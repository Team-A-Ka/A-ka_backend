# 🤝 데스크탑 작업 인수인계 프롬프트

> 데스크탑의 Claude Code 새 세션에 통째로 붙여넣으면 됨.
> 아래 마크다운 헤더(`# 🤝 ...`) 부터 맨 아래 마지막 줄까지 전부 복사.

---

# A-KA (Archive KakaoTalk) — 데스크탑 작업 인수인계

## 0. 작업 규칙 (중요)

- **PR 만들지 마**. main 브랜치에 머지 안 함. 본 작업은 데스크탑·노트북 공유 + 포트폴리오 작성용.
- **모든 작업은 `feat/lang-graph` 브랜치에서**. 커밋·푸시는 이 브랜치로만.
- 환경: Windows / Python 3.12 / Docker 안 씀 / Celery 로컬 + Redis 로컬 + Postgres 17 + pgvector

## 1. 프로젝트 한 줄 설명

카카오톡으로 유튜브 영상 URL을 보내면 AI가 자동으로 요약·분류·검색하여 노션에 아카이브하는 서비스. 4인 백엔드 팀 프로젝트. 내 담당: AI 라우터 + LangGraph 2개 그래프(Intelligence·SEARCH RAG) + 임베딩·pgvector + Celery 트러블슈팅.

## 2. 시작 시 무조건 먼저 읽을 문서

```
C:\A-ka_backend\portfolio\측정_및_검증_종합기록.md  ← ⭐ 단일 진실 문서 (686줄, 13섹션)
C:\A-ka_backend\portfolio\SESSION_2026-06-04.md     ← Day 1 작업 로그
C:\A-ka_backend\portfolio\KPI_측정결과.md           ← 상세 측정 결과 + JSON
C:\A-ka_backend\portfolio\intent_eval_result.md     ← 의도 분류 50케이스 결과
C:\A-ka_backend\portfolio\01_대표프로젝트_AKA.md     ← 포트폴리오 본문
```

이 5개를 먼저 읽고 다음 작업 시작.

## 3. 현재 상태 스냅샷 (2026-06-06 기준)

### 코드

- ✅ OpenAI → **Gemini 전환 완료** (chat `gemini-2.5-flash-lite` + embedding `gemini-embedding-001` @ 1536d, Matryoshka)
- ✅ 임베딩 추상화 신설 (`app/core/llm.py`의 `embed_texts/embed_query`)
- ✅ Celery 5.x **errback 회귀 버그 수정** (`handle_pipeline_failure_task` 시그니처 재배치)
- ✅ **ThreadPool 외부화** (`CHUNK_SUMMARY_MAX_WORKERS` env, 기본 10)
- ✅ `.env` 최신 상태 (`feat/lang-graph` 브랜치에 코드만 push, **`.env` 본인 키는 데스크탑에 따로 복사**)

### DB (운영 데이터)

영상 3편이 chunks·embeddings 포함 그대로 보존됨:

| 영상 길이 | video_id | title | chunks |
|---|---|---|---|
| 5분 | `o58i-LcqxVE` | 물티슈 성분 안전성, 화학적 관점에서 분석 | 38 |
| 20분 | `F9dSJm2VPGk` | 미국 마리화나 규제 완화와 의료용 대마의 화학적 작용 | 48 |
| 60분 | `-A9RxJn5V2o` | 이종범 작가, '장송의 프리렌' 명작 판타지 만화 분석 | 72 |

**데스크탑 DB는 비어있을 것 — 같은 영상 3개 다시 UPLOAD가 권장 경로** (SQL 백업 옮기는 것보다 단순하고 데스크탑 풀스택 동작 검증도 동시에 됨):

```bash
# (선택) 기존 데이터 있으면 wipe — 깨끗한 베이스라인
.venv/Scripts/python.exe -c "
import sys; sys.path.insert(0,'.')
from database import SessionLocal
from sqlalchemy import text
s=SessionLocal()
s.execute(text('TRUNCATE TABLE youtube_knowledge_chunk, youtube_metadata, knowledge, category RESTART IDENTITY CASCADE'))
s.commit(); s.close()
"

# 같은 영상 3개 UPLOAD (kpi_collector로 측정 + 결과 자동 append)
.venv/Scripts/python.exe portfolio/kpi_collector.py upload --url "https://www.youtube.com/watch?v=o58i-LcqxVE" --label "5분 (데스크탑 재측정)"
.venv/Scripts/python.exe portfolio/kpi_collector.py upload --url "https://www.youtube.com/watch?v=F9dSJm2VPGk" --label "20분 (데스크탑 재측정)"
.venv/Scripts/python.exe portfolio/kpi_collector.py upload --url "https://www.youtube.com/watch?v=-A9RxJn5V2o" --label "60분 (데스크탑 재측정)"
```

