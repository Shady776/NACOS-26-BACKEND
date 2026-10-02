from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload
from typing import List
from ..database import get_db
from ..models import Enrollment, Course, User, UserRole
from ..schemas import EnrollmentCreate, EnrollmentResponse
from ..oauth2 import get_current_user, get_current_student, get_current_teacher, get_current_admin

router = APIRouter(prefix="/enrollments", tags=["Enrollments"])


# ── static / fixed-path routes first ─────────────────────────────────────────

@router.post("", response_model=EnrollmentResponse, status_code=status.HTTP_201_CREATED)
def enroll_in_course(
    enrollment_data: EnrollmentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_student)
):
    """Student enrolls in a course"""
    course = db.query(Course).filter(Course.id == str(enrollment_data.course_id)).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    existing_enrollment = db.query(Enrollment).filter(
        Enrollment.student_id == current_user.id,
        Enrollment.course_id == str(enrollment_data.course_id)
    ).first()

    if existing_enrollment:
        raise HTTPException(status_code=400, detail="You are already enrolled in this course")

    new_enrollment = Enrollment(
        student_id=current_user.id,
        course_id=str(enrollment_data.course_id)
    )

    db.add(new_enrollment)
    db.commit()
    db.refresh(new_enrollment)
    return new_enrollment


@router.get("/my-courses", response_model=List[EnrollmentResponse])
def get_my_enrollments(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_student)
):
    """Get all courses the current student is enrolled in"""
    enrollments = db.query(Enrollment).options(
        joinedload(Enrollment.course),
        joinedload(Enrollment.student)
    ).filter(Enrollment.student_id == current_user.id).all()
    return enrollments


@router.get("/course/{course_id}/students")
def get_course_students(
    course_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all students enrolled in a specific course (teacher, admin only)"""
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    if current_user.role != UserRole.ADMIN and course.teacher_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only view students in your own courses")

    enrollments = db.query(Enrollment).options(
        joinedload(Enrollment.student),
        joinedload(Enrollment.course)
    ).filter(Enrollment.course_id == course_id).all()

    result = []
    for enrollment in enrollments:
        result.append({
            "id": str(enrollment.id),
            "student_id": str(enrollment.student_id),
            "course_id": str(enrollment.course_id),
            "enrolled_at": enrollment.enrolled_at.isoformat(),
            "student": {
                "id": str(enrollment.student.id),
                "email": enrollment.student.email,
                "username": enrollment.student.username,
                "full_name": enrollment.student.full_name,
                "role": enrollment.student.role,
                "matric_number": enrollment.student.matric_number,
                "department": enrollment.student.department,
                "created_at": enrollment.student.created_at.isoformat()
            } if enrollment.student else None,
            "course": {
                "id": str(enrollment.course.id),
                "title": enrollment.course.title,
                "course_code": enrollment.course.course_code,
                "department": enrollment.course.department,
                "semester": enrollment.course.semester,
                "credits": enrollment.course.credits
            } if enrollment.course else None
        })

    return result


# ── wildcard routes last ──────────────────────────────────────────────────────

@router.delete("/teacher/remove/{enrollment_id}", status_code=status.HTTP_204_NO_CONTENT)
def teacher_remove_student(
    enrollment_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_teacher)
):
    """Teacher removes a student from their course"""
    enrollment = db.query(Enrollment).options(
        joinedload(Enrollment.course)
    ).filter(Enrollment.id == enrollment_id).first()

    if not enrollment:
        raise HTTPException(status_code=404, detail="Enrollment not found")

    if enrollment.course.teacher_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only remove students from your own courses")

    db.delete(enrollment)
    db.commit()
    return None


@router.delete("/{enrollment_id}", status_code=status.HTTP_204_NO_CONTENT)
def unenroll(
    enrollment_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_student)
):
    """Student unenrolls from a course"""
    enrollment = db.query(Enrollment).filter(Enrollment.id == enrollment_id).first()

    if not enrollment:
        raise HTTPException(status_code=404, detail="Enrollment not found")

    if enrollment.student_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only unenroll yourself")

    db.delete(enrollment)
    db.commit()
    return None