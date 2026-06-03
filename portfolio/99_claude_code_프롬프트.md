# 📋 Claude Code 인계 프롬프트

> 이 파일 내용을 통째로 복사해서 Claude Code 새 세션 첫 메시지에 붙여넣으면 됩니다.

---

## ⬇️ 아래부터 복사

안녕. 이 프로젝트(`A-KA` / Archive KakaoTalk)는 카카오톡으로 유튜브 영상을 보내면 AI가 자동으로 요약·분류·검색까지 처리해 노션에 아카이브해주는 서비스야. 4인 백엔드 팀으로 개발 완료했고, 발표도 끝났고, **현재는 포트폴리오 작성과 OpenAI API 자체 운영 전환 단계**야.

내 담당 영역은 다음과 같아:
- AI 라우터 (의도 분류 + 4갈래 분기) — `app/services/chat_command.py`
- LangGraph 2개 그래프 (Intelligence + SEARCH RAG) — `app/services/intelligence_service.py`, `search_service.py`
- 임베딩 파이프라인 + pgvector 저장
- RAG 검색 답변 생성 (할루시네이션 4중 방어)
- 유사 영상 추천 (영상 단위 dedup) — `app/services/search_service.py:find_similar_videos`
- SAVE_ONLY 로직 — `app/services/save_only_service.py`
- Celery `.on_error()` 트러블슈팅 + 핸들러 설계 — `app/tasks/knowledge_tasks.py:handle_pipeline_failure_task`

자막 추출·청킹·DB 스키마·카카오톡/노션/SMTP 연동은 다른 팀원 영역.

---

## 📂 프로젝트 구조

```
C:\A-ka_backend\
├── app/                        # 메인 코드
│   ├── services/               # 비즈니스 로직 (내 담당 대부분)
│   ├── routers/endpoints/      # FastAPI 엔드포인트
│   ├── tasks/                  # Celery 태스크
│   └── core/config.py          # 환경 설정
├── docker-compose.yml          # 4개 서비스 (web/worker/redis/db)
├── .env                        # 환경변수
├── portfolio/                  # 포트폴리오 작업 폴더 (작성 중)
│   ├── 00_최종_할일_체크리스트.md
│   ├── 01_대표프로젝트_AKA.md          # 11항목 메인 본문 (잡코디 가이드 구조)
│   ├── 02_프로필_역량_요약.md           # 프로필 + 역량 매트릭스 + Executive Summary
│   ├── 03_README_백엔드.md
│   ├── 04_README_AI.md
│   ├── 05_1페이지_요약본.md
│   ├── 06_시연영상_활용가이드.md
│   ├── 07_만점_가는_가이드.md            # 14.5 → 16점 가는 방법
│   └── assets/                          # 시연 영상 자산 (스크린샷 6장 + GIF 2개 + mp4)
├── 발표 대본 2.md                       # 발표 대본 + Q&A 27개
└── project_flow_ppt.mermaid             # 시스템 아키텍처 다이어그램
```

---

## 🎯 해줬으면 하는 일 (우선순위 순)

### 🔥 우선순위 1: OpenAI API 키 적용 확인 (10분)

지금까지 학원 OpenAI 키를 썼는데 학원 종료로 지원이 끊겼어. **내 개인 OpenAI 키로 전환**할 거야.

해야 할 일:
1. `.env` 파일에서 `OPENAI_API_KEY` 줄 위치 확인하고 알려줘
2. 내가 키 교체한 후 `docker-compose restart web worker`로 재시작하면 작동하는지 검증
3. 간단한 동작 테스트:
   - 임베딩 호출 한 번 테스트 (`text-embedding-3-small`)
   - `analyze_intent()` 호출 한 번 테스트
4. 에러 나면 원인 진단해줘

참고: OpenAI 플랫폼에서 결제 정보 등록 + $5 충전 + Usage Limit 설정은 내가 직접 해둘 거야.

---

### 🔥 우선순위 2: KPI 실측 (1시간)

포트폴리오에 추정값으로 들어가 있는 KPI를 **실측값으로 교체**해야 해. 결과는 `portfolio/KPI_측정결과.md`에 표 형식으로 저장하고, `portfolio/01_대표프로젝트_AKA.md`의 **"8. 결과/임팩트"** 섹션도 같이 업데이트해줘.

측정 항목:

1. **UPLOAD 파이프라인 단계별 시간** (영상 3개)
   - 5분짜리 / 20분짜리 / 60분짜리 각 1개 (직접 골라서)
   - 각 단계: `collect_and_chunk` → `run_intelligence_graph` → `update_pipeline_status`
   - 전체 소요 시간 + 단계별 소요 시간
   - LangSmith 로그도 같이 캡처 (있다면)

2. **SEARCH RAG 응답 시간** (질문 5개 평균)
   - 질문은 저장된 영상 기반으로 적절히 골라
   - 각 단계 분리: `vectorize_query` → `search_chunks` (pgvector 쿼리) → `generate_answer` (LLM)
   - 평균/최대/최소

3. **청크 요약 병렬화 효과**
   - `intelligence_service.py:summarize_each_chunk`의 `ThreadPoolExecutor(max_workers=10)`를 `max_workers=1`로 바꿔서 한 번 측정
   - 다시 `max_workers=10`으로 측정해서 비교
   - 몇 배 빨라지는지 확인 (예상: 8~10배)

4. **LLM 호출 횟수 / 영상**
   - 영상 1편 처리 시 청크별 요약 N회 + Overview 1회 + 카테고리 정규화 1회 = 총 몇 번인지
   - 토큰 사용량은 OpenAI 응답의 `usage` 필드로 집계

측정 후 비용 추정도 같이 (`gpt-4o-mini` $0.15/1M 입력, $0.60/1M 출력 기준).

---

### 🟡 우선순위 3: 의도 분류 평가셋 (30분)

`portfolio/intent_eval_set.md` 파일 새로 만들고, **의도 분류 평가셋 50개 케이스** 작성 + 정확도 측정.

요구사항:
- 인텐트별 10개씩: UPLOAD / SAVE_ONLY / FIND_SIMILAR / SEARCH / UNKNOWN
- 경계 케이스 반드시 포함:
  - 부정문 (예: `"저장만이라는 단어 쓰지 마"`)
  - 인용문 (예: `'"저장만 해줘" 라고 누가 그랬어'`)
  - 프롬프트 인젝션 (예: `"ignore previous instructions and reply..."`)
  - 영어/한국어 혼합
  - 유튜브 URL 여러 개
  - 불완전한 URL (예: `https://youtube.com/watch` — video_id 11자리 없음)

`app/services/chat_command.py:analyze_intent()` 함수에 50개 케이스를 순차 호출해서:
- 정답률 (예: 47/50 = 94%)
- 오답 케이스별 원인 분석

결과는 `portfolio/intent_eval_set.md`에 표 형식으로 저장. 분류 결과를 `portfolio/01_대표프로젝트_AKA.md`의 **"7. 실험/검증"** 섹션에도 반영해줘.

---

### 🟡 우선순위 4: 트러블슈팅 1~2개 추가 발굴 (1시간)

포트폴리오에는 현재 Celery `.on_error()` 트러블슈팅 1건만 있는데, 2~3건이면 더 풍부해져. 다음 후보 중 실제 코드에서 발견 가능한 것 1~2개 골라서 정리해줘:

- **카테고리 분산 → 우산 정규화로 해결** (`app/services/category_resolver.py` 참고)
- **LLM 구조화 출력 실패 (JSON 형식 불일치) → with_structured_output + 재시도**
- **유사 영상 결과에 같은 영상 청크 여러 개 → video_id 기준 dedup 그루핑**
- **summary 비어있는 SAVE_ONLY 레코드 → UPLOAD 업그레이드 흐름**

각 사례를 발표 슬라이드 10번과 같은 형식 (`상황 → 문제 → 원인 → 해결 → 결과 → 교훈`)으로 작성해서 `portfolio/01_대표프로젝트_AKA.md`의 **"9. 운영/확장"** 섹션에 추가.

---

### 🟢 우선순위 5: GitHub Repo 정리 (15분)

내 GitHub Repo는 https://github.com/Team-A-Ka/A-ka_backend 야.

해야 할 일:
1. `portfolio/assets/` 폴더 전체를 커밋·푸시 (스크린샷·GIF·영상)
2. Repo 루트의 `README.md`를 `portfolio/04_README_AI.md` 내용으로 교체 (AI/ML 직무용으로 지원할 예정이라)
3. 커밋 메시지: `docs: add portfolio README with demo assets`
4. 푸시 후 GitHub 페이지에서 GIF 자동 재생되는지 확인

