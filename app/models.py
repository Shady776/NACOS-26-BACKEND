from sqlalchemy import Column, String, DateTime, ForeignKey, Text, Float, Enum, Boolean, Integer, UniqueConstraint
from sqlalchemy.types import TypeDecorator
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime, timezone
from uuid6 import uuid7
import enum

Base = declarative_base()

class UTCDateTime(TypeDecorator):
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class NaiveUTCDateTime(UTCDateTime):
    """Same, for an existing column WITHOUT a time zone (stored as naive UTC), so no table change is needed."""
    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        value = super().process_bind_param(value, dialect)
        return value.replace(tzinfo=None) if value is not None else None


# ── helpers ──────────────────────────────────────────────────────────────────

def generate_uuid7() -> str:
    return str(uuid7())


# ── enums ────────────────────────────────────────────────────────────────────

class UserRole(str, enum.Enum):
    ADMIN   = "admin"
    TEACHER = "teacher"
    STUDENT = "student"

class SubmissionStatus(str, enum.Enum):
    PENDING   = "PENDING"
    SUBMITTED = "SUBMITTED"
    GRADED    = "GRADED"
    LATE      = "LATE"

class AnnouncementType(str, enum.Enum):
    INFO    = "info"
    WARNING = "warning"
    SUCCESS = "success"
    URGENT  = "urgent"

class Department(str, enum.Enum):
    CSC = "CSC"
    SEN = "SEN"
    IFT = "IFT"
    CYB = "CYB"

class Semester(str, enum.Enum):
    FIRST  = "1st"
    SECOND = "2nd"

class TestType(str, enum.Enum):
    MULTIPLE_CHOICE = "multiple_choice"
    SUBJECTIVE      = "subjective"
    THEORY          = "theory"
    MIXED           = "mixed"

class TestStatus(str, enum.Enum):
    DRAFT    = "draft"
    ACTIVE   = "active"
    EXPIRED  = "expired"
    INACTIVE = "inactive"

class QuestionType(str, enum.Enum):
    MULTIPLE_CHOICE = "multiple_choice"
    FILL_IN_BLANK   = "fill_in_blank"
    THEORY          = "theory"

class TestAttemptStatus(str, enum.Enum):
    IN_PROGRESS  = "in_progress"
    SUBMITTED    = "submitted"
    GRADED       = "graded"
    EXPIRED      = "expired"
    INVALIDATED  = "invalidated"

class NotificationType(str, enum.Enum):
    TEST_ACTIVATED     = "test_activated"
    ASSIGNMENT_CREATED = "assignment_created"
    ASSIGNMENT_UPDATED = "assignment_updated"
    ASSIGNMENT_GRADED  = "assignment_graded"
    WARNING            = "warning"


