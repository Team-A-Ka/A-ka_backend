# A-Ka Backend

카카오톡 챗봇을 통해 유튜브 영상을 받아 **요약·검색·저장**하고, 결과를 **Notion**에 동기화하는 지식 관리 백엔드입니다.

## 주요 기능

- **카카오톡 연동** — 웹훅으로 메시지를 수신하고, 5초 이내 응답을 보장하기 위해 Celery 백그라운드 작업으로 처리
- **AI 의도 분석** — LangGraph / LLM으로 사용자 메시지를 `UPLOAD`, `SEARCH`, `FIND_SIMILAR`, `SAVE_ONLY` 등으로 분류
- **유튜브 지식 파이프라인** — 자막 수집 → 시맨틱 청킹 → 청크별 요약 → 벡터 임베딩 → PostgreSQL(pgvector) 저장
- **Notion OAuth** — 사용자별 Notion 워크스페이스 연동 및 요약 페이지 자동 생성
- **유사 영상 검색** — 임베딩 기반으로 저장된 지식 DB에서 관련 영상 탐색
- **이메일 알림** — 처리 오류·검색 결과를 SMTP로 발송

## 기술 스택

| 영역 | 기술 |
|------|------|
| API | FastAPI, Uvicorn |
| DB | PostgreSQL 16 + pgvector, SQLAlchemy 2.x, Alembic |
| 큐 | Celery, Redis |
| AI | LangGraph, LangChain (OpenAI / Gemini / Anthropic), OpenAI Whisper |
| 인증 | JWT, 카카오 사용자 식별 |
| 패키지 관리 | [uv](https://github.com/astral-sh/uv) |
| 컨테이너 | Docker, Docker Compose |

## 프로젝트 구조

```
A-ka_backend/
├── main.py                 # FastAPI 앱 진입점
├── database.py             # 동기/비동기 DB 세션
├── app/
│   ├── routers/
│   │   ├── api.py          # 라우터 통합
│   │   └── endpoints/      # auth, webhook, notion, youtube, kakao_notion, debug
│   ├── services/           # 비즈니스 로직 (파이프라인, Notion, 검색, AI 등)
│   ├── repositories/       # 데이터 접근 (knowledge 등)
│   ├── models/             # SQLAlchemy 엔티티
│   ├── schemas/            # Pydantic DTO
│   ├── tasks/              # Celery 태스크 (knowledge, router)
│   └── core/               # config, security, celery, llm, logging
├── alembic/                # DB 마이그레이션
├── erd.dbml                # ERD 정의
├── docker-compose.yml      # 로컬 개발용
├── docker-compose.prod.yml # 운영 배포용
└── Dockerfile
```

## 사전 요구 사항

- Python 3.12+
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- Docker & Docker Compose (로컬 DB/Redis 사용 시)
- PostgreSQL에 `vector` 확장 (pgvector 이미지 사용)

## 빠른 시작

### 1. 저장소 클론 및 의존성 설치

```bash
git clone <repository-url>
cd A-ka_backend
uv sync
```

### 2. 환경 변수 설정

```bash
cp .env.example .env
```

`.env`에서 최소한 아래 항목을 설정합니다.

| 변수 | 설명 |
|------|------|
| `JWT_SECRET_KEY` | JWT 서명 키 (필수) |
| `DATABASE_URL` | PostgreSQL 연결 URL |
| `OPENAI_API_KEY` | LLM·임베딩 (기본 프로바이더) |
| `YOUTUBE_API_KEY` | 유튜브 메타데이터 조회 |
| `NOTION_OAUTH_CLIENT_ID` / `SECRET` | Notion OAuth |
| `REDIS_URL` | Celery 브로커 |

전체 목록은 [`app/core/config.py`](app/core/config.py)와 [`.env.example`](.env.example)를 참고하세요.

### 3. Docker로 인프라 기동

```bash
docker compose up -d db redis
```

로컬 개발 시 DB는 호스트 `5433` 포트로 노출됩니다 (`docker-compose.yml`).

### 4. DB 마이그레이션

```bash
# pgvector 확장 (최초 1회)
docker compose exec db psql -U postgres -d aka_db -c "CREATE EXTENSION IF NOT EXISTS vector;"

uv run alembic upgrade head
```

### 5. 서버 실행

**API 서버**

```bash
uv run uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

**Celery 워커** (별도 터미널)

```bash
uv run celery -A app.core.celery_app worker --loglevel=info
```

또는 전체 스택을 한 번에:

```bash
docker compose up
```

API 문서: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

## API 개요

모든 엔드포인트는 `/api/v1` 접두사를 사용합니다.

| 경로 | 설명 |
|------|------|
| `POST /auth/login/local` | 로컬 테스트용 로그인 (JWT 발급) |
| `GET /auth/me` | 현재 사용자 조회 |
| `POST /chat/webhook` | 카카오톡 스킬 서버 웹훅 |
| `GET /notion/oauth/start` | Notion OAuth 시작 |
| `GET /notion/oauth/callback` | Notion OAuth 콜백 |
| `GET /notion/me` | Notion 연동 상태 |
| `POST /youtube/summarize` | 유튜브 요약 파이프라인 (직접 호출) |
| `GET /kakao/notion/oauth/bridge` | 카카오 → Notion OAuth 브릿지 |
| `GET /debug/graph/{graph_name}` | LangGraph 시각화 (개발용) |

## 처리 흐름

```
카카오 메시지
    → 웹훅 즉시 ACK
    → Celery: AI 의도 분석 (router_tasks)
        ├─ UPLOAD    → 자막 수집 → 청킹 → 요약 → 임베딩 → DB + Notion
        ├─ SEARCH    → 벡터 검색 → 답변 생성 → 이메일
        ├─ FIND_SIMILAR → 유사 영상 탐색
        └─ SAVE_ONLY → 링크만 Notion 저장 (쇼츠 등)
```

## 테스트

```bash
uv run pytest
```

주요 테스트 파일: `test_ai_router.py`, `test_e2e_pipeline.py`, `test_notion_service.py` 등

## 배포

`main` 브랜치 push 시 GitHub Actions가 EC2에 SSH 접속해 [`docker-compose.prod.yml`](docker-compose.prod.yml)로 배포합니다.

```bash
# 운영 수동 배포 예시
docker compose -f docker-compose.prod.yml up -d --build web worker db redis
```

운영 환경 변수는 `.env.prod`를 사용합니다.

## 커밋 메시지 규칙

| 타입 | 설명 |
|------|------|
| `feat` | 새로운 기능 |
| `fix` | 버그 수정 |
| `build` | 빌드·의존성 변경 |
| `chore` | 기타 자잘한 수정 |
| `docs` | 문서 수정 |
| `refactor` | 코드 리팩토링 |
| `test` | 테스트 코드 |
| `perf` | 성능 개선 |

