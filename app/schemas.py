from pydantic import BaseModel, EmailStr, Field, ConfigDict, field_validator
from typing import Optional, List, Dict, Any, Literal
from datetime import datetime
from uuid import UUID
from .models import (UserRole, SubmissionStatus, AnnouncementType, Department, 
                     Semester, TestType, TestStatus, QuestionType, TestAttemptStatus, NotificationType)
import json


class UserBase(BaseModel):
    email: EmailStr
    username: str
    full_name: Optional[str] = None
    password: str
    role: UserRole
    matric_number: Optional[str] = None
    department: Optional[Department] = None



class UserUpdateProfile(BaseModel):
    full_name: Optional[str] = None
    email: Optional[EmailStr] = None


class AdminUpdateProfile(BaseModel):
    full_name: Optional[str] = None
    email: Optional[EmailStr] = None
    username: Optional[str] = None
    matric_number: Optional[str] = None
    department: Optional[Department] = None
    
class AdminUpdateUsers(BaseModel):
    full_name: Optional[str] = None
    email: Optional[EmailStr] = None
    username: Optional[str] = None
    matric_number: Optional[str] = None
    department: Optional[Department] = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

class UserResponse(BaseModel):
    id: UUID
    email: EmailStr
    username: str
    full_name: Optional[str] = None
    role: UserRole
    matric_number: Optional[str] = None
    department: Optional[Department] = None
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)

class UserLogin(BaseModel):
    username: str
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str
    # Role is returned so the frontend can redirect after login without
    # having to read the (now HttpOnly) cookie.
    role: Optional[str] = None

class TokenData(BaseModel):
    user_id: Optional[str] = None

# Admin Statistics Schemas
class UserStats(BaseModel):
    total: int
    teachers: int
    students: int

class CourseStats(BaseModel):
    total: int
    active: int

class AssignmentStats(BaseModel):
    total: int

class SubmissionStats(BaseModel):
    total: int
    graded: int
    pending: int

class EnrollmentStats(BaseModel):
    total: int

class SystemOverview(BaseModel):
    users: UserStats
    courses: CourseStats
    assignments: AssignmentStats
    submissions: SubmissionStats
    enrollments: EnrollmentStats

class RecentActivity(BaseModel):
    period_days: int
    new_users: int
    new_courses: int
    new_assignments: int
    new_submissions: int
    new_enrollments: int

class RecentActivityItem(BaseModel):
    id: UUID
    type: str 
    action: str
    title: str
    user_name: Optional[str] = None
    created_at: datetime

class RecentActivityResponse(BaseModel):
    period_days: int
    activities: List[RecentActivityItem]
    summary: RecentActivity

class TopCourse(BaseModel):
    course_id: UUID
    course_title: str
    teacher_id: UUID
    enrollment_count: int

class TeacherPerformance(BaseModel):
    teacher_id: UUID
    teacher_name: Optional[str]
    teacher_username: str
    courses_count: int
    assignments_count: int
    pending_grading: int

class StudentPerformance(BaseModel):
    student_id: UUID
    student_name: Optional[str]
    student_username: str
    average_score: float
    total_submissions: int

# Course Schemas
class CourseBase(BaseModel):
    title: str
    course_code: Optional[str] = None
    description: Optional[str] = None
    department: Department
    semester: Semester
    schedule: Optional[str] = None
    location: Optional[str] = None
    credits: int = 3

class CourseCreate(CourseBase):
    """
    Schema for creating a course.
    Note: instructor field is NOT included here as it's automatically set from teacher's full_name
    """
    pass

class CourseUpdate(BaseModel):
    title: Optional[str] = None
    course_code: Optional[str] = None
    description: Optional[str] = None
    department: Optional[Department] = None
    semester: Optional[Semester] = None
    schedule: Optional[str] = None
    location: Optional[str] = None
    credits: Optional[int] = None
    is_active: Optional[bool] = None

