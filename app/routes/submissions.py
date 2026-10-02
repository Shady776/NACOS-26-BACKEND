import logging
import os
from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from ..models import (
    Assignment,
    Course,
    Enrollment,
    NotificationType,
    Submission,
    SubmissionStatus,
    User,
    UserRole,
)
from ..oauth2 import get_current_student, get_current_teacher, get_current_user
from ..schemas import (
    SubmissionAIGradeRequest,
    SubmissionDetailResponse,
    SubmissionGrade,
    SubmissionManualGrade,
    SubmissionResponse,
)
from ..services.grading_runner import GradingError, apply_grade, get_job, grade_one, make_ai_service
from ..utils.cloud_storage import (
    delete_stored_file,
    media_type_for_extension,
    stored_file_extension,
    stream_stored_file,
    upload_private_file,
)
from ..utils.file_extraction import TEXT_EXTENSIONS
from ..utils.file_validation import validate_upload_file
from ..utils.sanitize import sanitize_html
from .Notifications import fan_out

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/submissions", tags=["Submissions"])

# Submissions can be documents, archives, images of handwritten work, or
# source code — TEXT_EXTENSIONS covers the code/text formats AI grading
# knows how to read (kept in file_extraction.py as the single source of
# truth so the two stay in sync).
SUBMISSION_ALLOWED_EXTENSIONS = {
    'pdf', 'doc', 'docx', 'ppt', 'pptx', 'zip', 'rar',
    'png', 'jpg', 'jpeg'
} | TEXT_EXTENSIONS

MAX_SUBMISSION_FILE_SIZE = 50 * 1024 * 1024  # 50 MB


# ── Internal helpers ──────────────────────────────────────────────────────────

def _notify_graded(db, submission: Submission) -> None:
    """Call just before db.commit() in any grade endpoint."""
    assignment = submission.assignment
    fan_out(
        db,
        student_ids=[str(submission.student_id)],
        type=NotificationType.ASSIGNMENT_GRADED,
        title=f"Assignment graded — {assignment.course.course_code}",
        message=(
            f'Your submission for "{assignment.title}" has been graded. '
            f'You scored {submission.score}/{assignment.max_score}. Tap to view your feedback.'
        ),
        assignment_id=str(assignment.id),
        course_id=str(assignment.course_id),
    )


def _upload_submission_file(file: UploadFile, assignment_id: str) -> str:
    """Validate and store a student's file as a private file. Returns its stored URL."""
    validate_upload_file(
        file,
        allowed_extensions=SUBMISSION_ALLOWED_EXTENSIONS,
        max_size_bytes=MAX_SUBMISSION_FILE_SIZE,
    )
    extension = os.path.splitext(file.filename or "")[1].lstrip(".").lower()
    try:
        result = upload_private_file(
            file.file,
            folder=f"submissions/{assignment_id}",
            extension=extension,
        )
    except Exception:
        logger.exception("Cloudinary upload failed for assignment %s", assignment_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to upload the file. Please try again.",
        )
    return result["secure_url"]


def _delete_file_quietly(file_url: Optional[str]) -> None:
    """Best-effort removal of a stored file. A failure is logged, never raised."""
    if not file_url:
        return
    try:
        delete_stored_file(file_url)
    except Exception:
        logger.exception("Could not delete stored file %s", file_url)


def _ensure_can_view(submission: Submission, user: User) -> None:
    """Admin: any. Student: their own. Teacher: submissions in their own courses."""
    if user.role == UserRole.ADMIN:
        return
    if user.role == UserRole.STUDENT:
        if submission.student_id == user.id:
            return
    elif user.role == UserRole.TEACHER:
        if submission.assignment.course.teacher_id == user.id:
            return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You don't have access to this submission",
    )


# ── POST / ────────────────────────────────────────────────────────────────────

# Plain `def`: the blocking file upload runs in a thread pool instead of freezing the server.
@router.post("/", response_model=SubmissionResponse, status_code=status.HTTP_201_CREATED)
def submit_assignment(
    assignment_id: str = Form(...),
    content: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_student)
):
    """Submit an assignment with text, a file, or both."""
    try:
        assignment_uuid = UUID(assignment_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid assignment ID format")

    has_text = bool(content and content.strip())
    if not has_text and not file:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Either content or file must be provided")

    assignment = db.query(Assignment).filter(Assignment.id == str(assignment_uuid)).first()
    if not assignment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found")

    enrollment = db.query(Enrollment).filter(
        Enrollment.student_id == current_user.id,
        Enrollment.course_id == assignment.course_id
    ).first()
    if not enrollment:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You are not enrolled in this course")

    existing = db.query(Submission).filter(
        Submission.assignment_id == str(assignment_uuid),
        Submission.student_id == current_user.id
    ).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You have already submitted this assignment. Use update endpoint to modify.")

    file_url = _upload_submission_file(file, str(assignment_uuid)) if file else None

    submission_status = SubmissionStatus.SUBMITTED
    due_date = assignment.due_date
    if due_date is not None and due_date.tzinfo is None:
        due_date = due_date.replace(tzinfo=timezone.utc)  # SQLite returns naive datetimes
    if due_date and datetime.now(timezone.utc) > due_date:
        submission_status = SubmissionStatus.LATE

    try:
        new_submission = Submission(
            assignment_id=str(assignment_uuid),
            student_id=str(current_user.id),
            content=sanitize_html(content) if has_text else None,  # strip scripts etc. even if the browser skipped DOMPurify
            file_url=file_url,
            status=submission_status
        )
        db.add(new_submission)
        db.commit()
        db.refresh(new_submission)
    except Exception:
        db.rollback()
        _delete_file_quietly(file_url)  # don't leave an orphaned upload behind
        raise

    return new_submission


# ── Static-segment GET routes (must come before /{submission_id}) ─────────────

@router.get("/my-submissions", response_model=List[SubmissionDetailResponse])
def get_my_submissions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_student)
):
    """Get all submissions for the current student with full assignment details."""
    return db.query(Submission).options(
        joinedload(Submission.assignment).joinedload(Assignment.course),
        joinedload(Submission.student)
    ).filter(Submission.student_id == current_user.id).all()


@router.get("/assignment/{assignment_id}", response_model=List[SubmissionDetailResponse])
def get_assignment_submissions(
    assignment_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_teacher)
):
    """Get all submissions for an assignment (teacher only)."""
    assignment = db.query(Assignment).filter(Assignment.id == str(assignment_id)).first()
    if not assignment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found")

    if assignment.course.teacher_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only view submissions for your own courses")

    return db.query(Submission).filter(Submission.assignment_id == str(assignment_id)).all()


@router.get("/student/{student_id}/course/{course_id}", response_model=List[SubmissionDetailResponse])
def get_student_course_submissions(
    student_id: UUID,
    course_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_teacher)
):
    course = db.query(Course).filter(Course.id == str(course_id)).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    if course.teacher_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only view submissions for your own courses")

    return db.query(Submission).options(
        joinedload(Submission.assignment),
        joinedload(Submission.student)
    ).join(Assignment).filter(
        Submission.student_id == str(student_id),
        Assignment.course_id == str(course_id)
    ).all()


# ── Dynamic /{submission_id} routes (must come last) ──────────────────────────

