from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List
from datetime import datetime, timezone

from ..database import get_db
from ..models import User, Course, Assignment, Submission, Enrollment, SubmissionStatus, UserRole
from ..schemas import UserResponse, CourseResponse, AssignmentResponse, CourseCreate, AssignmentCreate
from ..oauth2 import get_current_user
from pydantic import BaseModel

router = APIRouter(prefix="/teacher/dashboard", tags=["Teacher Dashboard"])


class TeacherDashboardStats(BaseModel):
    active_courses: int
    total_students: int
    active_assignments: int
    pending_grading: int

class RecentSubmissionItem(BaseModel):
    student_name: str
    student_initials: str
    file_name: str
    submitted_at: datetime
    assignment_title: str
    course_code: str

class TeacherDashboardResponse(BaseModel):
    stats: TeacherDashboardStats
    recent_submissions: List[RecentSubmissionItem]


@router.get("")
async def get_teacher_dashboard(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if current_user.role != UserRole.TEACHER:
        raise HTTPException(status_code=403, detail="Access denied. Teachers only.")

    active_courses = db.query(Course).filter(
        Course.teacher_id == current_user.id,
        Course.is_active == True
    ).count()

    total_students = db.query(func.count(func.distinct(Enrollment.student_id))).join(
        Course, Enrollment.course_id == Course.id
    ).filter(
        Course.teacher_id == current_user.id
    ).scalar() or 0

    active_assignments = db.query(Assignment).join(
        Course, Assignment.course_id == Course.id
    ).filter(
        Course.teacher_id == current_user.id,
        Assignment.is_active == True
    ).count()

    pending_grading = db.query(Submission).join(
        Assignment, Submission.assignment_id == Assignment.id
    ).join(
        Course, Assignment.course_id == Course.id
    ).filter(
        Course.teacher_id == current_user.id,
        Submission.status == SubmissionStatus.SUBMITTED
    ).count()

    recent_submissions_query = db.query(
        Submission,
        User.full_name,
        User.username,
        Assignment.title.label('assignment_title'),
        Course.course_code
    ).join(
        Assignment, Submission.assignment_id == Assignment.id
    ).join(
        Course, Assignment.course_id == Course.id
    ).join(
        User, Submission.student_id == User.id
    ).filter(
        Course.teacher_id == current_user.id,
        Submission.submitted_at.isnot(None)
    ).order_by(
        Submission.submitted_at.desc()
    ).limit(10).all()

    recent_submissions = []
    for submission, student_name, student_username, assignment_title, course_code in recent_submissions_query:
        if student_name:
            initials = ''.join([word[0].upper() for word in student_name.split()[:2]])
        else:
            initials = student_username[:2].upper()

        if submission.file_url:
            display_text = "file"
        elif submission.content:
            content_preview = submission.content.strip()
            if len(content_preview) > 30:
                space_index = content_preview.find(' ', 25)
                if 0 < space_index < 35:
                    display_text = content_preview[:space_index] + "..."
                else:
                    display_text = content_preview[:30] + "..."
            else:
                display_text = content_preview
        else:
            display_text = "submission"

        submitted_at = submission.submitted_at
        if submitted_at.tzinfo is None:
            submitted_at = submitted_at.replace(tzinfo=timezone.utc)

        recent_submissions.append(RecentSubmissionItem(
            student_name=student_name or student_username,
            student_initials=initials,
            file_name=display_text,
            submitted_at=submitted_at,
            assignment_title=assignment_title,
            course_code=course_code or "N/A"
        ))

    return TeacherDashboardResponse(
        stats=TeacherDashboardStats(
            active_courses=active_courses,
            total_students=total_students,
            active_assignments=active_assignments,
            pending_grading=pending_grading
        ),
        recent_submissions=recent_submissions
    )


@router.get("/courses-list", response_model=List[CourseResponse])
async def get_teacher_courses_list(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if current_user.role != UserRole.TEACHER:
        raise HTTPException(status_code=403, detail="Access denied. Teachers only.")

    return db.query(Course).filter(
        Course.teacher_id == current_user.id,
        Course.is_active == True
    ).order_by(Course.created_at.desc()).all()


@router.post("/quick-actions/create-course", response_model=CourseResponse)
async def quick_create_course(
    course: CourseCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if current_user.role != UserRole.TEACHER:
        raise HTTPException(status_code=403, detail="Access denied. Teachers only.")

    new_course = Course(
        **course.model_dump(),
        teacher_id=current_user.id,
        instructor=current_user.full_name or current_user.username
    )

    db.add(new_course)
    db.commit()
    db.refresh(new_course)
    return new_course


@router.post("/quick-actions/create-assignment", response_model=AssignmentResponse)
async def quick_create_assignment(
    assignment: AssignmentCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if current_user.role != UserRole.TEACHER:
        raise HTTPException(status_code=403, detail="Access denied. Teachers only.")

    course = db.query(Course).filter(
        Course.id == str(assignment.course_id),   # ← UUID → str
        Course.teacher_id == current_user.id
    ).first()

    if not course:
        raise HTTPException(status_code=404, detail="Course not found or you don't have permission")

    assignment_data = assignment.model_dump()
    assignment_data['course_id'] = str(assignment_data['course_id'])  # ← UUID → str

    new_assignment = Assignment(**assignment_data)
    db.add(new_assignment)
    db.commit()
    db.refresh(new_assignment)
    return new_assignment