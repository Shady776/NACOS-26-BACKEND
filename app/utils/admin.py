from app.config import CONFIG
from sqlalchemy.exc import IntegrityError
from app.database import SessionLocal
from app.models import User, UserRole
from app.schemas import UserBase
from app.utils.password_hash import hash_password

def setup_admin():
    db = SessionLocal()
    try:
        new_user = User(
            username=CONFIG.ADMIN_USERNAME,
            email=CONFIG.ADMIN_EMAIL,
            full_name=CONFIG.ADMIN_FULLNAME,
            role=UserRole.ADMIN,
            hashed_password=hash_password(CONFIG.ADMIN_PASSWORD)
        )
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        print("ADMIN CREATED SUCCESSFULLY!!!")
    except IntegrityError:
        print("ADMIN ALREADY EXISTS")
    finally:
        db.close()
