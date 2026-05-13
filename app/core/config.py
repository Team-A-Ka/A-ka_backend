"""
[환경 설정 모듈]
애플리케이션 전체에서 사용되는 환경변수를 Pydantic Settings를 사용해 관리합니다.
.env 파일에서 값을 읽어오거나 네이티브 환경변수를 우선적으로 적용합니다.
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """
    어플리케이션 구동에 필요한 필수 설정값들을 정의하는 클래스입니다.
    타입 힌트를 기반으로 설정값의 타입 검증이 자동으로 이루어집니다.
    """

    PROJECT_NAME: str = "A-Ka Backend"

    # Auth
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 30

    # Database
    # Docker가 아닌 로컬 네이티브 환경(Windows)에 구동 중인 DB를 바라보도록 설정되어 있습니다.
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "aka_db"

    DATABASE_URL: str | None = None

    # Redis / Celery
    # 백그라운드 큐 통신을 위한 로컬 Redis 브로커 주소입니다.
    # Windows 환경에서 localhost가 IPv6(::1)로 우선 매핑되어 Connection Refused(10061) 에러가 발생할 수 있으므로 127.0.0.1을 명시합니다.
    REDIS_URL: str = "redis://127.0.0.1:6379/0"
    CELERY_BROKER_URL: str | None = None
    CELERY_RESULT_BACKEND: str | None = None

    # External APIs
    # LangGraph에서 활용할 OpenAI 통합과 외부 요약 적재용 Notion API 키입니다.
    OPENAI_API_KEY: str = ""
    YOUTUBE_API_KEY: str = ""
    NOTION_VERSION: str = "2026-03-11"
    NOTION_OAUTH_CLIENT_ID: str = ""
    NOTION_OAUTH_CLIENT_SECRET: str = ""
    NOTION_OAUTH_REDIRECT_URI: str = (
        "http://127.0.0.1:8000/api/v1/notion/oauth/callback"
    )
    NOTION_OAUTH_AUTH_URL: str = "https://api.notion.com/v1/oauth/authorize"

    # LangSmith (LangGraph 트레이싱)
    # .env에서 LANGCHAIN_API_KEY 등을 설정하면 자동으로 활성화됩니다.
    LANGCHAIN_TRACING_V2: bool = False
    LANGCHAIN_API_KEY: str = ""
    LANGCHAIN_PROJECT: str = "aka-backend"
    LANGCHAIN_ENDPOINT: str = "https://api.smith.langchain.com"

    @property
    def database_url(self) -> str:
        if self.DATABASE_URL:
            return self.DATABASE_URL

        return (
            f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def celery_broker_url(self) -> str:
        return self.CELERY_BROKER_URL or self.REDIS_URL

    @property
    def celery_result_backend(self) -> str:
        return self.CELERY_RESULT_BACKEND or self.REDIS_URL

    SQL_ECHO: bool = False

    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    ERROR_ALERT_EMAIL: str = ""

    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"


# 싱글톤처럼 애플리케이션 어디서든 import settings 하여 접근 가능하게 인스턴스화합니다.
settings = Settings()
