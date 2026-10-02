from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func, and_
from typing import List
from datetime import datetime, timedelta, timezone, date as date_type
from ..database import get_db
from ..models import User, Course, Assignment, Submission, Enrollment, SubmissionStatus
from ..schemas import (
    DashboardResponse, 
    DashboardStats, 
    RecentGrade, 
    UpcomingDeadline,
    TimetableSlot,
    AnnouncementResponse
)
from ..oauth2 import get_current_student


def _aware(dt):
    """SQLite returns naive datetimes, PostgreSQL returns aware ones. Treat naive as UTC."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


router = APIRouter(prefix="/dashboard", tags=["Dashboard"])

@router.get("/student", response_model=DashboardResponse)
def get_student_dashboard(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_student)
):
    # Get enrolled courses count
    enrolled_count = db.query(Enrollment).filter(
        Enrollment.student_id == current_user.id
    ).count()
    
    # Get enrolled course IDs
    enrollments = db.query(Enrollment).filter(
        Enrollment.student_id == current_user.id
    ).all()
    enrolled_course_ids = [e.course_id for e in enrollments]
    
    # Get pending assignments (not submitted)
    if enrolled_course_ids:
        all_assignments = db.query(Assignment).filter(
            Assignment.course_id.in_(enrolled_course_ids),
            Assignment.is_active == True
        ).all()
        
        # Get submitted assignment IDs
        submitted_assignment_ids = db.query(Submission.assignment_id).filter(
            Submission.student_id == current_user.id
        ).all()
        submitted_ids = [s[0] for s in submitted_assignment_ids]
        
        # Count pending
        pending_assignments = len([a for a in all_assignments if a.id not in submitted_ids])
    else:
        pending_assignments = 0
        all_assignments = []
    
    # Calculate average score
    graded_submissions = db.query(Submission).filter(
        Submission.student_id == current_user.id,
        Submission.status == SubmissionStatus.GRADED,
        Submission.score.isnot(None)
    ).all()
    
    if graded_submissions:
        total_percentage = sum(
            (s.score / s.assignment.max_score * 100) 
            for s in graded_submissions
        )
        average_score = round(total_percentage / len(graded_submissions), 1)
    else:
        average_score = 0.0
    
    # Get next deadline
    today = date_type.today()
    now = datetime.now(timezone.utc)
    upcoming_assignments = [
    a for a in all_assignments 
    if a.due_date and _aware(a.due_date) > now and a.id not in submitted_ids
]
    if upcoming_assignments:
        next_assignment = min(upcoming_assignments, key=lambda a: _aware(a.due_date))
        days_until = (next_assignment.due_date.date() - today).days
        next_deadline_days = max(0, days_until)
    else:
        next_deadline_days = None
    
    # Get recent grades (last 3 graded submissions)
    recent_graded = db.query(Submission).filter(
        Submission.student_id == current_user.id,
        Submission.status == SubmissionStatus.GRADED,
        Submission.score.isnot(None)
    ).order_by(Submission.graded_at.desc()).limit(3).all()
    
    recent_grades = []
    for sub in recent_graded:
        percentage = (sub.score / sub.assignment.max_score) * 100
        if percentage >= 90:
            grade = 'A'
        elif percentage >= 80:
            grade = 'B'
        elif percentage >= 70:
            grade = 'C'
        elif percentage >= 60:
            grade = 'D'
        else:
            grade = 'F'
        
        recent_grades.append(RecentGrade(
            course_code=sub.assignment.course.course_code,
            assignment_title=sub.assignment.title,
            grade=grade,
            score=round(percentage)
        ))
    
    # Get upcoming deadlines (next 2 pending assignments)
    sorted_upcoming = sorted(upcoming_assignments, key=lambda a: _aware(a.due_date))[:2]
    upcoming_deadlines = [
        UpcomingDeadline(
            assignment_id=a.id,
            title=a.title,
            course_code=a.course.course_code,
            due_date=a.due_date
        )
        for a in sorted_upcoming
    ]
    
    # Get timetable from enrolled courses
    enrolled_courses = db.query(Course).filter(
        Course.id.in_(enrolled_course_ids),
        Course.is_active == True
    ).all()
    
    timetable = []
    for course in enrolled_courses[:3]:  # Show first 3 courses
        if course.schedule:
            timetable.append(TimetableSlot(
                time=course.schedule or "TBD",
                course_code=course.course_code,
                subject=course.title,
                location=course.location or "TBD"
            ))
    
    # Get active announcements
    from ..models import Announcement
    announcements = db.query(Announcement).filter(
        Announcement.is_active == True
    ).order_by(Announcement.created_at.desc()).limit(5).all()
    
    return DashboardResponse(
        stats=DashboardStats(
            enrolled_count=enrolled_count,
            pending_assignments=pending_assignments,
            average_score=average_score,
            next_deadline_days=next_deadline_days
        ),
        recent_grades=recent_grades,
        upcoming_deadlines=upcoming_deadlines,
        timetable=timetable,
        announcements=announcements
    )