class CourseResponse(CourseBase):
    id: UUID
    instructor: Optional[str] = None
    teacher_id: UUID
    created_at: datetime
    is_active: bool
    
    model_config = ConfigDict(from_attributes=True)

class CourseDetailResponse(CourseResponse):
    teacher: UserResponse
    assignments: List["AssignmentResponse"] = []

# Enrollment Schemas
class EnrollmentCreate(BaseModel):
    course_id: UUID

class EnrollmentResponse(BaseModel):
    id: UUID
    student_id: UUID
    course_id: UUID
    enrolled_at: datetime
    course: CourseResponse
    
    model_config = ConfigDict(from_attributes=True)

# Assignment Schemas
class AssignmentBase(BaseModel):
    title: str
    description: Optional[str] = None
    max_score: float = 100.0
    due_date: Optional[datetime] = None
    grading_criteria: Optional[str] = None

class AssignmentCreate(AssignmentBase):
    course_id: UUID

class AssignmentUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    max_score: Optional[float] = None
    due_date: Optional[datetime] = None
    grading_criteria: Optional[str] = None
    is_active: Optional[bool] = None

class AssignmentResponse(AssignmentBase):
    id: UUID
    course_id: UUID
    created_at: datetime
    is_active: bool
    
    model_config = ConfigDict(from_attributes=True)

class AssignmentDetailResponse(AssignmentResponse):
    course: CourseResponse
    submissions: List["SubmissionResponse"] = []

# Submission Schemas
class SubmissionBase(BaseModel):
    content: Optional[str] = None
    file_url: Optional[str] = None

class SubmissionCreate(SubmissionBase):
    assignment_id: UUID

class SubmissionUpdate(BaseModel):
    content: Optional[str] = None
    file_url: Optional[str] = None

class SubmissionGrade(BaseModel):
    score: float
    feedback: Optional[str] = None

class SubmissionManualGrade(BaseModel):
    percentage: Optional[float] = None
    score: Optional[float] = None
    feedback: Optional[str] = None
    
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "percentage": 85.5,
            "feedback": "Great work! Well-structured answer with clear explanations."
        }
    })

class SubmissionAIGradeRequest(BaseModel):
    # Leave criteria empty to use the ones saved on the assignment.
    criteria: Optional[str] = None
    # Batch only: which ungraded submissions to include.
    #   all   = everything   text = typed answer, no file   files = has an attached file
    scope: Literal["all", "text", "files"] = "all"
    
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "criteria": "Bonus points for creative solutions and error handling"
        }
    })

class SubmissionResponse(SubmissionBase):
    id: UUID
    assignment_id: UUID
    student_id: UUID
    status: SubmissionStatus
    score: Optional[float] = None
    feedback: Optional[str] = None
    submitted_at: datetime
    graded_at: Optional[datetime] = None
    
    model_config = ConfigDict(from_attributes=True)

class SubmissionDetailResponse(SubmissionResponse):
    student: UserResponse
    assignment: AssignmentResponse

# Announcement Schemas
class AnnouncementBase(BaseModel):
    title: str
    content: str
    announcement_type: AnnouncementType = AnnouncementType.INFO

class AnnouncementCreate(AnnouncementBase):
    pass

class AnnouncementUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    announcement_type: Optional[AnnouncementType] = None
    is_active: Optional[bool] = None

class AnnouncementResponse(AnnouncementBase):
    id: UUID
    author_id: UUID
    created_at: datetime
    is_active: bool
    
    model_config = ConfigDict(from_attributes=True)

class AnnouncementDetailResponse(AnnouncementResponse):
    author: UserResponse

# Dashboard Schemas
class DashboardStats(BaseModel):
    enrolled_count: int
    pending_assignments: int
    average_score: float
    next_deadline_days: Optional[int] = None

class RecentGrade(BaseModel):
    course_code: Optional[str]
    assignment_title: str
    grade: str
    score: int

