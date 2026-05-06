from pydantic import BaseModel, ConfigDict, Field, field_validator


class LoginWithUsernameRequest(BaseModel):
    user_name: str = Field(..., max_length=50)

    @field_validator("user_name")
    @classmethod
    def normalize_user_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("user_name is required")
        return normalized


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_name: str | None
    is_active: bool


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse
