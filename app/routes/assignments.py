from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from uuid import UUID
from datetime import datetime, timezone
from ..database import get_db
from ..models import Assignment, Course, User, Enrollment, Submission, UserRole, NotificationType
from ..schemas import AssignmentCreate, AssignmentResponse, AssignmentUpdate, SubmissionAIGradeRequest, SubmissionStatus
from ..oauth2 import get_current_user, get_current_teacher, get_current_student
from ..services.ai_grading_service import AIGradingService
from sqlalchemy import func
from .Notifications import fan_out, get_enrolled_student_ids

router = APIRouter(prefix="/assignments", tags=["Assignments"])


@router.post("/", response_model=AssignmentResponse, status_code=status.HTTP_201_CREATED)
def create_assignment(
    assignment_data: AssignmentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_teacher)
):
    """Create a new assignment for a course (teacher only)"""
    course = db.query(Course).filter(Course.id == str(assignment_data.course_id)).first()
    if not course:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")

    if course.teacher_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only create assignments for your own courses")

    new_assignment = Assignment(
        course_id=str(assignment_data.course_id),
        title=assignment_data.title,
        description=assignment_data.description,
        max_score=assignment_data.max_score,
        due_date=assignment_data.due_date
    )
    db.add(new_assignment)
    db.flush()  # gets new_assignment.id without committing

    # ── TRIGGER 1: Notify enrolled students of new assignment ─────────────────
    student_ids = get_enrolled_student_ids(db, str(assignment_data.course_id))
    fan_out(
        db,
        student_ids=student_ids,
        type=NotificationType.ASSIGNMENT_CREATED,
        title=f"New assignment in {course.course_code}",
        message=f'"{new_assignment.title}" has been posted. Check it out!',
        assignment_id=str(new_assignment.id),
        course_id=str(assignment_data.course_id),
    )

    db.commit()
    db.refresh(new_assignment)
    return new_assignment


@router.post("/{assignment_id}/grade/ai-batch")
async def batch_grade_with_ai(
    assignment_id: UUID,
    grade_request: SubmissionAIGradeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_teacher)
):
    """Batch AI grading for all ungraded submissions in an assignment"""
    assignment = db.query(Assignment).filter(Assignment.id == str(assignment_id)).first()
    if not assignment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found")

    if assignment.course.teacher_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only grade submissions for your own courses")

    submissions = db.query(Submission).filter(
        Submission.assignment_id == str(assignment_id),
        Submission.status != SubmissionStatus.GRADED,
        Submission.content.isnot(None)
    ).all()

    if not submissions:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No ungraded text submissions found for this assignment")

    criteria = grade_request.criteria
    if not criteria:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Please provide grading criteria")

    try:
        ai_service = AIGradingService()
        graded_count = 0
        failed_count = 0

        for submission in submissions:
            try:
                grading_result = await ai_service.grade_submission(
                    submission_content=submission.content,
                    assignment_title=assignment.title,
                    assignment_description=assignment.description or "",
                    max_score=assignment.max_score,
                    criteria=criteria
                )
                submission.score = grading_result.score
                submission.feedback = grading_result.feedback
                submission.status = SubmissionStatus.GRADED
                submission.graded_at = datetime.now(timezone.utc)

                # ── TRIGGER 3 (batch): Notify each student their assignment was graded ──
                fan_out(
                    db,
                    student_ids=[str(submission.student_id)],
                    type=NotificationType.ASSIGNMENT_GRADED,
                    title=f"Assignment graded — {assignment.course.course_code}",
                    message=(
                        f'Your submission for "{assignment.title}" has been graded. '
                        f'You scored {grading_result.score}/{assignment.max_score}. Tap to view your feedback.'
                    ),
                    assignment_id=str(assignment.id),
                    course_id=str(assignment.course_id),
                )
                graded_count += 1

            except Exception as e:
                failed_count += 1
                print(f"Failed to grade submission {submission.id}: {str(e)}")
                continue

        db.commit()

        return {
            "message": "Batch grading completed",
            "total_submissions": len(submissions),
            "graded_successfully": graded_count,
            "failed": failed_count
        }

    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Batch AI grading failed: {str(e)}")


# ── Static-segment routes (must come before /{assignment_id}) ─────────────────