부가 이득: 노트북 측정값과 데스크탑 측정값을 비교하면 **"측정 재현성"** 자체가 포트폴리오 강점이 됨 (분산·머신 의존도 평가).

### 측정 완료 항목 (수치)

| 실험 | 결과 |
|---|---|
| UPLOAD 5/20/60분 | 12.3 / 14.2 / 17.2s · 비용 합계 $0.023 |
| ThreadPool 1 vs 10 | 청크 요약 **9.25× speedup** (37s → 4s), 총 시간 3.42× |
| SEARCH RAG 5질문 | 평균 **2.02s/질문**, 비용 $0.00172 |
| 의도 분류 50케이스 | **44/50 = 88.0%** (UNKNOWN 64%로 가장 약함, 인젝션 #45 성공) |
| 누적 비용 | $0.054 (paid tier 1, 잔액 ~$4.95) |

### Git 이력 (이미 push 완료)

```
e473075 docs: add comprehensive measurement and verification record  ← 최신
ffeb6a8 feat: KPI experiments — ThreadPool, SEARCH batch, Intent eval
25b5244 feat: Gemini embedding+chat migration with KPI baseline
9c3b1d2 docs: add portfolio bundle (README, MD set, PDF, demo assets)
```

데스크탑에서:
```bash
cd <repo>
git fetch origin
git checkout feat/lang-graph
git pull origin feat/lang-graph
```

## 4. 다음에 할 일 (우선순위 순)

### 🔵 1순위 — 포트폴리오 본문 보강 (코드 무관 작업)

- [ ] **`portfolio/01_대표프로젝트_AKA.md` §9에 트러블슈팅 3건 추가**
  - Celery 5.x errback 회귀 (종합기록 §9.1 그대로 발췌)
  - Gemini 2.0 deprecation 위장 에러 (종합기록 §9.2)
  - Matryoshka 임베딩으로 DB 마이그레이션 0 (종합기록 §9.3)
- [ ] **`portfolio/01_대표프로젝트_AKA.md` §8 (결과/임팩트)에 KPI 실측표 이식**
  - 종합기록 §5·§6·§7·§8 표 4개를 §8 자리에 배치
  - 기존 "추정값, 실측 후 업데이트 예정" 마커 제거
- [ ] **`portfolio/02_프로필_역량_요약.md`와 `05_1페이지_요약본.md`에도 핵심 수치 1줄씩 추가**
  - 예: "ThreadPool=10 병렬화로 청크 요약 9.25× speedup, 60분 영상도 17초 처리"
- [ ] **PDF 재빌드**
  ```bash
  .venv/Scripts/python.exe portfolio/_build_pdf.py
  ```
  → `portfolio/A-KA_포트폴리오_이채훈.pdf` 갱신 + 페이지 수 15~20p 유지 확인

### 🟡 2순위 — 추가 측정 (시간 여유 시)

- [ ] **반복 측정**: 같은 영상 3회씩 측정해 분산(variance) 산출 — 현재는 1회만
- [ ] **다른 콘텐츠 도메인 영상 추가**: 강연·인터뷰·튜토리얼 등으로 일반화 검증
- [ ] **DB 더 큰 corpus (10편 이상) 만든 후 SEARCH RAG 재측정** — 현재 3편은 검색 공간 너무 작음

### 🟢 3순위 — 코드 보강 (선택)

- [ ] **자막 비활성 영상 STT fallback 1줄 fix** (`app/services/youtube_service.py:182` outer except에서 `self._run_stt_process(video_id)` 호출)
- [ ] **의도 분류 인젝션 방어 강화** — system prompt에 인용문·인젝션 패턴 few-shot 추가
- [ ] **OpenAI 키 정리** — `.env`에 빈 값 그대로 둘지, 학원 키 삭제 명시할지 결정

## 5. 자주 쓰는 명령어

### 인프라 점검
```bash
.venv/Scripts/python.exe -c "
import sys; sys.path.insert(0,'.')
import redis
print('redis:', redis.Redis(host='127.0.0.1',port=6379,db=0).ping())
from database import SessionLocal
from sqlalchemy import text
s=SessionLocal()
print('knowledge:', s.execute(text('SELECT COUNT(*) FROM knowledge')).scalar())
print('chunks:', s.execute(text('SELECT COUNT(*) FROM youtube_knowledge_chunk')).scalar())
from app.core.celery_app import celery_app
print('celery:', celery_app.control.inspect(timeout=3).ping())
"
```

### Celery 워커 (Windows는 `--pool=solo` 필수)
```bash
echo "" > portfolio/logs/celery_worker.log
.venv/Scripts/python.exe -m celery -A app.core.celery_app worker --loglevel=info --pool=solo > portfolio/logs/celery_worker.log 2>&1 &
sleep 12
```

### 측정 실행
```bash
# UPLOAD 1편
.venv/Scripts/python.exe portfolio/kpi_collector.py upload --url "<URL>" --label "<라벨>"

# SEARCH 배치
.venv/Scripts/python.exe portfolio/kpi_collector.py search-batch --queries-file portfolio/queries_v1.txt --label "RAG-batch"

# 의도 평가셋
.venv/Scripts/python.exe portfolio/run_intent_eval.py
```

### DB wipe (영상 데이터만, 사용자 보존)
```bash
.venv/Scripts/python.exe -c "
import sys; sys.path.insert(0,'.')
from database import SessionLocal
from sqlalchemy import text
s=SessionLocal()
s.execute(text('TRUNCATE TABLE youtube_knowledge_chunk, youtube_metadata, knowledge, category RESTART IDENTITY CASCADE'))
s.commit(); s.close()
"
```

### Git (이 브랜치만)
```bash
git status --short
git add <변경 파일>
git commit -m "<메시지>"
git push origin feat/lang-graph
# PR 만들지 말 것
```

## 6. 데스크탑 환경 세팅 체크리스트

데스크탑 처음 가져오면:

- [ ] `git clone https://github.com/Team-A-Ka/A-ka_backend.git`
- [ ] `git checkout feat/lang-graph`
- [ ] `python -m venv .venv` + `.venv/Scripts/activate`
- [ ] `pip install -r requirements.txt` (있다면) 또는 노트북의 `.venv/Lib/site-packages` 확인 후 필요 패키지 설치
  - 필수: `celery`, `langchain`, `langchain-google-genai`, `langchain-openai`, `langchain-anthropic`, `langsmith`, `pgvector`, `psycopg2`, `redis`, `sqlalchemy`, `pydantic-settings`, `fastapi`, `openai-whisper` (STT용, 안 써도 됨), `markdown`, `pypdf`
- [ ] `.env` 파일 노트북에서 복사 (또는 새로 작성 — 아래 템플릿)
- [ ] PostgreSQL 17 설치 + `aka_db` 데이터베이스 생성 + pgvector extension 활성화
  - `CREATE EXTENSION IF NOT EXISTS vector;`
- [ ] Redis 설치 또는 WSL Redis (포트 6379)
- [ ] alembic 마이그레이션 적용: `alembic upgrade head`
- [ ] (선택) `portfolio/backups/db_backup_20260604_194739.sql`을 데스크탑에 복사 + 복원

### `.env` 최소 템플릿 (값은 본인 키로 채워야 함)

```env
JWT_SECRET_KEY=<랜덤한_시크릿>

POSTGRES_USER=postgres
POSTGRES_PASSWORD=<비번>
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=5432
POSTGRES_DB=aka_db

REDIS_URL=redis://127.0.0.1:6379/0

LLM_PRIMARY_PROVIDER=gemini
GOOGLE_API_KEY=<본인_Gemini_키>
GEMINI_MODEL=gemini-2.5-flash-lite

OPENAI_API_KEY=

CHUNK_SUMMARY_MAX_WORKERS=10

LANGCHAIN_TRACING_V2=True
LANGCHAIN_API_KEY=<본인_LangSmith_키>
LANGCHAIN_PROJECT=aka-backend
```

## 7. 알아두면 좋은 함정

- **Celery 워커 시작 시점에 `.env` 캐싱**: `.env` 수정 후 워커 재시작 안 하면 새 값 안 읽음. `celery_app.control.shutdown()` + 재기동
- **gemini-2.0-flash는 deprecated** — 절대 쓰지 말 것. `2.5-flash-lite` 또는 `2.5-flash` 사용
- **Gemini 2.5 flash (lite 아님)는 thinking ON 기본** — output 단가 비쌈 ($2.50/1M). flash-lite는 thinking OFF 기본 ($0.40/1M)
- **자막 비활성 영상**: 파이프라인 막힘. 측정용 URL 사용 전 자막 가용성 확인 (예: `cC5Yub8P0aQ`는 막힘)
- **솜 워커는 작업 실패 시 죽기 쉬움**: `--pool=solo` + 새 코드 변경 후 errback 회귀 안 잡으면 좀비 PENDING 행 누적

## 8. 첫 응답 가이드 (Claude Code에게)

이 프롬프트를 받으면 첫 응답에서:

1. 위 7개 섹션을 읽었다는 신호로 한 줄 요약: *"A-KA 인계 받음. 현재 1순위 작업은 §9 트러블슈팅 3건 명문화 + §8 KPI 표 이식."*
2. 인프라 점검 1회 자동 실행 (Redis·Postgres·Celery)
3. 진행 가능 여부 보고 후 사용자에게 다음 행동 확인:
   - `포트폴리오 §9 명문화 시작할까?`
   - `추가 측정부터 할까?`
   - `다른 작업 지시 있어?`

**규칙 재확인**: PR 만들지 마. `feat/lang-graph` 브랜치에만 커밋·푸시.

---
