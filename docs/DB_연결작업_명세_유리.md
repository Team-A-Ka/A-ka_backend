# DB 연결 작업 명세서 (유리님 작업용)

> 기준 ERD: `erd.dbml` (최신)
> 작성: 채훈 · 2026-04-24
> 목적: 파이프라인 각 단계에서 **어느 테이블**의 **어느 컬럼**에 **어떤 값**이 들어가야 하는지 1:1로 명확히 하기

---

## 0. 먼저 합의해야 할 3가지

| 항목 | 현재 상태 | ERD | 결정 필요 |
|------|----------|-----|----------|
| 청크 테이블명 | `youtube_knowledge_chunk` (models/knowledge.py) | `knowledge_chunk` | **ERD 기준 `knowledge_chunk`로 리네임** 제안 |
| embedding 컬럼 | 없음 | ERD에 없음 | **pgvector `Vector(1536)` 컬럼 추가 필요** (embedding 안 쓰면 SEARCH 불가능) |
| user_id 전파 | `run_core_pipeline_task(video_id)` — user_id 안 넘어옴 | — | **`run_core_pipeline_task(video_id, kakao_user_id)`로 시그니처 확장** (채훈 작업) |

---

## 1. 사전 세팅 (P0)

### 1-1. PostgreSQL pgvector 확장 설치
```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

### 1-2. Python 패키지
```bash
uv add pgvector
```

### 1-3. `knowledge_chunk` 모델 수정 (`app/models/knowledge.py`)

```python
from pgvector.sqlalchemy import Vector  # 추가

class YoutubeKnowledgeChunk(Base):
    __tablename__ = "knowledge_chunk"   # ← youtube_knowledge_chunk에서 변경
    # ... 기존 컬럼 유지 ...
    embedding: Mapped[Optional[list[float]]] = mapped_column(Vector(1536), nullable=True)  # ← 신규
```

### 1-4. Alembic 마이그레이션
```bash
uv run alembic revision --autogenerate -m "rename knowledge_chunk and add embedding"
```
생성된 파일 `upgrade()` 맨 위에 다음 줄 수동 추가:
```python
op.execute("CREATE EXTENSION IF NOT EXISTS vector")
```
그 다음:
```bash
uv run alembic upgrade head
```

### 1-5. 테스트용 시드 유저 (임시)
User·UserChannelIdentity 매핑 전략이 아직 정해지지 않았으므로, **당분간 `user.id=1`에 하드코딩 테스트 유저 1명**을 DB에 넣어두고 개발.
```sql
INSERT INTO "user" (id, user_name, is_active) VALUES (1, 'test_user', true);
INSERT INTO user_channel_identity (user_id, provider, provider_user_id)
  VALUES (1, 'kakao', 'tester_1');
```

---

## 2. 데이터 흐름 다이어그램

```
카카오 user_id ─┐
video_id ──────┤
               ▼
  ┌─────────────────────────────────────────────────────────────┐
  │ Step 1 · collect_and_chunk                                  │
  │ • User 조회/생성 (provider='kakao', provider_user_id)       │
  │ • Knowledge INSERT (status=PROCESSING)                      │
  │ • YoutubeMetadata INSERT                                    │
  │ • knowledge_chunk bulk INSERT (embedding=NULL, summary=NULL)│
  │ → 반환 dict에 knowledge_id 추가                             │
  └─────────────────────────────────────────────────────────────┘
               ▼
  ┌─────────────────────────────────────────────────────────────┐
  │ Step 2 · run_intelligence_graph_task  (LangGraph)           │
  │ • LangGraph가 summary/embedding/overview 생성               │
  │ • Category upsert → category_id 획득                        │
  │ • Knowledge UPDATE (summary, category_id)                   │
  │ • knowledge_chunk UPDATE × N (summary_detail, embedding)    │
  └─────────────────────────────────────────────────────────────┘
               ▼
  ┌─────────────────────────────────────────────────────────────┐
  │ Step 3 · update_pipeline_status                             │
  │ • Knowledge UPDATE (status=COMPLETED)                       │
  └─────────────────────────────────────────────────────────────┘

  에러 발생 시 → handle_pipeline_failure
  • Knowledge UPDATE (status=FAILED)
