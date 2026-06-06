# A-KA Gemini 전환 후 전체 재검증 + 배포 플랜

> Claude Code 새 세션에 이 파일을 통째로 붙여넣거나 "portfolio/E2E_재검증_배포_플랜.md 읽고 시작해"로 시작.
> 작성: 2026-06-06 (코워크 세션). HANDOFF_프롬프트.md와 측정_및_검증_종합기록.md를 먼저 읽을 것.

## 0. 작업 규칙 (HANDOFF와 동일)

- PR 만들지 마. 모든 커밋은 `feat/lang-graph` 브랜치로만.
- 환경: Windows / Python 3.12 / Celery 로컬(--pool=solo) + Redis 로컬 + Postgres 17 + pgvector
- 각 Phase 완료 시 결과를 `portfolio/측정_및_검증_종합기록.md`에 섹션 추가로 기록 (단일 진실 문서 유지)

## 1. 목표

Gemini 전환(`gemini-2.5-flash-lite` + `gemini-embedding-001` 1536d) 이후 KPI 측정은 UPLOAD·SEARCH 경로만 검증됨.
나머지 전 기능을 E2E로 재검증하고, 약점을 보강한 뒤, 직접 배포까지 완료한다.
최종 산출: ① 전 기능 동작 확인 기록 ② 보강 커밋 ③ 운영 중인 배포 URL ④ 포트폴리오·이력서 반영용 결과 요약.

## 2. Phase 1 — 환경 점검

- [ ] 인프라 ping (HANDOFF §5 인프라 점검 스크립트 그대로 실행: redis / knowledge / chunks / celery)
- [ ] DB에 영상 3편(o58i-LcqxVE, F9dSJm2VPGk, -A9RxJn5V2o) 보존 확인. 없으면 backups/db_backup_20260604_194739.sql 복원
- [ ] Celery 워커 기동 + 로그 파일 확인

## 3. Phase 2 — E2E 기능 매트릭스 (핵심)

각 케이스: 입력 → 기대 결과 → 실제 결과 → PASS/FAIL 표로 기록.

### UPLOAD
- [ ] 정상 URL: 카톡 5초 내 ACK → 노션 페이지 생성(요약·카테고리·조회수) → DB chunks+embeddings 저장
- [ ] 자막 비활성 영상: 현재 STT fallback 미호출(youtube_service.py:182 알려진 버그) — 현상 재현만 기록, 수정은 Phase 3
- [ ] 이미 저장한 URL 재전송: 중복 처리 정책 동작 확인
- [ ] 유효하지 않은 URL / 삭제된 영상: 에러 경로 + 사용자 안내

### SAVE_ONLY
- [ ] LLM 호출 0회 확인 (로그·비용 카운터로 증명)
- [ ] 노션에 메타데이터+카테고리+조회수 반영

### SEARCH (RAG)
- [ ] 정상 질문: 메일로 답변 + 출처 URL 포함
- [ ] DB에 없는 주제 질문: 거리 임계값 0.7 → 빈 결과 분기 → "없음" 안내 (할루시네이션 없이)
- [ ] 무응답 케이스 보강 커밋(1445b79) 동작 확인

### FIND_SIMILAR
- [ ] 유사 영상 추천: 영상 단위 dedup 동작
- [ ] 임계값 0.8 경계: 유사 영상 없을 때 분기
- [ ] include_similar=True 통합 경로 정상

### 의도 분류 / UNKNOWN
- [ ] UNKNOWN 입력 시 안내 메시지
- [ ] run_intent_eval.py 재실행해 88% 기준선 재확인

### 카테고리 (본인 구현 영역 — 집중 검증)
- [ ] 기존 11개 카테고리 매칭
- [ ] 목록에 없는 주제 → LLM 신규 카테고리 생성 + 검증 로직
- [ ] 카테고리명 정규화(공백 제거)·미분류 fallback
- [ ] Shorts 영상 케이스

### 실패 경로 (Celery errback — 트러블슈팅 대표 사례)
- [ ] 파이프라인 중간 단계 강제 실패 → DB FAILED 마킹 + 사용자 안내 메일 발송
- [ ] Celery 5.x 시그니처 수정(213bf23) 회귀 없음 확인

## 4. Phase 3 — 약점 보강 (HANDOFF 3순위 승격)