# ── models ───────────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id              = Column(String(36), primary_key=True, default=generate_uuid7, index=True)
    email           = Column(String, unique=True, index=True, nullable=False)
    username        = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    full_name       = Column(String, nullable=True)
    role            = Column(Enum(UserRole), nullable=False)
    matric_number   = Column(String, unique=True, index=True, nullable=True)
    department      = Column(Enum(Department), nullable=True)
    created_at      = Column(UTCDateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    taught_courses = relationship("Course", back_populates="teacher", foreign_keys="Course.teacher_id")
    enrollments    = relationship("Enrollment", back_populates="student")
    submissions    = relationship("Submission", back_populates="student")
    announcements  = relationship("Announcement", back_populates="author")
    notifications  = relationship("Notification", back_populates="user", cascade="all, delete-orphan")
    refresh_tokens = relationship("RefreshToken", back_populates="user", cascade="all, delete-orphan")


class Course(Base):
    __tablename__ = "courses"

    id          = Column(String(36), primary_key=True, default=generate_uuid7, index=True)
    title       = Column(String, nullable=False)
    course_code = Column(String, index=True, nullable=True)
    description = Column(Text, nullable=True)
    department  = Column(Enum(Department), nullable=False)
    semester    = Column(Enum(Semester), nullable=False)
    instructor  = Column(String, nullable=True)
    schedule    = Column(String, nullable=True)
    location    = Column(String, nullable=True)
    credits     = Column(Integer, default=3, nullable=False)
    teacher_id  = Column(String(36), ForeignKey("users.id"), nullable=False)
    created_at  = Column(UTCDateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    is_active   = Column(Boolean, default=True, nullable=False)

    materials     = relationship("CourseMaterial", back_populates="course", cascade="all, delete-orphan")
    teacher       = relationship("User", back_populates="taught_courses", foreign_keys=[teacher_id])
    assignments   = relationship("Assignment", back_populates="course", cascade="all, delete-orphan")
    enrollments   = relationship("Enrollment", back_populates="course", cascade="all, delete-orphan")
    # FIX: was back_populates="assignment" — must match Notification.course relationship name
    notifications = relationship("Notification", back_populates="course", cascade="all, delete-orphan")


class Enrollment(Base):
    __tablename__ = "enrollments"

    id          = Column(String(36), primary_key=True, default=generate_uuid7, index=True)
    student_id  = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    course_id   = Column(String(36), ForeignKey("courses.id"), nullable=False, index=True)
    enrolled_at = Column(UTCDateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    student = relationship("User", back_populates="enrollments")
    course  = relationship("Course", back_populates="enrollments")


class Assignment(Base):
    __tablename__ = "assignments"

    id          = Column(String(36), primary_key=True, default=generate_uuid7, index=True)
    course_id   = Column(String(36), ForeignKey("courses.id"), nullable=False)
    title       = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    max_score   = Column(Float, default=100.0, nullable=False)
    due_date    = Column(UTCDateTime, nullable=True)
    created_at  = Column(UTCDateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    is_active   = Column(Boolean, default=True, nullable=False)

    course        = relationship("Course", back_populates="assignments")
    submissions   = relationship("Submission", back_populates="assignment", cascade="all, delete-orphan")
    notifications = relationship("Notification", back_populates="assignment", cascade="all, delete-orphan")


class Submission(Base):
    __tablename__ = "submissions"

    id            = Column(String(36), primary_key=True, default=generate_uuid7, index=True)
    assignment_id = Column(String(36), ForeignKey("assignments.id"), nullable=False)
    student_id    = Column(String(36), ForeignKey("users.id"), nullable=False)
    content       = Column(Text, nullable=True)
    file_url      = Column(String, nullable=True)
    status        = Column(Enum(SubmissionStatus), default=SubmissionStatus.SUBMITTED, nullable=False)
    score         = Column(Float, nullable=True)
    feedback      = Column(Text, nullable=True)
    submitted_at  = Column(UTCDateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    graded_at     = Column(UTCDateTime, nullable=True)

    assignment = relationship("Assignment", back_populates="submissions")
    student    = relationship("User", back_populates="submissions")


class Announcement(Base):
    __tablename__ = "announcements"

    id                = Column(String(36), primary_key=True, default=generate_uuid7, index=True)
    title             = Column(String, nullable=False)
    content           = Column(Text, nullable=False)
    announcement_type = Column(Enum(AnnouncementType), default=AnnouncementType.INFO, nullable=False)
    author_id         = Column(String(36), ForeignKey("users.id"), nullable=False)
    created_at        = Column(UTCDateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    is_active         = Column(Boolean, default=True, nullable=False)

    author = relationship("User", back_populates="announcements")


class CourseMaterial(Base):
    __tablename__ = "course_materials"

    id          = Column(String(36), primary_key=True, default=generate_uuid7, index=True)
    course_id   = Column(String(36), ForeignKey("courses.id"), nullable=False)
    title       = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    file_url    = Column(String, nullable=False)
    file_type   = Column(String, nullable=True)
    file_size   = Column(Integer, nullable=True)
    uploaded_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    uploaded_at = Column(UTCDateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    is_active   = Column(Boolean, default=True, nullable=False)

    course   = relationship("Course", back_populates="materials")
    uploader = relationship("User")


class Test(Base):
    __tablename__ = "tests"

    id                  = Column(String(36), primary_key=True, default=generate_uuid7, index=True)
    course_id           = Column(String(36), ForeignKey("courses.id"), nullable=False)
    title               = Column(String, nullable=False)
    description         = Column(Text, nullable=True)
    test_type           = Column(Enum(TestType), nullable=False)
    duration_minutes    = Column(Integer, nullable=False)
    total_marks         = Column(Float, default=100.0, nullable=False)
    randomize_questions = Column(Boolean, default=True, nullable=False)
    randomize_options   = Column(Boolean, default=True, nullable=False)
    start_time          = Column(UTCDateTime, nullable=True)
    end_time            = Column(UTCDateTime, nullable=True)
    status              = Column(Enum(TestStatus), default=TestStatus.DRAFT, nullable=False)
    created_by          = Column(String(36), ForeignKey("users.id"), nullable=False)
    created_at          = Column(UTCDateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    course    = relationship("Course", backref="tests")
    creator   = relationship("User", foreign_keys=[created_by])
    questions = relationship("TestQuestion", back_populates="test", cascade="all, delete-orphan")
    attempts  = relationship("TestAttempt", back_populates="test", cascade="all, delete-orphan")


class TestQuestion(Base):
    __tablename__ = "test_questions"

    id                 = Column(String(36), primary_key=True, default=generate_uuid7, index=True)
    test_id            = Column(String(36), ForeignKey("tests.id"), nullable=False)
    question_type      = Column(Enum(QuestionType), nullable=False)
    question_text      = Column(Text, nullable=False)
    marks              = Column(Float, nullable=False)
    order_index        = Column(Integer, nullable=False)
    options            = Column(Text, nullable=True)
    correct_answer     = Column(String, nullable=True)
    acceptable_answers = Column(Text, nullable=True)

    test    = relationship("Test", back_populates="questions")
    answers = relationship("TestAnswer", back_populates="question", cascade="all, delete-orphan")


class TestAttempt(Base):
    __tablename__ = "test_attempts"

    id                  = Column(String(36), primary_key=True, default=generate_uuid7, index=True)
    test_id             = Column(String(36), ForeignKey("tests.id"), nullable=False, index=True)
    student_id          = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    status              = Column(Enum(TestAttemptStatus), default=TestAttemptStatus.IN_PROGRESS, nullable=False)
    score               = Column(Float, nullable=True)
    total_marks         = Column(Float, nullable=False)
    started_at          = Column(UTCDateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    submitted_at        = Column(UTCDateTime, nullable=True)
    graded_at           = Column(UTCDateTime, nullable=True)
    time_taken_minutes  = Column(Integer, nullable=True)
    invalidation_reason = Column(Text, nullable=True)
    # JSON {question_id: answer_text}, saved periodically while the student
    # types so a crash / browser change does not lose their answers.
    # Cleared when the test is submitted.
    saved_answers       = Column(Text, nullable=True)

    test    = relationship("Test", back_populates="attempts")
    student = relationship("User")
    answers = relationship("TestAnswer", back_populates="attempt", cascade="all, delete-orphan")

    # One attempt per student per test, enforced by the database itself so a
    # double-click or retry can never create a second attempt.
    __table_args__ = (
        UniqueConstraint("test_id", "student_id", name="uq_attempt_test_student"),
    )


class TestAnswer(Base):
    __tablename__ = "test_answers"

    id               = Column(String(36), primary_key=True, default=generate_uuid7, index=True)
    attempt_id       = Column(String(36), ForeignKey("test_attempts.id"), nullable=False, index=True)
    question_id      = Column(String(36), ForeignKey("test_questions.id"), nullable=False)
    answer_text      = Column(Text, nullable=True)
    is_correct       = Column(Boolean, nullable=True)
    marks_obtained   = Column(Float, nullable=True)
    teacher_feedback = Column(Text, nullable=True)

    attempt  = relationship("TestAttempt", back_populates="answers")
    question = relationship("TestQuestion", back_populates="answers")


class RefreshToken(Base):
    """Long-lived login token. Only a SHA-256 hash is stored, never the token
    itself, so a database leak cannot be used to log in. `revoked` lets logout
    (or a password change) kill the session on the server."""
    __tablename__ = "refresh_tokens"

    id         = Column(String(36), primary_key=True, default=generate_uuid7)
    user_id    = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = Column(String(64), unique=True, nullable=False, index=True)
    expires_at = Column(UTCDateTime, nullable=False, index=True)
    revoked    = Column(Boolean, default=False, nullable=False)
    created_at = Column(UTCDateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    user = relationship("User", back_populates="refresh_tokens")


class Warning(Base):
    __tablename__ = "warnings"

    id         = Column(String(36), primary_key=True, default=generate_uuid7, index=True)
    student_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    issued_by  = Column(String(36), ForeignKey("users.id"), nullable=False)
    course_id  = Column(String(36), ForeignKey("courses.id"), nullable=True)
    reason     = Column(Text, nullable=False)
    # Added: lets the sidebar badge track unread warnings
    is_read    = Column(Boolean, default=False, nullable=False)
    created_at = Column(UTCDateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    course   = relationship("Course", foreign_keys=[course_id])
    student  = relationship("User", foreign_keys=[student_id])
    issuer   = relationship("User", foreign_keys=[issued_by])


class Notification(Base):
    __tablename__ = "notifications"

    id            = Column(String(36), primary_key=True, default=generate_uuid7, index=True)
    user_id       = Column(String(36), ForeignKey("users.id"), nullable=False)
    type          = Column(Enum(NotificationType), nullable=False)
    title         = Column(String(255), nullable=False)
    message       = Column(Text, nullable=False)

    assignment_id = Column(String(36), ForeignKey("assignments.id"), nullable=True)
    test_id       = Column(String(36), nullable=True)
    course_id     = Column(String(36), ForeignKey("courses.id"), nullable=True)

    is_read    = Column(Boolean, default=False, nullable=False)
    created_at = Column(NaiveUTCDateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    user       = relationship("User",       back_populates="notifications")
    assignment = relationship("Assignment", back_populates="notifications")
    course     = relationship("Course",     back_populates="notifications")