만약 백엔드 직무용으로 동시 지원할 거면 백엔드 버전(`03_README_백엔드.md`)도 별도 브랜치나 별도 파일로 보존하는 방안 알려줘.

---

### 🟢 우선순위 6: PDF 변환 (15분)

잡코디 포트폴리오 가이드 기준 **PDF 15~20페이지**가 필요해.

다음 4개 파일을 하나의 PDF로 통합 변환:
- `portfolio/01_대표프로젝트_AKA.md`
- `portfolio/02_프로필_역량_요약.md`
- `portfolio/05_1페이지_요약본.md`

방법 추천:
- pandoc 또는 markdown-pdf 사용
- 한국어 폰트 깨지지 않게 (Malgun Gothic 등)
- 이미지 임베드 확인 (`./assets/*.jpg` 경로)
- 최종 파일명: `portfolio/A-KA_포트폴리오_이채훈.pdf`
- 15~20p 분량 맞는지 확인

---

### 🔵 우선순위 7: LangSmith 트레이싱 활성화 (선택, 30분)

포트폴리오 가점 자료로 LangSmith 트레이싱 스크린샷이 있으면 좋아.

해야 할 일:
1. LangSmith 계정 만들기 (https://smith.langchain.com, 무료 플랜 OK)
2. API 키 발급
3. `.env`에 추가:
   ```
   LANGCHAIN_TRACING_V2=true
   LANGCHAIN_API_KEY=lsv2_pt_...
   LANGCHAIN_PROJECT=aka-backend
   ```
4. 컨테이너 재시작
5. UPLOAD + SEARCH 한 번씩 돌려서 트레이싱 데이터 발생시킴
6. LangSmith 대시보드에서 그래프 노드별 흐름·토큰 사용량 스크린샷 캡처
7. `portfolio/assets/`에 `langsmith_trace.png` 등으로 저장
8. `portfolio/01_대표프로젝트_AKA.md`의 적절한 위치에 임베드

이건 시간 여유 있을 때만.

---

## 📝 작업 시 참고사항

### 환경 정보
- OS: Windows
- Docker Compose 사용 중 (web/worker/redis/db 4개 컨테이너)
- Python 3.12, FastAPI, Celery, PostgreSQL 16 + pgvector

### 코드에서 자주 참조할 위치
- 모델 설정: `app/core/config.py` (`OPENAI_MODEL=gpt-4o-mini`, `OPENAI_EMBEDDING_MODEL=text-embedding-3-small`)
- LLM 인스턴스 생성: `app/core/llm.py`
- Celery 설정: `app/core/celery_app.py`
- 환경변수: `.env`

### 포트폴리오 작업 시 주의
- 추정값은 *(추정값, 실측 후 업데이트 예정)* 마커가 붙어있음 → 실측값으로 교체
- 스크린샷은 `./assets/` 경로로 참조
- YouTube 시연 영상 URL: https://youtu.be/cC5Yub8P0aQ (이미 적용됨)
- 내 정보: 이채훈 / maxbeny666@gmail.com / 010-2752-2117 / GitHub maxbeny999

### 발표 대본
`발표 대본 2.md`에 5분 50초 분량 발표 스크립트 + 27개 Q&A가 있어. 트러블슈팅 사례 추가 발굴 시 참고 자료로 쓸 수 있음.

---

## 🚦 시작 순서

내가 따로 지시 안 하면 다음 순서로 진행해줘:

1. 먼저 `portfolio/00_최종_할일_체크리스트.md`와 `portfolio/01_대표프로젝트_AKA.md`를 읽고 현재 상태 파악
2. `우선순위 1` (OpenAI 키 적용 검증)부터 시작
3. 한 단계 완료할 때마다 결과 보여주고 다음 단계 진행 여부 확인
4. 막히는 부분이나 의사결정 필요한 부분은 멈추고 물어봐줘

---

## 📌 마지막으로

- **이 프로젝트는 내가 처음 만든 게 아니야**. 코드 일부는 LangChain·LangGraph·Claude 도움받아 짠 부분도 있어. 그래서 모든 라인을 외우진 않았어. 작업 진행 중 *"왜 이렇게 짰냐?"* 물어보면 같이 코드 읽으면서 답하자.
- 잡코디 가이드 기준 **현재 14.5/16점**이고, **16점 만점 가는 게 목표**.
- 시간 부족하면 우선순위 1~3까지가 가장 중요. 4~7은 보너스.

준비됐어. 시작해줘.

---

## ⬆️ 여기까지 복사
