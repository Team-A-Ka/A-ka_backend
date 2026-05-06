from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.auth_dependencies import get_current_user
from app.models.user import User
from app.schemas.auth import LoginWithUsernameRequest, TokenResponse, UserResponse
from app.services.auth_service import issue_test_access_token
from database import get_db

router = APIRouter(prefix="/auth")


@router.post("/login/local", response_model=TokenResponse)
def login_with_username(
    body: LoginWithUsernameRequest,
    db: Annotated[Session, Depends(get_db)],
) -> TokenResponse:
    user, access_token = issue_test_access_token(db, body.user_name)
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user",
        )

    return TokenResponse(access_token=access_token, user=user)


@router.get("/me", response_model=UserResponse)
def get_me(current_user: Annotated[User, Depends(get_current_user)]) -> User:
    return current_user