class UpcomingDeadline(BaseModel):
    assignment_id: UUID
    title: str
    course_code: Optional[str]
    due_date: datetime

class TimetableSlot(BaseModel):
    time: str
    course_code: Optional[str]
    subject: str
    location: Optional[str]

class DashboardResponse(BaseModel):
    stats: DashboardStats
    recent_grades: List[RecentGrade]
    upcoming_deadlines: List[UpcomingDeadline]
    timetable: List[TimetableSlot]
    announcements: List[AnnouncementResponse]
    
# Add these schemas to your existing schemas.py

class CourseMaterialBase(BaseModel):
    title: str
    description: Optional[str] = None
    file_type: Optional[str] = None

class CourseMaterialCreate(CourseMaterialBase):
    course_id: UUID
    file_url: str
    file_size: Optional[int] = None

class CourseMaterialResponse(CourseMaterialBase):
    id: UUID
    course_id: UUID
    file_url: str
    file_size: Optional[int] = None
    uploaded_by: UUID
    uploaded_at: datetime
    is_active: bool
    
    model_config = ConfigDict(from_attributes=True)

class CourseMaterialDetailResponse(CourseMaterialResponse):
    uploader: UserResponse
    course: CourseResponse

# Update CourseDetailResponse to include materials
class CourseDetailResponse(CourseResponse):
    teacher: UserResponse
    assignments: List["AssignmentResponse"] = []
    materials: List[CourseMaterialResponse] = []
    
    

# Question Schemas
class QuestionOptionCreate(BaseModel):
    text: str

class TestQuestionCreate(BaseModel):
    question_type: QuestionType
    question_text: str
    marks: float
    options: Optional[List[str]] = None  # For MCQ
    correct_answer: Optional[str] = None  # For MCQ and subjective
    acceptable_answers: Optional[List[str]] = None  # For subjective (multiple acceptable answers)
    
    @field_validator('options')
    @classmethod
    def validate_mcq_options(cls, v, info):
        if info.data.get('question_type') == QuestionType.MULTIPLE_CHOICE and (not v or len(v) < 2):
            raise ValueError('Multiple choice questions must have at least 2 options')
        return v
    
    @field_validator('correct_answer')
    @classmethod
    def validate_mcq_answer(cls, v, info):
        if info.data.get('question_type') == QuestionType.MULTIPLE_CHOICE and not v:
            raise ValueError('Multiple choice questions must have a correct answer')
        return v

class TestQuestionResponse(BaseModel):
    id: UUID
    test_id: UUID
    question_type: QuestionType
    question_text: str
    marks: float
    order_index: int
    options: Optional[List[str]] = None
    
    model_config = ConfigDict(from_attributes=True)
    
    @classmethod
    def from_orm_custom(cls, question):
        data = {
            "id": question.id,
            "test_id": question.test_id,
            "question_type": question.question_type,
            "question_text": question.question_text,
            "marks": question.marks,
            "order_index": question.order_index,
            "options": json.loads(question.options) if question.options else None
        }
        return cls(**data)

class TestQuestionWithAnswerResponse(TestQuestionResponse):
    correct_answer: Optional[str] = None
    acceptable_answers: Optional[List[str]] = None
    
    @classmethod
    def from_orm_custom(cls, question):
        data = {
            "id": question.id,
            "test_id": question.test_id,
            "question_type": question.question_type,
            "question_text": question.question_text,
            "marks": question.marks,
            "order_index": question.order_index,
            "options": json.loads(question.options) if question.options else None,
            "correct_answer": question.correct_answer,
            "acceptable_answers": json.loads(question.acceptable_answers) if question.acceptable_answers else None
        }
        return cls(**data)


