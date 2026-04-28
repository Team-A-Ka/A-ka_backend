from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.models.user import User
from app.services.auth_service import get_user_by_id
from database import get_db

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    auth_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid authentication credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise auth_error

    try:
        payload = decode_access_token(credentials.credentials) # JWT 토큰 검증
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError): # JWT 토큰 검증 실패 시 예외 처리
        raise auth_error

    user = get_user_by_id(db, user_id) # 사용자 정보 조회
    if user is None or not user.is_active:
        raise auth_error

    return user
