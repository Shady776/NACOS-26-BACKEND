from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import datetime, timezone
from pydantic import BaseModel
from typing import Optional

from ..database import get_db
from ..models import Warning, Course, User, UserRole, NotificationType
from ..oauth2 import get_current_admin, get_current_user, get_current_student
from .Notifications import fan_out

router = APIRouter(prefix="/warnings", tags=["Warnings"])


class WarningCreate(BaseModel):
    student_id: str
    course_id: Optional[str] = None
    reason: str


@router.post("", status_code=201)
def issue_warning(
    payload: WarningCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role not in [UserRole.TEACHER, UserRole.ADMIN]:
        raise HTTPException(403, "Not authorized")

    if payload.course_id and current_user.role == UserRole.TEACHER:
        course = db.query(Course).filter(Course.id == payload.course_id).first()
        if not course or course.teacher_id != current_user.id:
            raise HTTPException(403, "You can only warn students in your own courses")

    warning = Warning(
        student_id=payload.student_id,
        issued_by=str(current_user.id),
        course_id=payload.course_id,
        reason=payload.reason,
        created_at=datetime.now(timezone.utc)
    )
    db.add(warning)

    # ── Notification hook: notify the student they received a warning ──────────
    course_code = None
    if payload.course_id:
        course = db.query(Course).filter(Course.id == payload.course_id).first()
        course_code = f" in {course.course_code}" if course and course.course_code else ""

    fan_out(
        db,
        student_ids=[payload.student_id],
        type=NotificationType.WARNING,
        title="You have received a warning",
        message=f"A warning has been issued to you{course_code or ''}: {payload.reason}",
        course_id=payload.course_id,
    )
    # ──────────────────────────────────────────────────────────────────────────

    db.commit()
    db.refresh(warning)
    return {"id": str(warning.id), "message": "Warning issued successfully"}


@router.get("/student/{student_id}")
def get_student_warnings(
    student_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    warnings = (
        db.query(Warning)
        .filter(Warning.student_id == student_id)
        .order_by(Warning.created_at.desc())
        .all()
    )
    return [
        {
            "id": str(w.id),
            "student_id": str(w.student_id),
            "issued_by": str(w.issued_by),
            "course_id": str(w.course_id) if w.course_id else None,
            "course_code": w.course.course_code if w.course_id and w.course else "Unknown Course",
            "course_name": w.course.title if w.course_id and w.course else None,
            "reason": w.reason,
            "is_read": w.is_read,
            "created_at": w.created_at.isoformat()
        }
        for w in warnings
    ]


@router.get("/my")
def get_my_warnings(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_student)
):
    """Logged-in student views their own warnings."""
    warnings = (
        db.query(Warning)
        .filter(Warning.student_id == current_user.id)
        .order_by(Warning.created_at.desc())
        .all()
    )
    return [
        {
            "id": str(w.id),
            "course_id": str(w.course_id) if w.course_id else None,
            "course_code": w.course.course_code if w.course_id and w.course else "Unknown Course",
            "course_name": w.course.title if w.course_id and w.course else None,
            "reason": w.reason,
            "is_read": w.is_read,
            "created_at": w.created_at.isoformat()
        }
        for w in warnings
    ]


@router.patch("/my/mark-read", status_code=status.HTTP_200_OK)
def mark_my_warnings_read(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_student)
):
    """Mark all of the logged-in student's warnings as read.
    Call this when the student visits the /student/warnings page.
    """
    db.query(Warning).filter(
        Warning.student_id == current_user.id,
        Warning.is_read == False,
    ).update({"is_read": True}, synchronize_session=False)
    db.commit()
    return {"message": "All warnings marked as read"}


@router.get("/all", dependencies=[Depends(get_current_admin)])
def get_all_warnings(db: Session = Depends(get_db)):
    """Admin: get every warning across the platform."""
    warnings = (
        db.query(Warning)
        .order_by(Warning.created_at.desc())
        .all()
    )
    # Enrich with teacher info
    return [
        {
            "id": str(w.id),
            "student_id": str(w.student_id),
            "student_name": w.student.full_name or w.student.username if w.student else "Unknown",
            "student_email": w.student.email if w.student else None,
            "issued_by": str(w.issued_by),
            "teacher_name": w.issuer.full_name or w.issuer.username if hasattr(w, 'issuer') and w.issuer else None,
            "course_id": str(w.course_id) if w.course_id else None,
            "course_code": w.course.course_code if w.course_id and w.course else None,
            "course_name": w.course.title if w.course_id and w.course else None,
            "reason": w.reason,
            "is_read": w.is_read,
            "created_at": w.created_at.isoformat()
        }
        for w in warnings
    ]