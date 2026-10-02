import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from uuid import UUID
from ..database import get_db
from ..models import Course, CourseMaterial, User, Enrollment
from ..schemas import CourseCreate, CourseResponse, CourseUpdate, CourseDetailResponse
from ..oauth2 import get_current_user, get_current_teacher
from ..utils.cloud_storage import delete_stored_file

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/courses", tags=["Courses"])

@router.post("/", response_model=CourseResponse, status_code=status.HTTP_201_CREATED)
def create_course(
    course_data: CourseCreate, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_teacher)
):
    """
    Create a new course. Only teachers can create courses.
    The instructor name is automatically set from the teacher's profile (full_name).
    """
    instructor_name = current_user.full_name if current_user.full_name else current_user.username
    
    new_course = Course(
        title=course_data.title,
        course_code=course_data.course_code,
        description=course_data.description,
        department=course_data.department,
        semester=course_data.semester,
        instructor=instructor_name,
        schedule=course_data.schedule,
        location=course_data.location,
        credits=course_data.credits,
        teacher_id=current_user.id
    )
    
    db.add(new_course)
    db.commit()
    db.refresh(new_course)
    
    return new_course


@router.get("/", response_model=List[CourseResponse])
def get_all_courses(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    skip: int = 0,
    limit: int = 100
):
    """
    Get all courses:
    - Teachers see only their own courses
    - Students see all available courses
    """
    if current_user.role == "teacher":
        courses = db.query(Course).filter(
            Course.teacher_id == current_user.id
        ).offset(skip).limit(limit).all()
    else:
        courses = db.query(Course).filter(
            Course.is_active == True
        ).offset(skip).limit(limit).all()
    
    return courses


@router.get("/{course_id}", response_model=CourseDetailResponse)
def get_course(
    course_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get detailed information about a specific course.
    Teachers can only view their own courses.
    Students can view any active course.
    """
    course = db.query(Course).filter(Course.id == str(course_id)).first()
    
    if not course:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Course not found"
        )
    
    if current_user.role == "teacher":
        if course.teacher_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have access to this course"
            )
    elif current_user.role == "student":
        if not course.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This course is not available"
            )
    
    return course


@router.put("/{course_id}", response_model=CourseResponse)
def update_course(
    course_id: UUID,
    course_data: CourseUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_teacher)
):
    """
    Update a course. Only the course teacher can update it.
    """
    course = db.query(Course).filter(Course.id == str(course_id)).first()
    
    if not course:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Course not found"
        )
    
    if course.teacher_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only update your own courses"
        )
    
    update_data = course_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(course, field, value)
    
    course.instructor = current_user.full_name if current_user.full_name else current_user.username
    
    db.commit()
    db.refresh(course)
    
    return course


@router.delete("/{course_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_course(
    course_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_teacher)
):
    """
    Delete a course. Only the course teacher can delete it.
    This will also delete all associated assignments and enrollments (cascade),
    and the course material files stored in Cloudinary.
    """
    course = db.query(Course).filter(Course.id == str(course_id)).first()
    
    if not course:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Course not found"
        )
    
    if course.teacher_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only delete your own courses"
        )
    
    # Collect the stored files before the rows (and their URLs) are gone.
    material_urls = [
        row.file_url
        for row in db.query(CourseMaterial.file_url)
        .filter(CourseMaterial.course_id == course.id)
        .all()
    ]

    db.delete(course)
    db.commit()

    # Best effort, after the course is deleted: a storage hiccup should not stop
    # the teacher from deleting a course. Failures are logged for cleanup.
    for url in material_urls:
        try:
            delete_stored_file(url)
        except Exception:
            logger.exception("Could not delete stored file %s for deleted course %s", url, course_id)
    
    return None


@router.get("/{course_id}/students", response_model=List[dict])
def get_course_students(
    course_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_teacher)
):
    """
    Get all students enrolled in a course. Only accessible by the course teacher.
    """
    course = db.query(Course).filter(Course.id == str(course_id)).first()
    
    if not course:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Course not found"
        )
    
    if course.teacher_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only view students in your own courses"
        )
    
    enrollments = db.query(Enrollment).filter(
        Enrollment.course_id == str(course_id)
    ).all()
    
    students = [{
        "student_id": enrollment.student.id,
        "username": enrollment.student.username,
        "full_name": enrollment.student.full_name,
        "email": enrollment.student.email,
        "enrolled_at": enrollment.enrolled_at
    } for enrollment in enrollments]
    
    return students