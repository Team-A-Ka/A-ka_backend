from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import create_access_token
from app.models.user import User

# 이후 레포지토리 폴더로 이동 예정
def get_user_by_id(db: Session, user_id: int) -> User | None:
    return db.query(User).filter(User.id == user_id).one_or_none()
def get_user_by_user_name(db: Session, user_name: str) -> User | None:
    return db.query(User).filter(User.user_name == user_name).one_or_none()


def get_or_create_test_user(db: Session, user_name: str) -> User:
    '''
    username 기반으로 유저 조회 → 없으면 생성
    '''
    user = get_user_by_user_name(db, user_name)
    if user is not None:
        return user

    user = User(user_name=user_name, is_active=True)
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        user = get_user_by_user_name(db, user_name)
        if user is None:
            raise
        return user

    db.refresh(user)
    return user


def issue_test_access_token(db: Session, user_name: str) -> tuple[User, str]:
    '''유저 가져오고 → access token 발급'''
    user = get_or_create_test_user(db, user_name)
    token = create_access_token(subject=str(user.id))
    return user, token
