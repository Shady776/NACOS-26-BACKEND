from app.schemas import UserBase
import random
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import User, UserRole
from ..schemas import UserBase, UserResponse, UserLogin, Token
from ..oauth2 import (
    create_access_token, issue_refresh_token, find_valid_refresh_token,
    revoke_refresh_token, set_auth_cookies, clear_auth_cookies,
    prune_expired_tokens, REFRESH_COOKIE,
)
from ..utils.password_hash import hash_password, verify_password
from ..utils.rate_limit import limiter, login_attempt_allowed
from fastapi.security import OAuth2PasswordRequestForm

router = APIRouter(prefix="/auth", tags=["Authentication"])


def authenticate_user(db: Session, username: str, password: str):
    """Authenticate a user by username and password"""
    # Convert username to lowercase for case-insensitive lookup
    user = db.query(User).filter(User.username == username).first()

    if not user:
        return False
    
    if not verify_password(password, user.hashed_password):
        return False
    
    return user


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("60/minute")
def register(request: Request, user_data: UserBase, db: Session = Depends(get_db)):
    # Convert username to lowercase and strip whitespace
    username_lower = user_data.username.lower().strip()
    
    # Validate username is not empty after stripping
    if not username_lower:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username cannot be empty"
        )
    
    # Check if user exists (check with lowercase username)
    existing_user = db.query(User).filter(
        (User.email == user_data.email) | (User.username == username_lower)
    ).first()
    
    if existing_user:
        if existing_user.username == username_lower:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username already taken"
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered"
            )
    
    # Create new user with lowercase username
    hashed_pwd = hash_password(user_data.password)
    new_user = User(
        email=user_data.email,
        username=username_lower,  # Store username in lowercase
        full_name=user_data.full_name,
        matric_number=user_data.matric_number,
        department=user_data.department,
        # SECURITY: self-registration must never trust a client-supplied role.
        # Anyone could otherwise POST {"role": "admin"} and create an admin
        # account directly. Teacher/admin accounts are created only through
        # the admin-only endpoints in routes/admin.py.
        role=UserRole.STUDENT,
        hashed_password=hashed_pwd
    )
    
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    return new_user


@router.post("/login", response_model=Token)
# Generous per-IP limit: a whole campus can share one IP. The stricter limit
# is per username + IP (see login_attempt_allowed below).
@limiter.limit("600/minute")
def login(
    request: Request,
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    client_ip = request.client.host if request.client else "unknown"
    if not login_attempt_allowed(client_ip, form_data.username):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts for this account. Wait a minute and try again.",
            headers={"Retry-After": "60"},
        )

    user = authenticate_user(db, form_data.username, form_data.password)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(
        data={
            "sub": str(user.id),
            "role": user.role.value
        }
    )
    refresh_token = issue_refresh_token(db, str(user.id))

    # Browsers get both tokens as HttpOnly cookies (JavaScript cannot read them).
    set_auth_cookies(response, access_token, refresh_token)

    # Occasionally clean up old refresh tokens (cheap, avoids a cron job).
    if random.random() < 0.02:
        prune_expired_tokens(db)

    # access_token is still returned in the body so Swagger / scripts / load
    # tests that use "Authorization: Bearer" keep working. The frontend ignores it.
    return {"access_token": access_token, "token_type": "bearer", "role": user.role.value}


@router.post("/refresh")
@limiter.limit("600/minute")
def refresh(request: Request, response: Response, db: Session = Depends(get_db)):
    """Issue a new short-lived access token from the refresh cookie."""
    record = find_valid_refresh_token(db, request.cookies.get(REFRESH_COOKIE))
    user = db.query(User).filter(User.id == record.user_id).first() if record else None

    if not record or not user:
        clear_auth_cookies(response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired. Please log in again.",
        )

    access_token = create_access_token(
        data={"sub": str(user.id), "role": user.role.value}
    )
    set_auth_cookies(response, access_token)  # refresh token is not rotated
    return {"detail": "refreshed", "role": user.role.value}


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    """Revoke the refresh token on the server and clear both cookies."""
    revoke_refresh_token(db, request.cookies.get(REFRESH_COOKIE))
    clear_auth_cookies(response)
    return {"detail": "Logged out"}


@router.get("/check-username/{username}")
def check_username_availability(username: str, db: Session = Depends(get_db)):
    """Check if a username is available"""
    # Convert to lowercase and strip whitespace
    username_lower = username.lower().strip()
    
    # Validate username is not empty
    if not username_lower:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username cannot be empty"
        )
    
    # Check if username exists
    existing_user = db.query(User).filter(User.username == username_lower).first()
    
    return {
        "username": username_lower,
        "available": existing_user is None
    }