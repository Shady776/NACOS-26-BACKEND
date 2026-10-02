# routers/course_materials.py
import logging
import os
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Course, CourseMaterial, Enrollment, User, UserRole
from ..oauth2 import get_current_teacher, get_current_user
from ..schemas import CourseMaterialDetailResponse, CourseMaterialResponse
from ..utils.cloud_storage import (
    delete_stored_file,
    media_type_for_extension,
    stream_stored_file,
    upload_private_file,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/course-materials", tags=["Course Materials"])

ALLOWED_EXTENSIONS = {"pdf", "doc", "docx", "ppt", "pptx", "txt", "zip", "rar"}
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB
MAX_TITLE_LENGTH = 200


# ── helpers ──────────────────────────────────────────────────────────────────

def _get_course_or_404(db: Session, course_id: str) -> Course:
    course = db.query(Course).filter(Course.id == str(course_id)).first()
    if not course:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")
    return course


def _get_material_or_404(db: Session, material_id: str) -> CourseMaterial:
    material = (
        db.query(CourseMaterial)
        .filter(CourseMaterial.id == str(material_id), CourseMaterial.is_active == True)  # noqa: E712
        .first()
    )
    if not material:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Material not found")
    return material


def _ensure_course_access(db: Session, course: Course, user: User) -> None:
    """Admin: always. Teacher: only their own course. Student: only if enrolled."""
    if user.role == UserRole.ADMIN:
        return

    if user.role == UserRole.TEACHER:
        if course.teacher_id == user.id:
            return
    elif user.role == UserRole.STUDENT:
        enrolled = (
            db.query(Enrollment.id)
            .filter(Enrollment.course_id == course.id, Enrollment.student_id == user.id)
            .first()
        )
        if enrolled and course.is_active:
            return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You don't have access to this course's materials",
    )


# ── endpoints ────────────────────────────────────────────────────────────────

# Plain `def` (not async): FastAPI runs it in a thread pool, so the blocking
# Cloudinary upload does not freeze the rest of the server.
@router.post("/", response_model=CourseMaterialResponse, status_code=status.HTTP_201_CREATED)
def upload_course_material(
    course_id: str = Form(...),
    title: str = Form(...),
    description: Optional[str] = Form(None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_teacher),
):
    """Upload course material. Only the course teacher can upload."""
    course = _get_course_or_404(db, course_id)

    if course.teacher_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only upload materials to your own courses",
        )

    title = title.strip()
    if not title:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Title is required")
    if len(title) > MAX_TITLE_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Title must be {MAX_TITLE_LENGTH} characters or fewer",
        )

    # Type check
    extension = os.path.splitext(file.filename or "")[1].lstrip(".").lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File type not allowed. Allowed types: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    # Size check (without loading the file into memory)
    file.file.seek(0, os.SEEK_END)
    size = file.file.tell()
    file.file.seek(0)
    if size == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="The file is empty")
    if size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File is too large. Maximum size is {MAX_FILE_SIZE // (1024 * 1024)} MB",
        )

    try:
        result = upload_private_file(
            file.file,
            folder=f"course_materials/{course.id}",
            extension=extension,
        )
    except Exception:
        logger.exception("Cloudinary upload failed for course %s", course.id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to upload the file to storage. Please try again.",
        )

    file_url = result["secure_url"]

    try:
        material = CourseMaterial(
            course_id=course.id,
            title=title,
            description=description,
            file_url=file_url,
            file_type=extension,
            file_size=result.get("bytes") or size,
            uploaded_by=current_user.id,
        )
        db.add(material)
        db.commit()
        db.refresh(material)
    except Exception:
        db.rollback()
        logger.exception("Saving material record failed for course %s", course.id)
        # Don't leave an orphaned file in Cloudinary
        try:
            delete_stored_file(file_url)
        except Exception:
            logger.exception("Could not clean up orphaned file %s", file_url)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save the material. Please try again.",
        )

    return material


@router.get("/course/{course_id}", response_model=List[CourseMaterialResponse])
def get_course_materials(
    course_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List materials for a course. Course teacher, enrolled students and admins only."""
    course = _get_course_or_404(db, course_id)
    _ensure_course_access(db, course, current_user)

    return (
        db.query(CourseMaterial)
        .filter(CourseMaterial.course_id == course.id, CourseMaterial.is_active == True)  # noqa: E712
        .order_by(CourseMaterial.uploaded_at.desc())
        .all()
    )


@router.get("/{material_id}", response_model=CourseMaterialDetailResponse)
def get_material_detail(
    material_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Details of one material. Same access rules as the list."""
    material = _get_material_or_404(db, material_id)
    course = _get_course_or_404(db, material.course_id)
    _ensure_course_access(db, course, current_user)
    return material


# Plain `def`: the blocking download runs in a thread pool, so one student
# downloading a big file no longer holds up everyone else.
@router.get("/{material_id}/download")
def download_material(
    material_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Download a material by streaming it from Cloudinary."""
    material = _get_material_or_404(db, material_id)
    course = _get_course_or_404(db, material.course_id)
    _ensure_course_access(db, course, current_user)

    file_type = (material.file_type or "").lower()
    return stream_stored_file(
        material.file_url,
        filename=f"{material.title}.{file_type or 'bin'}",
        media_type=media_type_for_extension(file_type),
    )


@router.delete("/{material_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_material(
    material_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_teacher),
):
    """Delete a material (database row and the stored file). Uploader or course teacher only."""
    material = db.query(CourseMaterial).filter(CourseMaterial.id == str(material_id)).first()
    if not material:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Material not found")

    course = db.query(Course).filter(Course.id == material.course_id).first()
    is_owner = material.uploaded_by == current_user.id
    is_course_teacher = course is not None and course.teacher_id == current_user.id
    if not (is_owner or is_course_teacher):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only delete materials from your own courses",
        )

    # Remove the stored file first. If that fails, keep the database row so the
    # teacher can retry instead of losing track of a file that still exists.
    try:
        delete_stored_file(material.file_url)
    except Exception:
        logger.exception("Cloudinary delete failed for material %s", material.id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not delete the file from storage. Please try again.",
        )

    db.delete(material)
    db.commit()
    return None