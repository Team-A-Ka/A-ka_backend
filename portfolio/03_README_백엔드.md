<p align="center">
  <img src="./assets/00_hero_logo.jpg" alt="A-KA Logo" width="200"/>
</p>

# A-KA (Archive KakaoTalk)

> 카카오톡으로 유튜브 영상을 보내면 AI가 자동 요약·검색 가능하게 만드는 개인 영상 아카이브 서비스
> **백엔드 시스템 설계 + 비동기 처리 + 운영 안정성** 관점에서 정리한 README입니다.

<p align="center">
  <img src="./assets/demo_hero.gif" alt="A-KA Demo" width="400"/>
  <br/>
  <em>카톡으로 URL 보내기 → 노션에 자동 요약 (15초 시연)</em>
</p>

🎬 **[전체 시연 영상 (1분 32초) →](https://youtu.be/cC5Yub8P0aQ)**

---

## ✨ 주요 기능

- 📥 **단일 카카오톡 채널** → 4가지 사용자 의도(UPLOAD / SAVE_ONLY / FIND_SIMILAR / SEARCH) 자동 분류·처리
- ⚡ **카카오톡 5초 응답 룰** 100% 준수 (즉시 ACK + Celery 백그라운드 위임)
- 🔄 **3단계 Celery chain** + 통합 `.on_error()` 핸들러로 어디서 실패해도 한 곳에서 처리
- 📧 **결과 채널 분리 정책**: 영상 요약→노션 / 검색 결과→메일 / 카톡엔 ACK만
- 💰 **SAVE_ONLY 분기**로 LLM 호출 0회 처리 (의도가 *"저장만"* 인 경우 토큰 비용 100% 절감)

### 실제 동작 화면

| 입력 (카카오톡) | 결과 1 (노션 페이지) | 결과 2 (SMTP 메일) |
|:---:|:---:|:---:|
| <img src="./assets/01_kakaotalk_input.jpg" width="220"/> | <img src="./assets/02_notion_summary.jpg" width="220"/> | <img src="./assets/04_smtp_search_result.jpg" width="220"/> |
| URL 보내기 + ACK 응답 | 청크별 타임스탬프 요약 자동 생성 | RAG 답변 + 출처 URL 포함 |

<p align="center">
  <img src="./assets/05_notion_database.jpg" alt="Notion Database" width="700"/>
  <br/>
  <em>우산 카테고리로 자동 분류된 노션 데이터베이스</em>
</p>

---

## 🏗 시스템 아키텍처

```
[카톡 사용자] → POST /chat/webhook → 즉시 ACK (5초 룰)
                          ↓ BackgroundTasks
                    Redis (Celery Broker)
                          ↓
                    Celery Worker
                          ↓
                  AI 라우터 (LLM 의도 분류)
                          ↓
        ┌─────────────────┼─────────────────┐
        ↓                 ↓                 ↓
    UPLOAD           SAVE_ONLY           SEARCH
  (Celery chain)   (메타데이터만)    (LangGraph RAG)
        ↓                 ↓                 ↓
   Intelligence      pgvector            pgvector
    LangGraph       (요약 없음)         코사인 검색
        ↓                                   ↓
   pgvector 저장                       LLM 답변 생성
        ↓                                   ↓
  Notion 페이지                         SMTP 메일
```

상세 흐름은 [docs/architecture.md](./docs/architecture.md) 참고

---

## 🛠 기술 스택

| 영역 | 기술 |
|---|---|
| **언어 / 런타임** | Python 3.12, uv |
| **API** | FastAPI · Uvicorn (ASGI) · Pydantic |
| **비동기 / 큐** | Celery · Redis |
| **DB** | PostgreSQL 16 + pgvector |
| **ORM** | SQLAlchemy 2.0 (async) · Alembic |
| **AI / LLM** | LangGraph · LangChain · OpenAI |
| **인프라** | Docker · Docker Compose |
| **개발 도구** | pytest · ruff |

### 왜 이 스택을 골랐나 (요약)

- **FastAPI**: 카카오톡 웹훅의 빠른 응답 필요, async/await 네이티브 지원, Pydantic 타입 검증 + Swagger 자동 문서화
- **Celery + Redis**: LLM 호출 30초~수 분 작업을 5초 응답 룰 안에서 처리하려면 백그라운드 큐 위임 필수. asyncio는 같은 프로세스라 격리·재시도·영속성에서 Celery가 우위
- **PostgreSQL + pgvector**: 메타데이터와 벡터를 같은 트랜잭션으로 관리해 무결성 확보. Pinecone 같은 별도 벡터 DB 대비 운영 부담 + 동기화 이슈 회피

---

## 🚀 실행 방법

```bash
# 환경 변수 설정 (.env 파일 생성)
cp .env.example .env
# OPENAI_API_KEY, POSTGRES_*, REDIS_* 등 설정

# Docker Compose로 4개 서비스 실행
docker-compose up -d
# web, worker, redis, db 컨테이너 기동

# DB 마이그레이션
docker-compose exec web alembic upgrade head

# 카카오톡 챗봇 빌더에 웹훅 URL 등록
# https://your-domain.com/chat/webhook
```

상세 가이드: [docs/setup.md](./docs/setup.md)

---

## 📁 프로젝트 구조

```
app/
├── routers/endpoints/       # FastAPI 엔드포인트 (webhook, auth 등)
├── services/                # 비즈니스 로직 (AI 라우터, LangGraph, 검색)
├── tasks/                   # Celery 태스크 정의 (chain, on_error)
├── repositories/            # DB 접근 계층
├── models/                  # SQLAlchemy ORM 모델
├── schemas/                 # Pydantic / TypedDict 스키마
└── core/                    # 설정·LLM 초기화·인증
```

---

## 💡 핵심 설계 결정 (백엔드 관점)

### 1. 카카오톡 5초 룰 대응 — 비동기 위임 패턴

웹훅에 5초 안에 응답 안 하면 카톡 챗봇이 타임아웃 처리. LLM 호출은 30초~수 분 걸리므로:

```python
@router.post("/chat/webhook")
async def kakao_webhook(request, background_tasks):
    # 사용자 식별 + 즉시 ACK 응답
    background_tasks.add_task(trigger_ai_router, ...)
    return KakaoWebhookResponse(...)  # ← 5초 안에 응답
```

`BackgroundTasks` → Celery 큐 위임으로 실제 처리는 워커가 비동기로.

### 2. 3단계 Celery Chain + `.on_error()` 통합 핸들러

```python
workflow = chain(
    collect_and_chunk_task.s(video_id, user_id, ...),
    run_intelligence_graph_task.s(),
    update_pipeline_status_task.s(),
).on_error(handle_pipeline_failure_task.s(video_id, user_id))
```

어느 Step에서든 실패하면 통합 핸들러가:
- DB status `FAILED` 마킹
- 사용자에게 안내 메일 자동 발송

### 3. pgvector 단일 트랜잭션 관리

별도 벡터 DB 대신 PostgreSQL의 `pgvector` 확장을 선택해 영상 메타데이터(`knowledge`)와 벡터(`youtube_knowledge_chunk.embedding`)를 같은 트랜잭션으로 일관 관리.

```sql
SELECT kc.content, k.title, k.original_url,
       kc.embedding <=> CAST(:query_vec AS vector) AS distance
FROM youtube_knowledge_chunk kc
JOIN knowledge k ON kc.knowledge_id = k.id
WHERE k.user_id = :user_id
  AND kc.embedding <=> CAST(:query_vec AS vector) < :threshold
ORDER BY kc.embedding <=> CAST(:query_vec AS vector)
LIMIT :top_k;
```

JOIN 한 쿼리로 *"특정 사용자의 영상에서 가장 유사한 청크 찾기"* 처리.

---

## 🔍 트러블슈팅 사례: Celery `.on_error()` 인자 자동 주입

**문제**
3단계 chain에 `.on_error(handle.s(video_id, user_id))`로 핸들러 등록했는데:
- 핸들러 호출 안 됨
- DB가 `PROCESSING`에서 멈춤
- 사용자에게는 아무 안내도 안 감 (가장 위험한 형태의 실패)

**원인 진단**
Celery 워커 로그 정독 → 핸들러는 호출되는데 *"인자 개수 불일치"* 예외로 즉시 죽음.
Celery 공식 문서 재정독 → `.on_error()` 콜백은 실패한 태스크의 **`request`, `exc`, `traceback`** 3개를 자동으로 콜백 함수에 포함시킨다는 규칙 발견.

**해결**
```python
# Before — 인자 2개만 받음
def handle_pipeline_failure_task(self, video_id, user_id):
    ...

# After — Celery 자동 주입 3개 추가
def handle_pipeline_failure_task(self, video_id, user_id, request, exc, traceback):
    task_id = getattr(request, "id", None) or str(request)
    knowledge_pipeline_service.handle_failure(video_id, task_id)
    send_user_processing_error_email(...)
```

**교훈**
프레임워크의 콜백류 함수는 자