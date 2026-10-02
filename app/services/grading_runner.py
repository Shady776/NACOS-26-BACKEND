import asyncio
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

from fastapi.concurrency import run_in_threadpool

from ..database import SessionLocal
from ..models import Assignment, NotificationType, Submission, SubmissionStatus
from ..routes.Notifications import fan_out
from ..utils.cloud_storage import fetch_stored_file_bytes, stored_file_extension
from ..utils.file_extraction import ExtractionError, extract_gradable_text
from .ai_grading_service import AIGradingService

logger = logging.getLogger(__name__)

IMAGE_MEDIA_TYPES = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp"}

BATCH_CONCURRENCY = 3        # submissions graded at the same time
MAX_RECORDED_ERRORS = 25     # failures listed back to the teacher


class GradingError(Exception):
    """A submission could not be graded. The message is safe to show the teacher."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


# ── grading one submission ───────────────────────────────────────────────────

def make_ai_service() -> AIGradingService:
    """Create the AI service, or fail with a message the teacher can act on."""
    try:
        return AIGradingService()
    except Exception:
        logger.exception("Could not set up the AI grading service")
        raise GradingError(
            "AI grading is not set up correctly on the server. Check OPENROUTER_MODEL "
            "(and OPENROUTER_VISION_MODEL if set): each must be a model ID copied from "
            "openrouter.ai/models, in the form provider/model-name.",
            500,
        )


def submission_kind(submission: Submission) -> str:
    """'files' if a file is attached (with or without text), else 'text'."""
    return "files" if submission.file_url else "text"


async def grade_one(
    ai_service: AIGradingService,
    submission: Submission,
    assignment: Assignment,
    criteria: str,
):
    """Read the submission and grade it. Raises GradingError with a readable reason."""
    typed = (submission.content or "").strip()

    if not typed and not submission.file_url:
        raise GradingError("This submission has no text or file to grade")

    file_bytes: Optional[bytes] = None
    extension = ""
    file_text: Optional[str] = None
    vision_reason: Optional[str] = None  # why we need the vision model, if we do

    if submission.file_url:
        extension = stored_file_extension(submission.file_url)
        try:
            file_bytes = await run_in_threadpool(fetch_stored_file_bytes, submission.file_url)
        except Exception:
            logger.exception("Could not download the file of submission %s", submission.id)
            raise GradingError("Could not retrieve the submitted file. Try again.", 502)

        if extension in IMAGE_MEDIA_TYPES:
            vision_reason = "an image"
        else:
            filename = f"submission.{extension}" if extension else "submission"
            try:
                file_text = await run_in_threadpool(extract_gradable_text, file_bytes, filename)
            except ExtractionError:
                vision_reason = "a scanned PDF"  # the vision model can still read it
            except ExtractionError as e:
                raise GradingError(str(e))

    try:
        if vision_reason:
            if ai_service.vision_model is None:
                raise GradingError(
                    f"This is {vision_reason}, which needs a vision model to read. "
                    "Set OPENROUTER_VISION_MODEL on the server, or grade it manually."
                )
            media_type = IMAGE_MEDIA_TYPES.get(extension, "application/pdf")
            return await ai_service.grade_file_with_vision(
                file_bytes=file_bytes,
                media_type=media_type,
                assignment_title=assignment.title,
                assignment_description=assignment.description or "",
                max_score=assignment.max_score,
                criteria=criteria,
                typed_answer=typed or None,
            )

        gradable = typed
        if file_text:
            gradable = f"{typed}\n\n--- Attached file ---\n{file_text}" if typed else file_text
        return await ai_service.grade_submission(
            submission_content=gradable,
            assignment_title=assignment.title,
            assignment_description=assignment.description or "",
            max_score=assignment.max_score,
            criteria=criteria,
        )
    except GradingError:
        raise
    except ValueError as e:
        raise GradingError(str(e))
    except Exception:
        logger.exception("AI grading failed for submission %s", submission.id)
        raise GradingError("The AI service failed to grade this submission. Try again.", 502)


def apply_grade(db, submission: Submission, assignment: Assignment, result) -> None:
    """Save the AI result on the submission and notify the student. Caller commits."""
    submission.score = result.score
    submission.feedback = result.feedback
    submission.status = SubmissionStatus.GRADED
    submission.graded_at = datetime.now(timezone.utc)
    fan_out(
        db,
        student_ids=[str(submission.student_id)],
        type=NotificationType.ASSIGNMENT_GRADED,
        title=f"Assignment graded — {assignment.course.course_code}",
        message=(
            f'Your submission for "{assignment.title}" has been graded. '
            f"You scored {result.score}/{assignment.max_score}. Tap to view your feedback."
        ),
        assignment_id=str(assignment.id),
        course_id=str(assignment.course_id),
    )


# ── batch jobs ───────────────────────────────────────────────────────────────

@dataclass
class BatchJob:
    assignment_id: str
    total: int
    status: str = "running"            # running | done | error
    processed: int = 0
    graded: int = 0
    failed: int = 0
    skipped: int = 0                    # graded by someone else while the job ran
    errors: List[dict] = field(default_factory=list)
    message: Optional[str] = None
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    finished_at: Optional[str] = None

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "total": self.total,
            "processed": self.processed,
            "graded": self.graded,
            "failed": self.failed,
            "skipped": self.skipped,
            "errors": self.errors,
            "message": self.message,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


_jobs: Dict[str, BatchJob] = {}
_jobs_lock = threading.Lock()


def get_job(assignment_id: str) -> Optional[BatchJob]:
    with _jobs_lock:
        return _jobs.get(assignment_id)


def start_job(assignment_id: str, submission_ids: List[str], criteria: str) -> BatchJob:
    """
    Register a job and start it. Raises GradingError(409) if this assignment is
    already being graded: that is the lock that stops two clicks from grading
    (and notifying) the same students twice.
    """
    with _jobs_lock:
        existing = _jobs.get(assignment_id)
        if existing and existing.status == "running":
            raise GradingError("This assignment is already being graded. Wait for it to finish.", 409)
        job = BatchJob(assignment_id=assignment_id, total=len(submission_ids))
        _jobs[assignment_id] = job

    asyncio.create_task(_run_job(job, submission_ids, criteria))
    return job


async def _grade_in_batch(job: BatchJob, submission_id: str, criteria: str, ai_service, semaphore) -> None:
    async with semaphore:
        db = SessionLocal()
        label = submission_id
        try:
            def load():
                sub = db.get(Submission, submission_id)
                if sub is None:
                    return None, None, submission_id
                student = sub.student
                name = (student.full_name or student.username) if student else submission_id
                return sub, sub.assignment, name

            submission, assignment, label = await run_in_threadpool(load)
            if submission is None or submission.status == SubmissionStatus.GRADED:
                job.skipped += 1
                return

            result = await grade_one(ai_service, submission, assignment, criteria)

            def save():
                db.refresh(submission)
                if submission.status == SubmissionStatus.GRADED:
                    return False  # the teacher graded it by hand while the AI was working
                apply_grade(db, submission, assignment, result)
                db.commit()
                return True

            if await run_in_threadpool(save):
                job.graded += 1
            else:
                job.skipped += 1
        except GradingError as e:
            await run_in_threadpool(db.rollback)
            _record_failure(job, submission_id, label, str(e))
        except Exception:
            logger.exception("Batch grading crashed on submission %s", submission_id)
            await run_in_threadpool(db.rollback)
            _record_failure(job, submission_id, label, "Unexpected error while grading")
        finally:
            job.processed += 1
            await run_in_threadpool(db.close)


def _record_failure(job: BatchJob, submission_id: str, label: str, reason: str) -> None:
    job.failed += 1
    if len(job.errors) < MAX_RECORDED_ERRORS:
        job.errors.append({"submission_id": submission_id, "student": label, "reason": reason})


async def _run_job(job: BatchJob, submission_ids: List[str], criteria: str) -> None:
    try:
        ai_service = make_ai_service()
        semaphore = asyncio.Semaphore(BATCH_CONCURRENCY)
        await asyncio.gather(
            *(_grade_in_batch(job, sid, criteria, ai_service, semaphore) for sid in submission_ids)
        )
        job.status = "done"
    except Exception as e:
        logger.exception("Batch grading job failed")
        job.status = "error"
        job.message = (
            str(e) if isinstance(e, GradingError)
            else "Batch grading stopped unexpectedly. Submissions already graded were saved."
        )
    finally:
        job.finished_at = datetime.now(timezone.utc).isoformat()