# ========== NEW: Question schema for embedding in answers ==========
class TestQuestionInAnswer(BaseModel):
    """Question data embedded within an answer response"""
    id: UUID
    question_type: str  # Use string to handle enum serialization
    question_text: str
    marks: float
    options: Optional[List[str]] = None
    correct_answer: Optional[str] = None
    
    model_config = ConfigDict(from_attributes=True)
    
    @classmethod
    def from_orm_custom(cls, question):
        """Convert ORM question to schema with parsed options"""
        options = None
        if question.options:
            try:
                options = json.loads(question.options)
            except (json.JSONDecodeError, TypeError):
                options = None
        
        # Get question type as string
        question_type = question.question_type
        if hasattr(question_type, 'value'):
            question_type = question_type.value
        else:
            question_type = str(question_type)
        
        return cls(
            id=question.id,
            question_type=question_type,
            question_text=question.question_text,
            marks=question.marks,
            options=options,
            correct_answer=question.correct_answer
        )


# Test Schemas
class TestCreate(BaseModel):
    course_id: UUID
    title: str
    description: Optional[str] = None
    test_type: TestType
    # Whole minutes, at least 1. (0 or a fraction used to be saved as 0, which
    # gave the student no timer at all.)
    duration_minutes: int = Field(ge=1, le=600)
    total_marks: float = 100.0
    randomize_questions: bool = True
    randomize_options: bool = True
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    questions: List[TestQuestionCreate]

class TestUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    duration_minutes: Optional[int] = Field(default=None, ge=1, le=600)
    total_marks: Optional[float] = None
    randomize_questions: Optional[bool] = None
    randomize_options: Optional[bool] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    status: Optional[TestStatus] = None

class TestResponse(BaseModel):
    id: UUID
    course_id: UUID
    title: str
    description: Optional[str] = None
    test_type: TestType
    duration_minutes: int
    total_marks: float
    randomize_questions: bool
    randomize_options: bool
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    status: TestStatus
    created_by: UUID
    created_at: datetime
    question_count: int = 0
    
    model_config = ConfigDict(from_attributes=True)

class TestDetailResponse(TestResponse):
    course: "CourseResponse"
    creator: "UserResponse"
    questions: List[TestQuestionWithAnswerResponse] = []

# Test Attempt Schemas
class TestAttemptStart(BaseModel):
    test_id: UUID

class TestAnswerSubmit(BaseModel):
    question_id: UUID
    answer_text: str = ""

class TestAttemptSubmit(BaseModel):
    answers: List[TestAnswerSubmit]
    invalidated: Optional[bool] = False
    invalidation_reason: Optional[str] = None

# ========== UPDATED: Basic answer response (without nested question) ==========
class TestAnswerResponse(BaseModel):
    id: UUID
    question_id: UUID
    answer_text: Optional[str] = None
    is_correct: Optional[bool] = None
    marks_obtained: Optional[float] = None
    teacher_feedback: Optional[str] = None
    
    model_config = ConfigDict(from_attributes=True)


# ========== NEW: Answer response WITH nested question data ==========
class TestAnswerWithQuestionResponse(BaseModel):
    """Answer response that includes the full question data"""
    id: UUID
    question_id: UUID
    answer_text: Optional[str] = None
    is_correct: Optional[bool] = None
    marks_obtained: Optional[float] = None
    teacher_feedback: Optional[str] = None
    question: TestQuestionInAnswer  # Nested question data
    
    model_config = ConfigDict(from_attributes=True)
    
    @classmethod
    def from_orm_custom(cls, answer):
        """Convert ORM answer with question to response schema"""
        question_data = TestQuestionInAnswer.from_orm_custom(answer.question)
        
        return cls(
            id=answer.id,
            question_id=answer.question_id,
            answer_text=answer.answer_text,
            is_correct=answer.is_correct,
            marks_obtained=answer.marks_obtained,
            teacher_feedback=answer.teacher_feedback,
            question=question_data
        )


