from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from ..database import get_db
from ..models import Notification, NotificationType, Warning, User, Enrollment
from ..oauth2 import get_current_student

router = APIRouter(prefix="/notifications", tags=["Notifications"])


# ── Internal helpers — imported by assignments and submissions routers ─────────

def fan_out(
    db: Session,
    *,
    student_ids: List[str],
    type: NotificationType,
    title: str,
    message: str,
    assignment_id: str | None = None,
    test_id: str | None = None,
    course_id: str | None = None,
) -> None:
    """
    Bulk-create one Notification row per student.
    Always call this BEFORE db.commit() so it's part of the same transaction.
    """
    if not student_ids:
        return
    db.bulk_save_objects([
        Notification(
            user_id=sid,
            type=type,
            title=title,
            message=message,
            assignment_id=assignment_id,
            test_id=test_id,
            course_id=course_id,
        )
        for sid in student_ids
    ])


def get_enrolled_student_ids(db: Session, course_id: str) -> List[str]:
    """Return list of student_id strings enrolled in a course."""
    return [
        str(r.student_id)
        for r in db.query(Enrollment.student_id)
                   .filter(Enrollment.course_id == course_id)
                   .all()
    ]


# ── Student-facing endpoints ──────────────────────────────────────────────────

@router.get("/my", response_model=List[dict])
def get_my_notifications(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_student),
):
    """All notifications for the logged-in student, newest first."""
    rows = (
        db.query(Notification)
          .filter(Notification.user_id == current_user.id)
          .order_by(Notification.created_at.desc())
          .all()
    )
    return [
        {
            "id":            r.id,
            "type":          r.type.value,
            "title":         r.title,
            "message":       r.message,
            "assignment_id": r.assignment_id,
            "test_id":       r.test_id,
            "course_id":     r.course_id,
            "is_read":       r.is_read,
            "created_at":    r.created_at.isoformat(),
        }
        for r in rows
    ]


@router.get("/my/unread-count")
def get_notification_unread_count(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_student),
):
    count = (
        db.query(Notification)
          .filter(Notification.user_id == current_user.id, Notification.is_read == False)
          .count()
    )
    return {"total_unread": count}


@router.patch("/{notification_id}/read")
def mark_as_read(
    notification_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_student),
):
    notif = db.query(Notification).filter(
        Notification.id == notification_id,
        Notification.user_id == current_user.id,
    ).first()
    if not notif:
        raise HTTPException(status_code=404, detail="Notification not found")
    notif.is_read = True
    db.commit()
    return {"id": notif.id, "is_read": True}


@router.patch("/read-all", status_code=status.HTTP_200_OK)
def mark_all_read(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_student),
):
    db.query(Notification).filter(
        Notification.user_id == current_user.id,
        Notification.is_read == False,
    ).update({"is_read": True}, synchronize_session=False)
    db.commit()
    return {"message": "All notifications marked as read"}


@router.delete("/{notification_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_notification(
    notification_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_student),
):
    notif = db.query(Notification).filter(
        Notification.id == notification_id,
        Notification.user_id == current_user.id,
    ).first()
    if not notif:
        raise HTTPException(status_code=404, detail="Notification not found")
    db.delete(notif)
    db.commit()


# ── Warnings unread count — used by the sidebar badge in DashboardLayout ──────

@router.get("/warnings/unread-count")
def get_warnings_unread_count(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_student),
):
    """Number of unread warnings for the logged-in student."""
    count = (
        db.query(Warning)
          .filter(Warning.student_id == current_user.id, Warning.is_read == False)
          .count()
    )
    return {"total_unread": count}


@router.patch("/warnings/mark-read", status_code=status.HTTP_200_OK)
def mark_warnings_read(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_student),
):
    """Mark all warnings as read — call this when the student visits /student/warnings."""
    db.query(Warning).filter(
        Warning.student_id == current_user.id,
        Warning.is_read == False,
    ).update({"is_read": True}, synchronize_session=False)
    db.commit()
    return {"message": "All warnings marked as read"}