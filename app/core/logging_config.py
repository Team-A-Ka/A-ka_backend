r"""
[로깅 설정 모듈]
애플리케이션 전체의 로그 포맷·레벨·핸들러를 dictConfig로 일원 관리합니다.
FastAPI(main.py)와 Celery 워커(celery_app.py) 양쪽에서 호출합니다.

[카테고리 체계]
도메인 흐름 기준으로 logger 이름을 표준화한다. 모듈 경로(__name__) 대신
'aka.<domain>[.<subflow>]' 계층을 사용해 흐름 단위로 토글·추적할 수 있다.

  aka.webhook          카카오 webhook 진입
  aka.intent           의도 분류 + 라우팅
  aka.upload           UPLOAD/FIND_SIMILAR 파이프라인 (부모)
    aka.upload.step1   Step1: 수집 + 청킹
    aka.upload.step2   Step2: LangGraph (요약->임베딩->개요)
    aka.upload.step3   Step3: 완료 + 노션 + 유사검색
  aka.save_only        SAVE_ONLY 처리
  aka.search           SEARCH RAG
  aka.similar          유사 영상 검색 (find_similar_videos)
  aka.notion           노션 OAuth + API
  aka.smtp             이메일 발송
  aka.youtube          YouTube API + Whisper STT
  aka.db               DB CRUD
  aka.auth             인증

콘솔 포맷 예:
  2026-05-11 17:13:58 [INFO] [UPLOAD.STEP2] aka.upload.step2: 청크 요약 완료

grep 활용:
  grep '\[UPLOAD\]'         -> UPLOAD 흐름 전체 (step1/2/3 모두 매칭)
  grep '\[UPLOAD\.STEP2\]'  -> step2만
"""

import logging
import logging.config


class CategoryFilter(logging.Filter):
    """logger 이름에서 도메인 카테고리를 추출해 record.category에 부착.

    'aka.upload.step2' → 'UPLOAD.STEP2'
    'aka.search'       → 'SEARCH'
    'app.foo' 또는 외부 logger → 'GEN'
    """

    def filter(self, record: logging.LogRecord) -> bool:
        parts = record.name.split(".")
        if len(parts) >= 2 and parts[0] == "aka":
            record.category = ".".join(parts[1:]).upper()
        else:
            record.category = "GEN"
        return True


LOGGING_CONFIG: dict = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "category": {
            "()": "app.core.logging_config.CategoryFilter",
        },
    },
    "formatters": {
        "default": {
            "format": "%(asctime)s [%(levelname)s] [%(category)s] %(name)s: %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "default",
            "filters": ["category"],
            "stream": "ext://sys.stdout",
        },
    },
    "root": {
        "level": "INFO",
        "handlers": ["console"],
    },
    "loggers": {
        # ===== 애플리케이션 도메인 카테고리 =====
        # 진입 / 라우팅
        "aka.webhook":      {"level": "INFO", "handlers": ["console"], "propagate": False},
        "aka.intent":       {"level": "INFO", "handlers": ["console"], "propagate": False},

        # UPLOAD/FIND_SIMILAR 파이프라인 (부모-자식 계층)
        "aka.upload":       {"level": "INFO", "handlers": ["console"], "propagate": False},
        "aka.upload.step1": {"level": "INFO", "handlers": ["console"], "propagate": False},
        "aka.upload.step2": {"level": "INFO", "handlers": ["console"], "propagate": False},
        "aka.upload.step3": {"level": "INFO", "handlers": ["console"], "propagate": False},

        # 단순 저장 / 검색 / 유사
        "aka.save_only":    {"level": "INFO", "handlers": ["console"], "propagate": False},
        "aka.search":       {"level": "INFO", "handlers": ["console"], "propagate": False},
        "aka.similar":      {"level": "INFO", "handlers": ["console"], "propagate": False},

        # 외부 시스템
        "aka.notion":       {"level": "INFO",    "handlers": ["console"], "propagate": False},
        "aka.smtp":         {"level": "INFO",    "handlers": ["console"], "propagate": False},
        "aka.youtube":      {"level": "INFO",    "handlers": ["console"], "propagate": False},

        # 인프라
        "aka.db":           {"level": "WARNING", "handlers": ["console"], "propagate": False},
        "aka.auth":         {"level": "INFO",    "handlers": ["console"], "propagate": False},

        # ===== 외부 라이브러리 노이즈 억제 =====
        "sqlalchemy.engine": {"level": "WARNING", "handlers": ["console"], "propagate": False},
        "httpx":             {"level": "WARNING", "propagate": False},
        "httpcore":          {"level": "WARNING", "propagate": False},
        "openai":            {"level": "WARNING", "propagate": False},
        "celery":            {"level": "INFO",    "propagate": False},
        "kombu":             {"level": "WARNING", "propagate": False},
    },
}

def setup_logging() -> None:
    """dictConfig를 적용해 전체 로깅 설정을 초기화합니다.

    Windows 환경에서 cp949 코덱 문제를 방지하기 위해
    sys.stdout을 UTF-8 스트림으로 교체합니다.
    """
    import io
    import sys

    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(
            sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True
        )
    logging.config.dictConfig(LOGGING_CONFIG)