class TestAttemptResponse(BaseModel):
    id: UUID
    test_id: UUID
    student_id: UUID
    status: TestAttemptStatus
    score: Optional[float]
    total_marks: float
    started_at: datetime
    submitted_at: Optional[datetime]
    graded_at: Optional[datetime]
    time_taken_minutes: Optional[int]
    invalidation_reason: Optional[str] = None
    
    class Config:
        from_attributes = True


# ========== UPDATED: Detail response uses answers WITH question data ==========
class TestAttemptDetailResponse(BaseModel):
    """Detailed attempt response with answers including question data"""
    id: UUID
    test_id: UUID
    student_id: UUID
    status: str  # Use string to handle enum serialization
    score: Optional[float] = None
    total_marks: float
    started_at: datetime
    submitted_at: Optional[datetime] = None
    graded_at: Optional[datetime] = None
    time_taken_minutes: Optional[int] = None
    answers: List[TestAnswerWithQuestionResponse] = [] 
    invalidation_reason: Optional[str] = None 
    
    model_config = ConfigDict(from_attributes=True)
    
    @classmethod
    def from_orm_custom(cls, attempt):
        """Convert ORM attempt to response with all nested data"""
        # Convert status to string
        status_str = attempt.status
        if hasattr(status_str, 'value'):
            status_str = status_str.value
        else:
            status_str = str(status_str)
        
        # Convert answers with question data
        answers_with_questions = [
            TestAnswerWithQuestionResponse.from_orm_custom(answer)
            for answer in attempt.answers
        ]
        
        return cls(
            id=attempt.id,
            test_id=attempt.test_id,
            student_id=attempt.student_id,
            status=status_str,
            score=attempt.score,
            total_marks=attempt.total_marks,
            started_at=attempt.started_at,
            submitted_at=attempt.submitted_at,
            graded_at=attempt.graded_at,
            time_taken_minutes=attempt.time_taken_minutes,
            answers=answers_with_questions
        )


class TestAttemptWithQuestionsResponse(TestAttemptResponse):
    questions: List[TestQuestionResponse] = []
    time_remaining_minutes: Optional[int] = None
    # Exact seconds left, computed from the SERVER clock (the browser timer
    # only counts down from this number).
    time_remaining_seconds: Optional[int] = None
    # Answers saved so far (question_id -> text). Lets a resumed attempt
    # restore what the student had typed.
    saved_answers: Dict[str, str] = {}


class TestAnswersAutosave(BaseModel):
    """Periodic save of in-progress answers (question_id -> text)."""
    answers: Dict[str, str]

# Grading Schemas
class TheoryAnswerGrade(BaseModel):
    answer_id: UUID
    marks_obtained: float
    feedback: Optional[str] = None

class TestAttemptGrade(BaseModel):
    grades: List[TheoryAnswerGrade]

# Statistics Schemas
class TestStatistics(BaseModel):
    test_id: UUID
    test_title: str
    total_enrolled: int
    total_attempted: int
    total_not_attempted: int
    total_completed: int
    total_in_progress: int
    average_score: Optional[float] = None
    highest_score: Optional[float] = None
    lowest_score: Optional[float] = None

class StudentTestAttemptInfo(BaseModel):
    student_id: UUID
    student_name: Optional[str]
    student_username: str
    matric_number: Optional[str]
    department: Optional[str]
    has_attempted: bool
    attempt_id: Optional[UUID] = None
    attempt_status: Optional[TestAttemptStatus] = None
    score: Optional[float] = None
    submitted_at: Optional[datetime] = None
    
    model_config = ConfigDict(from_attributes=True)
    
class NotificationResponse(BaseModel):
    id:            str
    type:          NotificationType
    title:         str
    message:       str
    assignment_id: Optional[str] = None
    test_id:       Optional[str] = None
    course_id:     Optional[str] = None
    is_read:       bool
    created_at:    datetime
 
    class Config:
        from_attributes = True
 
 
class NotificationCountResponse(BaseModel):
    total_unread: int