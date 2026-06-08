# 코워크 인계 프롬프트 — 이력서 · 포트폴리오 작업

> 사용법: 새 Claude/코워크 세션에 이 파일을 통째로 붙여넣거나 "portfolio/COWORK_인계_이력서_포트폴리오.md 읽고 시작해"로 시작.
> 단일 진실 문서는 `portfolio/측정_및_검증_종합기록.md` (특히 §5~9 측정, §14 E2E 재검증·보강). 수치는 거기서 인용.

---

## 0. 너에게 부탁하는 일

A-KA 백엔드 프로젝트의 **검증된 측정 결과**를 바탕으로 ① 포트폴리오 본문과 ② 이력서를 다듬어줘.
사실은 아래와 종합기록에 다 있으니, **새 수치를 지어내지 말고** 인용·정리·문장화에 집중해줘. 모르면 종합기록을 먼저 읽어.

## 1. 작성자(나) 배경

- SeSAC 도봉 5개월 교육(백엔드/AI 트랙) 수강생. A-KA 팀프로젝트에서 **AI Router / Upload / Search 파이프라인 담당**.
- A-KA = 카카오톡으로 유튜브 링크를 보내면 자막→요약→벡터화→Notion 저장하고, 자연어로 RAG 검색·유사영상 추천을 해주는 백엔드.
- 스택: FastAPI · Celery · PostgreSQL+pgvector · LangChain/LangGraph · Gemini(2.5-flash-lite + gemini-embedding-001 1536d).

## 2. 갱신 대상 파일

| 파일 | 할 일 |
|---|---|
| `portfolio/01_대표프로젝트_AKA.md` | §8 KPI 표 최신화, §9 트러블슈팅 3~4건 반영 |
| `portfolio/02_프로필_역량_요약.md` | 측정·검증·보강 경험 한두 줄 반영 |
| `portfolio/05_1페이지_요약본.md` | 핵심 수치 한 줄 갱신 |
| (이력서 — 별도 파일/요청 시 작성) | §5의 "이력서 불릿" 활용 |
| `portfolio/_build_pdf.py` | 본문 수정 후 PDF 재빌드 (`.venv/Scripts/python.exe portfolio/_build_pdf.py`) |

## 3. 인용 가능한 검증 수치 (종합기록 §5~9, §14)

- **UPLOAD 처리시간**: 5분/20분/60분 영상 → **12.3 / 14.2 / 17.2초**, 청크 38/48/72개. 12배 길이차에 시간은 1.4배만 증가(sub-linear).
- **병렬화(ThreadPool max_workers 1→10)**: 청크 요약 단계 **37초 → 4초 (9.25배)**, 전체 wall-clock 3.42배.
- **SEARCH RAG**: 5질문 평균 **2.02초**, 성공 5/5, **할루시네이션 0**(DB 없는 질문은 "없음" 응답).
- **의도 분류 정확도(50 케이스, 적대적 포함)**: **88.0% → 90.0%** (프롬프트 인젝션 few-shot 보강 후, #45 인젝션·#47 비-유튜브 URL 차단).
- **provider 전환**: OpenAI text-embedding-3-small → Gemini gemini-embedding-001(Matryoshka, output_dimensionality=1536)로 **DB 스키마 마이그레이션 0**.
- **운영 비용**: 월 사용자 100명 기준 LLM ~**$16/월**(인스턴스보다 저렴).
- **임베딩 안정성 보강**: 인라인 임베딩에 429/503 지수 백오프 재시도 + sub-batch 추가 → RPM 스파이크 시에도 임베딩 누락 0.

## 4. 트러블슈팅 스토리 (이력서·면접용, 종합기록 §9·§14)

1. **Celery 5.x errback 회귀(213bf23)**: 4.x→5.x 업그레이드 후 errback 호출 규약 변경(`args[1:3]==('exc','traceback')` 검사)으로 에러 핸들러가 죽던 것을, 시그니처 `(self, exc, traceback, video_id, user_id)`로 재배치해 복구. → 실패 시 DB FAILED 마킹 + 사용자 안내 메일 정상화.
2. **Gemini 임베딩 429(RPM) 견고성**: 코퍼스 일괄 재임베딩 시 batchEmbedContents가 429로 임베딩 0개 조용히 실패 → RAG 붕괴. 원인=계정 RPM 제한+버스트+재시도 부재. sub-batch+지수 백오프 재시도로 해결(UPLOAD·SEARCH·FIND_SIMILAR 공통 choke point 한 곳에서).
3. **OpenAI→Gemini 무중단 전환**: 임베딩 차원을 Matryoshka 1536으로 고정해 `vector(1536)` 스키마 변경 0으로 provider 교체.
4. **(인프라) 환경 재현·복구**: 데스크탑 이전 시 pgvector 미설치/스키마 드리프트를 Docker pgvector(pg16) + alembic 정합화로 복구. alembic squashed_baseline의 enum 이중생성·제약 rename 버그도 조건부화로 수정해 `alembic upgrade head` clean 통과 확보.

## 5. 이력서 불릿 (그대로 다듬어 쓰기)

- "유튜브 요약·RAG 검색 백엔드의 AI 라우팅/업로드/검색 파이프라인을 담당, 의도 분류 정확도를 **88%→90%**로 개선(프롬프트 인젝션 방어 few-shot)."
- "ThreadPool 병렬화로 요약 단계를 **37초→4초(9.25배)** 단축, 60분 영상도 17초 내 처리."
- "OpenAI→Gemini provider 전환을 임베딩 차원 고정(Matryoshka 1536)으로 **DB 마이그레이션 0**으로 수행."
- "Celery 5.x errback 회귀를 진단·수정해 실패 알림 파이프라인 복구, 임베딩 레이트리밋(429)에 백오프 재시도를 추가해 RAG 안정성 확보."
- "50개 적대적 케이스 평가셋·KPI 자동 측정 스크립트로 정량 검증 체계 구축."

## 6. 정직한 한계 (과장 금지 — 면접 대비)

- 의도 분류 90%는 **적대적 케이스 포함** 수치. 남은 오답(#44 도메인밖, #40 SEARCH↔FIND_SIMILAR 경계)은 미해결.
- 임베딩 재시도는 **분당 RPM 스파이크**를 방어. **일일 하드쿼터** 소진 시엔 Gemini 유료 티어 상향 필요(코드로 해결 X).
- STT(자막 비활성 영상 Whisper fallback) 버그는 **본인 담당 영역 아니라 점검만** 함(미수정, `youtube_service.py:182`).
- 측정은 영상 3편·질문 5건 규모의 소표본. 대규모 부하 테스트는 미수행.
- **배포(Phase 4)는 아직 미완**(대상 Railway 유력). "운영 중"이라고 쓰지 말 것.

## 7. 소스 포인터

- 측정·검증 단일 진실: `portfolio/측정_및_검증_종합기록.md` (§5 UPLOAD, §6 ThreadPool, §7 SEARCH, §8 의도분류, §9 트러블슈팅, §14 E2E 재검증·보강)
- 상세 데이터: `portfolio/KPI_측정결과.md`, `portfolio/intent_eval_result.md`(90%)
- 코드 보강 커밋: `feat/lang-graph` (임베딩 재시도·인젝션 few-shot·카테고리 일반화·alembic 수정)
