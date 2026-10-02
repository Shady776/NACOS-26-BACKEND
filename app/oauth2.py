import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from .database import get_db
from .models import RefreshToken, User, UserRole
from .schemas import TokenData
from app.config import CONFIG

SECRET_KEY = CONFIG.SECRET_KEY
ALGORITHM = CONFIG.ALGORITHM
ACCESS_TOKEN_EXPIRE_MINUTES = CONFIG.ACCESS_TOKEN_EXPIRE_MINUTES
REFRESH_TOKEN_EXPIRE_DAYS = CONFIG.REFRESH_TOKEN_EXPIRE_DAYS

ACCESS_COOKIE = "access_token"
REFRESH_COOKIE = "refresh_token"

# auto_error=False so a missing Authorization header is not an instant 401:
# the token may be in the cookie instead.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login", auto_error=False)


# ── access token (short-lived JWT) ───────────────────────────────────────────

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def verify_access_token(token: str, credentials_exception) -> TokenData:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
        return TokenData(user_id=user_id)
    except JWTError:
        raise credentials_exception


# ── refresh token (long-lived, random, stored hashed) ───────────────────────

def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def issue_refresh_token(db: Session, user_id: str) -> str:
    """Create a refresh token row and return the raw token (sent as a cookie)."""
    raw = secrets.token_urlsafe(48)
    db.add(RefreshToken(
        user_id=user_id,
        token_hash=_hash_token(raw),
        expires_at=datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
    ))
    db.commit()
    return raw


def find_valid_refresh_token(db: Session, raw: Optional[str]) -> Optional[RefreshToken]:
    if not raw:
        return None
    rec = db.query(RefreshToken).filter(RefreshToken.token_hash == _hash_token(raw)).first()
    if not rec or rec.revoked:
        return None
    expires = rec.expires_at
    if expires.tzinfo is None:  # SQLite returns naive datetimes
        expires = expires.replace(tzinfo=timezone.utc)
    if expires <= datetime.now(timezone.utc):
        return None
    return rec


def revoke_refresh_token(db: Session, raw: Optional[str]) -> None:
    if not raw:
        return
    rec = db.query(RefreshToken).filter(RefreshToken.token_hash == _hash_token(raw)).first()
    if rec and not rec.revoked:
        rec.revoked = True
        db.commit()


def revoke_all_user_tokens(db: Session, user_id: str) -> None:
    """Log a user out everywhere (used on password change / reset).
    Does not commit: the caller commits together with its own change."""
    db.query(RefreshToken).filter(
        RefreshToken.user_id == user_id,
        RefreshToken.revoked == False,  # noqa: E712
    ).update({"revoked": True}, synchronize_session=False)


def prune_expired_tokens(db: Session) -> None:
    """Housekeeping: drop refresh tokens that expired more than a day ago."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=1)
    db.query(RefreshToken).filter(RefreshToken.expires_at < cutoff).delete(synchronize_session=False)
    db.commit()


# ── cookies ──────────────────────────────────────────────────────────────────

def _cookie_secure() -> bool:
    return CONFIG.COOKIE_SECURE or CONFIG.ENVIRONMENT.lower() == "production"


def _refresh_cookie_path() -> str:
    return f"{CONFIG.API_PATH_PREFIX.rstrip('/')}/auth"


def set_auth_cookies(response: Response, access_token: str, refresh_token: Optional[str] = None) -> None:
    secure = _cookie_secure()
    samesite = CONFIG.COOKIE_SAMESITE.lower()
    response.set_cookie(
        ACCESS_COOKIE, access_token,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        httponly=True, secure=secure, samesite=samesite, path="/",
    )
    if refresh_token:
        response.set_cookie(
            REFRESH_COOKIE, refresh_token,
            max_age=REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600,
            httponly=True, secure=secure, samesite=samesite, path=_refresh_cookie_path(),
        )


def clear_auth_cookies(response: Response) -> None:
    secure = _cookie_secure()
    samesite = CONFIG.COOKIE_SAMESITE.lower()
    response.delete_cookie(ACCESS_COOKIE, path="/", httponly=True, secure=secure, samesite=samesite)
    response.delete_cookie(REFRESH_COOKIE, path=_refresh_cookie_path(), httponly=True, secure=secure, samesite=samesite)


# ── current user ─────────────────────────────────────────────────────────────

def get_current_user(
    request: Request,
    bearer_token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # An explicit Authorization header wins (Swagger, load tests, scripts);
    # browsers use the HttpOnly cookie.
    token = bearer_token or request.cookies.get(ACCESS_COOKIE)
    if not token:
        raise credentials_exception

    token_data = verify_access_token(token, credentials_exception)
    user = db.query(User).filter(User.id == token_data.user_id).first()

    if user is None:
        raise credentials_exception

    return user


def get_current_teacher(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != UserRole.TEACHER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only teachers can perform this action"
        )
    return current_user


def get_current_student(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != UserRole.STUDENT:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only students can perform this action"
        )
    return current_user


def get_current_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can perform this action"
        )
    return current_user