- [ ] STT fallback 1줄 fix: youtube_service.py:182 outer except에서 self._run_stt_process(video_id) 호출 → 자막 비활성 영상으로 재검증
- [ ] 의도 분류 인젝션 방어: system prompt에 인용문·인젝션 few-shot 추가 → intent eval 재실행, 목표 90%+ (특히 #45 인젝션 케이스 차단)
- [ ] UNKNOWN 정확도 64% 개선 시도 (few-shot 또는 분류 기준 명문화)
- [ ] .env에서 학원 OpenAI 키 제거 결정 반영 (LLM_PRIMARY_PROVIDER=gemini 체제 정리)
- [ ] 보강 후 KPI 1개라도 변화 있으면 KPI_측정결과.md 갱신

## 5. Phase 4 — 배포

- [ ] 배포 대상 결정 (미정 — 본인이 선택: AWS EC2 프리티어 / Lightsail / 기타. 비용 0~수천 원/월 기준 권장)
- [ ] docker-compose.prod.yml 검토: Gemini 전환 반영 여부(env, 이미지), pgvector 포함 Postgres 이미지 확인
- [ ] .env 프로덕션 시크릿 분리 (키 노출 금지, .gitignore 확인)
- [ ] .github/workflows/deploy.yml 점검 — 트리거 브랜치·시크릿 설정 확인 (main 머지 금지 규칙과 충돌 시 workflow_dispatch 수동 트리거로 변경)
- [ ] 배포 후 스모크 테스트: 카톡 웹훅 → UPLOAD 1건 + SEARCH 1건 E2E
- [ ] 운영 URL·아키텍처 한 줄을 종합기록에 추가

## 6. Phase 5 — 기록 및 인계

- [ ] 측정_및_검증_종합기록.md에 "E2E 재검증" "배포" 섹션 추가 (표 + PASS/FAIL + 보강 커밋 해시)
- [ ] 포트폴리오 본문 반영(01 §8 KPI 표, §9 트러블슈팅 3건, 02·05 수치 한 줄, PDF 재빌드)은 코워크 세션 담당 — 여기서는 기록만 정확히
- [x] 끝나면 git push 후 "코워크로 인계: 재검증·배포 완료" 한 줄을 이 파일 맨 아래에 추가

---

## 진행 인계 (2026-06-06~07 데스크탑 세션)

- **Phase 1~3 + 기록 완료**, `feat/lang-graph`에 커밋·push (커밋 `db68bcc`). **배포(Phase 4)는 대상 미정(Railway 유력)으로 다음 세션 이월.**
- **환경**: 데스크탑이라 다수 복구 필요했음 — DB는 Docker pgvector(host 5433), `.env` 5432→5433(.env.bak 백업), `uv sync`(LLM 패키지 누락), 스키마 재구축, redis 기동. 상세 종합기록 §14.
- **Phase 2 전 기능 PASS**: UPLOAD·SEARCH·의도분류(88%)·카테고리·SAVE_ONLY·FIND_SIMILAR·중복URL·실패경로(errback). 무효URL은 STT버그로 부분.
- **Phase 3 보강(코드)**: 임베딩 429 재시도+sub-batch(`llm.py`) / 의도분류 인젝션 few-shot 88→90%·#45차단(`chat_command.py`) / 카테고리 좁은→넓은 우산 일반화(`category_resolver.py`). STT는 점검만(미수정).
- **다음 세션 배포 점검 포인트**: deploy.yml의 `push:main` 트리거 vs main 머지금지 충돌 → workflow_dispatch 전환 / deploy.yml이 worker 미기동 → 포함 / docker-compose.prod의 .env.prod·시크릿 분리 / 1GB 프리티어 RAM(Whisper) → Lightsail·swap 고려.
- **알려진 미해결**: 임베딩 일일 하드쿼터 시 티어 상향 필요(재시도는 분당 스파이크만 방어) / squashed_baseline alembic enum 이중생성 버그(create_all 우회 중) / test_failure_cases.py user_id 시그니처 노후화 / 종합기록 §13.3 DB백업 파일 실제 부재.

> 코워크로 인계: **재검증·보강 완료, 배포는 다음 세션** (Phase 1~3 done / Phase 4 pending).