@router.get("/{submission_id}", response_model=SubmissionDetailResponse)
def get_submission(
    submission_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    submission = db.query(Submission).filter(Submission.id == str(submission_id)).first()
    if not submission:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found")

    _ensure_can_view(submission, current_user)
    return submission


# Plain `def`: the blocking download runs in a thread pool.
@router.get("/{submission_id}/file")
def download_submission_file(
    submission_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Download the file attached to a submission. Its student, the course teacher, or an admin only."""
    submission = db.query(Submission).options(
        joinedload(Submission.assignment).joinedload(Assignment.course),
        joinedload(Submission.student)
    ).filter(Submission.id == str(submission_id)).first()
    if not submission:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found")

    _ensure_can_view(submission, current_user)

    if not submission.file_url:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="This submission has no attached file")

    extension = stored_file_extension(submission.file_url)
    student = submission.student
    label = student.matric_number or student.username
    filename = f"{label}_{submission.assignment.title}.{extension or 'bin'}"

    return stream_stored_file(
        submission.file_url,
        filename=filename,
        media_type=media_type_for_extension(extension),
    )


# Plain `def`: the blocking file upload runs in a thread pool.
@router.put("/{submission_id}", response_model=SubmissionResponse)
def update_submission(
    submission_id: UUID,
    content: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_student)
):
    """Update a submission (before grading). Send new text, a replacement file, or both."""
    submission = db.query(Submission).filter(Submission.id == str(submission_id)).first()
    if not submission:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found")

    if submission.student_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only update your own submissions")

    if submission.status == SubmissionStatus.GRADED:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot update a graded submission")

    # Work out the result first, so nothing is uploaded for an update that would leave the submission empty.
    if content is None:
        new_content = submission.content
    else:
        new_content = sanitize_html(content) if content.strip() else None

    if not new_content and not file and not submission.file_url:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="A submission needs text or a file")

    old_file_url = submission.file_url
    new_file_url = _upload_submission_file(file, str(submission.assignment_id)) if file else None

    submission.content = new_content
    if new_file_url:
        submission.file_url = new_file_url
    submission.submitted_at = datetime.now(timezone.utc)

    try:
        db.commit()
        db.refresh(submission)
    except Exception:
        db.rollback()
        _delete_file_quietly(new_file_url)
        raise

    # Only after the new file is safely saved, remove the one it replaced.
    if new_file_url:
        _delete_file_quietly(old_file_url)

    return submission


@router.post("/{submission_id}/grade/ai", response_model=SubmissionResponse)
async def grade_submission_with_ai(
    submission_id: UUID,
    grade_request: SubmissionAIGradeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_teacher)
):
    submission = db.query(Submission).filter(Submission.id == str(submission_id)).first()
    if not submission:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found")

    assignment = submission.assignment
    if assignment.course.teacher_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only grade submissions for your own courses")

    # Criteria typed now win; otherwise use the ones saved on the assignment.
    criteria = (grade_request.criteria or assignment.grading_criteria or "").strip()
    if not criteria:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Please provide grading criteria for AI grading")

    # Don't fight a batch run that is grading this same assignment right now.
    job = get_job(str(assignment.id))
    if job and job.status == "running":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A batch grading run is in progress for this assignment. Wait for it to finish.")

    try:
        # Reads the typed answer and the attached file (code, PDF, DOCX, ZIP, image or scan).
        result = await grade_one(make_ai_service(), submission, assignment, criteria)
    except GradingError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))

    apply_grade(db, submission, assignment, result)
    if criteria != (assignment.grading_criteria or ""):
        assignment.grading_criteria = criteria
    db.commit()
    db.refresh(submission)
    return submission


@router.post("/{submission_id}/grade/manual", response_model=SubmissionResponse)
def grade_submission_manually(
    submission_id: UUID,
    grade_data: SubmissionManualGrade,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_teacher)
):
    """Manual grading by teacher with percentage or direct score."""
    submission = db.query(Submission).filter(Submission.id == str(submission_id)).first()
    if not submission:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found")

    if submission.assignment.course.teacher_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only grade submissions for your own courses")

    if grade_data.percentage is not None:
        if not 0 <= grade_data.percentage <= 100:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Percentage must be between 0 and 100")
        calculated_score = (grade_data.percentage / 100) * submission.assignment.max_score
    elif grade_data.score is not None:
        if grade_data.score > submission.assignment.max_score:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Score cannot exceed maximum score of {submission.assignment.max_score}")
        calculated_score = grade_data.score
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Either percentage or score must be provided")

    submission.score     = calculated_score
    submission.feedback  = grade_data.feedback
    submission.status    = SubmissionStatus.GRADED
    submission.graded_at = datetime.now(timezone.utc)

    # ── TRIGGER 3 (manual): Notify student ───────────────────────────────────
    _notify_graded(db, submission)

    db.commit()
    db.refresh(submission)
    return submission


@router.post("/{submission_id}/grade", response_model=SubmissionResponse)
def grade_submission(
    submission_id: UUID,
    grade_data: SubmissionGrade,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_teacher)
):
    """Legacy grading endpoint."""
    submission = db.query(Submission).filter(Submission.id == str(submission_id)).first()
    if not submission:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found")

    if submission.assignment.course.teacher_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only grade submissions for your own courses")

    if grade_data.score > submission.assignment.max_score:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Score cannot exceed maximum score of {submission.assignment.max_score}")

    submission.score     = grade_data.score
    submission.feedback  = grade_data.feedback
    submission.status    = SubmissionStatus.GRADED
    submission.graded_at = datetime.now(timezone.utc)

    # ── TRIGGER 3 (legacy): Notify student ───────────────────────────────────
    _notify_graded(db, submission)

    db.commit()
    db.refresh(submission)
    return submission


@router.delete("/{submission_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_submission(
    submission_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_student)
):
    """Delete a submission (before grading)."""
    submission = db.query(Submission).filter(Submission.id == str(submission_id)).first()
    if not submission:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found")

    if submission.student_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only delete your own submissions")

    if submission.status == SubmissionStatus.GRADED:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot delete a graded submission")

    file_url = submission.file_url

    db.delete(submission)
    db.commit()

    # After the row is gone, remove the stored file (best effort).
    _delete_file_quietly(file_url)
    return None