```

---

## 3. 테이블별 필드 주입 양식

### 3-1. `user` (Step 1 진입 시 — 없으면 생성)

| 컬럼 | 값 소스 | 비고 |
|------|--------|------|
| `id` | auto-increment | — |
| `user_name` | `NULL` 또는 `'kakao_' + provider_user_id[:8]` | 카카오는 닉네임 못 받음, 닉네임 별도 수집 전까지 nullable |
| `is_active` | `true` | default |
| `created_at` / `updated_at` | `now()` | default |

**트리거**: `UserChannelIdentity`에 `(provider='kakao', provider_user_id)` 조합이 없을 때만 INSERT

---

### 3-2. `user_channel_identity` (Step 1 진입 시 — user 신규 생성과 동시)

| 컬럼 | 값 소스 | 비고 |
|------|--------|------|
| `id` | auto-increment | — |
| `user_id` | 위에서 생성/조회된 `user.id` | FK |
| `provider` | `'kakao'` | 현재는 카카오만 |
| `provider_user_id` | 카카오 웹훅의 `userRequest.user.id` | 해시값, `router_service.process_ai_routing`의 `user_id` 인자 그대로 |
| `created_at` / `updated_at` | `now()` | default |

**유니크 제약**: `uq_provider_user` → upsert 구현 권장
```python
stmt = insert(UserChannelIdentity).values(...).on_conflict_do_nothing(
    constraint='uq_provider_user'
)
```

---

### 3-3. `knowledge` — Step 1 **INSERT**

| 컬럼 | 값 소스 | 비고 |
|------|--------|------|
| `id` | `gen_random_uuid()` | default — **반환값으로 Step 2에 전달 필수** |
| `user_id` | 3-1에서 조회/생성된 user.id | FK |
| `category_id` | `NULL` | Step 2에서 채움 |
| `source_type` | `SourceType.YOUTUBE` | 현재는 유튜브만 |
| `title` | `metadata['video_title']` | `youtube_service.get_metadata()` 결과 |
| `original_url` | `f"https://www.youtube.com/watch?v={video_id}"` | 재구성 |
| `status` | `ProcessStatus.PROCESSING` | — |
| `summary` | `NULL` | Step 2에서 채움 |
| `hit_count` | `1` | default |
| `created_at` / `updated_at` | `now()` | default |

### 3-4. `knowledge` — Step 2 **UPDATE** (WHERE id = knowledge_id)

| 컬럼 | 값 소스 | 비고 |
|------|--------|------|
| `category_id` | `category` upsert 결과 FK (3-7 참조) | — |
| `summary` | `result['full_summary']` (LangGraph 결과) | 노션 업로드용 전체 요약 |
| `title` | **UPDATE 안 함** | Step 1의 metadata title 유지 (AI 제목은 `result['title']`지만 원제목이 더 정확) |
| `updated_at` | `now()` | onupdate 자동 |

### 3-5. `knowledge` — Step 3 **UPDATE**

| 컬럼 | 값 소스 | 비고 |
|------|--------|------|
| `status` | `ProcessStatus.COMPLETED` | — |

### 3-6. `knowledge` — 에러 경로 **UPDATE**

| 컬럼 | 값 소스 | 비고 |
|------|--------|------|
| `status` | `ProcessStatus.FAILED` | — |

---

### 3-7. `category` — Step 2 **upsert** (INSERT ON CONFLICT)

| 컬럼 | 값 소스 | 비고 |
|------|--------|------|
| `id` | auto-increment | — |
| `name` | `result['category']` (LangGraph `VideoOverview.category`) | 예: "개발/IT", "경제", "자기계발" |
| `created_at` / `updated_at` | `now()` | default |

**구현 예시**:
```python
stmt = insert(Category).values(name=category_name).on_conflict_do_update(
    index_elements=['name'], set_={'updated_at': func.now()}
).returning(Category.id)
category_id = session.execute(stmt).scalar_one()
```

**⚠️ ERD 확인**: `category.name`에 UNIQUE 제약이 없음 — upsert 쓰려면 UNIQUE 추가 마이그레이션 필요. 없으면 그냥 "SELECT 후 없으면 INSERT" 패턴으로.

---

### 3-8. `youtube_metadata` — Step 1 **INSERT**

| 컬럼 | 값 소스 | 비고 |
|------|--------|------|
| `id` | `gen_random_uuid()` | default |
| `knowledge_id` | 3-3에서 생성된 knowledge.id | FK, UNIQUE (1:1) |
| `video_id` | 파이프라인 입력 `video_id` | — |
| `video_title` | `metadata['video_title']` | — |
| `channel_name` | `metadata['channel_name']` | — |
| `duration` | `metadata['duration']` | ms 단위 |
| `created_at` / `updated_at` | `now()` | default |

---

### 3-9. `knowledge_chunk` — Step 1 **bulk INSERT**

**입력 소스**: `final_chunks` 리스트 (collect_and_chunk에서 생성)

| 컬럼 | 값 소스 | 비고 |
|------|--------|------|
| `id` | `gen_random_uuid()` | default — **chunk 단위로 고유** |
| `knowledge_id` | 3-3에서 생성된 knowledge.id | FK |
| `content` | `chunk['content']` | 청크 원문 |
| `summary_detail` | `NULL` | Step 2에서 채움 |
| `start_time` | `chunk['start_time']` (ms) | — |
| `chunk_order` | `chunk['chunk_order']` (0부터) | 순서 복원용 |
| `embedding` | `NULL` | Step 2에서 채움 |
| `created_at` / `updated_at` | `now()` | default |

**구현 팁**: `session.bulk_insert_mappings()` 또는 `session.execute(insert(...), values_list)` 사용

---

### 3-10. `knowledge_chunk` — Step 2 **UPDATE × N**

**입력 소스**:
- `result['summarized_chunks']` = `[{chunk_order, content, start_time, summary}, ...]`
- `result['embeddings']` = `[[1536개 float], [1536개 float], ...]` (순서는 summarized_chunks와 동일)

| 컬럼 | 값 소스 | 매칭 키 |
|------|--------|--------|
| `summary_detail` | `summarized_chunks[i]['summary']` | `chunk_order` |
| `embedding` | `embeddings[i]` | 동일 인덱스 |
| `updated_at` | `now()` | onupdate |

**매칭 로직**: `WHERE knowledge_id = :kid AND chunk_order = :order`

**구현 팁** (bulk update):
```python
from sqlalchemy import update
for chunk, embedding in zip(summarized_chunks, embeddings):
    session.execute(
        update(YoutubeKnowledgeChunk)
        .where(
            YoutubeKnowledgeChunk.knowledge_id == knowledge_id,
            YoutubeKnowledgeChunk.chunk_order == chunk['chunk_order'],
        )
        .values(summary_detail=chunk['summary'], embedding=embedding)
    )
