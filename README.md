# A-ka_backend

### 백엔드 폴더 구조
```
backend/
├── app/
│   ├── api/ v1/          # [Layer 1] Presentation: Controller (Router)
│   │   ├── endpoints/    # 요청을 받고 응답을 보내는 껍데기 (유효성 검사)
│   │   └── api.py        # 라우터 통합 관리
│   ├── services/         # [Layer 2] Business Logic: Service
│   │   ├── youtube.py    # 유튜브 요약 로직 (Part 1 핵심)
│   │   ├── notion.py     # 노션 동기화 로직 (Part 2 핵심)
│   │   └── category.py   # 카테고리 병합/수정 비즈니스 로직
│   ├── repositories/     # [Layer 3] Data Access: Repository (RDB/Vector)
│   │   ├── base.py       # 공통 CRUD (SQLModel/SQLAlchemy)
│   │   ├── knowledge.py  # 지식 데이터 저장/조회 쿼리
│   │   └── vector.py     # Vector DB 검색 및 저장 쿼리
│   ├── models/           # DB 테이블 정의 (Entity)
│   ├── schemas/          # Pydantic 모델 (DTO: Data Transfer Object)
│   ├── core/             # 공통 설정 (Config, Security, Consts)
│   ├── databases/         # DB 연결 설정 (PostgreSQL)
│   ├── agents/           # AI 흐름 제어 (LangGraph Nodes)
│   └── main.py           # FastAPI 앱 실행
├── migrations/           # Alembic 마이그레이션
└── tests/                # 계층별 유닛 테스트
```


### 커밋 메세지 규칙
- **feat**
  - 새로운 기능에 대한 커밋
- **fix**
  -  버그 수정에 대한 커밋
- **build**
  - 빌드 관련 파일 수정 / 모듈 설치 또는 삭제에 대한 커밋
- **chore**
  - 그 외 자잘한 수정에 대한 커밋
- **docs**
  - 문서 수정에 대한 커밋
- **refactor**
  - 코드 리팩토링에 대한 커밋
- **test**
  - 테스트 코드 수정에 대한 커밋
- **perf**
  -  성능 개선에 대한 커밋