@router.get("/courses-list")
def get_teacher_courses_with_counts(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all courses for the current teacher with enrollment and assignment counts"""
    if current_user.role != UserRole.TEACHER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only teachers can access this endpoint")

    courses = db.query(Course).filter(Course.teacher_id == current_user.id).all()

    result = []
    for course in courses:
        enrolled_count   = db.query(func.count(Enrollment.id)).filter(Enrollment.course_id == course.id).scalar() or 0
        assignments_count = db.query(func.count(Assignment.id)).filter(Assignment.course_id == course.id).scalar() or 0

        result.append({
            "id":               str(course.id),
            "title":            course.title,
            "course_code":      course.course_code,
            "department":       course.department.value if course.department else None,
            "semester":         course.semester.value if course.semester else None,
            "credits":          course.credits,
            "description":      course.description,
            "enrolled_count":   enrolled_count,
            "assignments_count": assignments_count
        })

    return result


@router.get("/student/my-assignments")
def get_student_assignments(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_student)
):
    """Get all assignments for courses the student is enrolled in, with submission status"""
    enrollments = db.query(Enrollment).filter(Enrollment.student_id == current_user.id).all()
    course_ids  = [e.course_id for e in enrollments]

    if not course_ids:
        return []

    assignments = db.query(Assignment).filter(
        Assignment.course_id.in_(course_ids),
        Assignment.is_active == True
    ).all()

    result = []
    for assignment in assignments:
        submission = db.query(Submission).filter(
            Submission.assignment_id == str(assignment.id),
            Submission.student_id == current_user.id
        ).first()

        result.append({
            "id": str(assignment.id),
            "course_id": str(assignment.course_id),
            "title": assignment.title,
            "description": assignment.description,
            "max_score": assignment.max_score,
            "due_date": assignment.due_date.isoformat() if assignment.due_date else None,
            "created_at": assignment.created_at.isoformat(),
            "is_active": assignment.is_active,
            "course_code": assignment.course.course_code if assignment.course else None,
            "status": "Submitted" if submission else "Pending",
            "submission_id": str(submission.id) if submission else None,
            "submitted_at": submission.submitted_at.isoformat() if submission else None,
            "graded_at": submission.graded_at.isoformat() if submission and submission.graded_at else None,
            "grade": submission.score if submission and submission.status == "GRADED" else None
        })

    return result

@router.get("/course/{course_id}", response_model=List[AssignmentResponse])
def get_course_assignments(
    course_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all assignments for a specific course"""
    course = db.query(Course).filter(Course.id == str(course_id)).first()
    if not course:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")

    if current_user.role == "teacher":
        if course.teacher_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only view assignments for your own courses")
    else:
        enrollment = db.query(Enrollment).filter(
            Enrollment.student_id == current_user.id,
            Enrollment.course_id == str(course_id)
        ).first()
        if not enrollment:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You are not enrolled in this course")

    return db.query(Assignment).filter(Assignment.course_id == str(course_id)).all()


@router.get("/", response_model=List[AssignmentResponse])
def get_all_assignments(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    skip: int = 0,
    limit: int = 100
):
    if current_user.role == "teacher":
        courses    = db.query(Course).filter(Course.teacher_id == current_user.id).all()
        course_ids = [c.id for c in courses]
    else:
        enrollments = db.query(Enrollment).filter(Enrollment.student_id == current_user.id).all()
        course_ids  = [e.course_id for e in enrollments]

    return db.query(Assignment).filter(Assignment.course_id.in_(course_ids)).offset(skip).limit(limit).all()


# ── Dynamic /{assignment_id} routes (must come last) ─────────────────────────

@router.get("/{assignment_id}", response_model=AssignmentResponse)
def get_assignment(
    assignment_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    assignment = db.query(Assignment).filter(Assignment.id == str(assignment_id)).first()
    if not assignment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found")

    course = db.query(Course).filter(Course.id == str(assignment.course_id)).first()

    if current_user.role == UserRole.ADMIN:
        pass
    elif current_user.role == UserRole.TEACHER:
        if course.teacher_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only view assignments from your own courses")
    elif current_user.role == UserRole.STUDENT:
        enrollment = db.query(Enrollment).filter(
            Enrollment.student_id == current_user.id,
            Enrollment.course_id == str(assignment.course_id)
        ).first()
        if not enrollment:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only view assignments from courses you're enrolled in")
    else:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Unauthorized access")

    return assignment


@router.put("/{assignment_id}", response_model=AssignmentResponse)
def update_assignment(
    assignment_id: UUID,
    assignment_data: AssignmentUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_teacher)
):
    """Update an assignment — notifies enrolled students if title or description changed."""
    assignment = db.query(Assignment).filter(Assignment.id == str(assignment_id)).first()
    if not assignment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found")

    if assignment.course.teacher_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only update assignments for your own courses")

    # Snapshot before mutation
    old_title       = assignment.title
    old_description = assignment.description or ""

    update_data = assignment_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(assignment, field, value)

    # ── TRIGGER 2: Notify if title or description changed ─────────────────────
    new_title       = assignment.title
    new_description = assignment.description or ""

    title_changed       = new_title.strip()       != old_title.strip()
    description_changed = new_description.strip() != old_description.strip()

    if title_changed or description_changed:
        if title_changed and description_changed:
            what_changed = "title and instructions"
        elif title_changed:
            what_changed = "title"
        else:
            what_changed = "instructions"

        student_ids = get_enrolled_student_ids(db, str(assignment.course_id))
        fan_out(
            db,
            student_ids=student_ids,
            type=NotificationType.ASSIGNMENT_UPDATED,
            title=f"Assignment updated in {assignment.course.course_code}",
            message=f'The {what_changed} of "{assignment.title}" has been updated. Tap to review.',
            assignment_id=str(assignment.id),
            course_id=str(assignment.course_id),
        )

    db.commit()
    db.refresh(assignment)
    return assignment


@router.delete("/{assignment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_assignment(
    assignment_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_teacher)
):
    assignment = db.query(Assignment).filter(Assignment.id == str(assignment_id)).first()
    if not assignment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found")

    if assignment.course.teacher_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only delete assignments for your own courses")

    db.delete(assignment)
    db.commit()
    return None