session.commit()
```

---

## 4. 코드 수정 위치 체크리스트

### 4-1. `app/services/knowledge_pipeline.py`

| 위치 | 현재 | 변경 후 |
|------|------|--------|
| `run_core_pipeline_task(video_id)` | 인자 1개 | `run_core_pipeline_task(video_id, kakao_user_id)` |
| `collect_and_chunk` 내 L287-292 주석 | `dummy_async_db_operation(...)` | **3-1, 3-2, 3-3, 3-8, 3-9 INSERT 구현** |
| `collect_and_chunk` 반환 dict | `{video_id, metadata, chunks}` | `{video_id, knowledge_id, chunks}` 로 변경 (metadata는 이미 DB에 저장됨) |
| `run_intelligence_graph_task` data 수신 | `video_id, chunks` 사용 | **`knowledge_id`도 사용 — 3-4, 3-7, 3-10 UPDATE 구현** |
| `run_intelligence_graph_task` L332 | `dummy_async_db_operation(...)` | 실제 UPDATE로 교체 |
| `update_pipeline_status` L364 | `dummy_async_db_operation(...)` | **3-5 UPDATE 구현**, `data['knowledge_id']` 사용 |
| `handle_pipeline_failure` 시그니처 | `(task_id, video_id)` | `(task_id, knowledge_id)` — **3-6 UPDATE 구현** |
| `workflow.on_error(...)` | `handle_pipeline_failure.s(video_id)` | `handle_pipeline_failure.s(knowledge_id)` — Step 1이 knowledge_id 생성 후 호출해야 함 |

### 4-2. `app/services/router_service.py`

| 위치 | 변경 |
|------|------|
| `process_ai_routing(self, user_id, user_message)` | 그대로 (webhook에서 `user_id`=카카오 해시 받음) |
| L97 `run_core_pipeline_task(video_id)` | `run_core_pipeline_task(video_id, user_id)` — **user_id 전달** |

### 4-3. `app/services/search_service.py`

| 위치 | 변경 |
|------|------|
| `search_chunks` L51-71 | 주석 해제 — 테이블명을 `knowledge_chunk`로 수정 |

### 4-4. `app/models/knowledge.py`

| 위치 | 변경 |
|------|------|
| `YoutubeKnowledgeChunk.__tablename__` | `"knowledge_chunk"` |
| `YoutubeKnowledgeChunk` 컬럼 | `embedding: Mapped[Optional[list[float]]] = mapped_column(Vector(1536), nullable=True)` 추가 |
| import | `from pgvector.sqlalchemy import Vector` 추가 |

---

## 5. 완료 판정 기준 (유리님 작업 끝났다고 할 수 있는 조건)

1. `uv run alembic upgrade head` 성공 (pgvector 확장 + embedding 컬럼 확인)
2. `psql`로 아래 전부 OK:
   ```sql
   \d knowledge_chunk    -- embedding vector(1536) 컬럼 존재
   \dx                    -- vector 확장 목록에 보임
   ```
3. `test_ai_router.py` 실행 후:
   ```sql
   SELECT id, user_id, category_id, status, LENGTH(summary) FROM knowledge;
   -- status='COMPLETED', summary IS NOT NULL, category_id IS NOT NULL
   SELECT chunk_order, LENGTH(summary_detail), (embedding IS NOT NULL) AS has_vec
     FROM knowledge_chunk WHERE knowledge_id = :kid ORDER BY chunk_order;
   -- 모든 row에 summary_detail 있고 has_vec=true
   ```
4. 같은 user_id로 SEARCH 호출 시 Celery 로그에 `[SEARCH 노드2: 검색] 완료 — N개 청크 발견` (N>0)

---

## 6. 채훈이 병렬로 도울 수 있는 조각

- `run_core_pipeline_task(video_id, kakao_user_id)` 시그니처 확장 + `router_service.py` 호출부 수정
- `handle_pipeline_failure` 시그니처 `knowledge_id`로 변경 + `on_error` 연결
- `collect_and_chunk` 반환 dict에 `knowledge_id` 자리 잡아두기 (내부 INSERT는 유리님 영역)
- `VideoOverview.category` Enum 제약 (카테고리 자유형 방지)

→ 어느 조각부터 먼저 할지 공유 후 작업 분담!
