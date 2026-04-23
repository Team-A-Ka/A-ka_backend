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
    
    # Database
    # Docker가 아닌 로컬 네이티브 환경(Windows)에 구동 중인 DB를 바라보도록 설정되어 있습니다.
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "aka_db"
    DATABASE_URL: str = ""

    # Redis / Celery
    # 백그라운드 큐 통신을 위한 로컬 Redis 브로커 주소입니다.
    # Windows 환경에서 localhost가 IPv6(::1)로 우선 매핑되어 Connection Refused(10061) 에러가 발생할 수 있으므로 127.0.0.1을 명시합니다.
    REDIS_URL: str = "redis://127.0.0.1:6379/0"

    # External APIs
    # LangGraph에서 활용할 OpenAI 통합과 외부 요약 적재용 Notion API 키입니다.
    OPENAI_API_KEY: str = ""
    YOUTUBE_API_KEY: str = ""
    NOTION_API_KEY: str = ""

    class Config:
        env_file = ".env"
        case_sensitive = True

# 싱글톤처럼 애플리케이션 어디서든 import settings 하여 접근 가능하게 인스턴스화합니다.
settings = Settings()
