import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

# 환경 변수 로드
load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

# DB 엔진 생성
engine = create_engine(DATABASE_URL, echo=True)

# 세션 생성기 정의
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# SQLAlchemy 2.0 스타일의 Base 클래스 선언
class Base(DeclarativeBase):
    pass


# DB 세션 의존성 주입 함수
# commit, rollback 로직을 여기에 추가할수도 있어요.
# with db.begin() 대신에
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
