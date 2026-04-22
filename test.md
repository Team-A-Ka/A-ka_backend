``` mermaid
sequenceDiagram
    actor User as 사용자 (KakaoTalk)
    participant API as FastAPI (Webhook API)
    participant Celery as Celery Task Worker
    participant Router as LangGraph Router Agent
    participant DB as PostgreSQL & VectorDB
    participant KakaoAPI as Kakao Callback API

    User->>API: 1. 메시지 입력 (링크 or 질문)
    API->>Celery: 2. 작업 위임 (Background Task)
    API-->>User: 3. 즉각 응답 (200 OK, 5초 타임아웃 방어)
    
    Celery->>Router: 4. 메시지 분석 요청
    
    alt Intent == "Ingest" (지식 입력)
        Router->>DB: 5a. 데이터 청킹 및 Vector DB 적재
        DB-->>Router: 적재 완료 (Status: COMPLETED)
        Router->>KakaoAPI: 6a. 처리 완료 푸시 알림 전송
    else Intent == "Search" (지식 검색)
        Router->>DB: 5b. user_id, category_id 기반 벡터 검색
        DB-->>Router: 검색 결과 (Chunks) 반환
        Router->>Router: 6b. LLM 답변 생성 (RAG)
        Router->>KakaoAPI: 7b. 생성된 답변 전송
    else Intent == "Status" (작업 상태 조회)
        Router->>DB: 5c. 해당 지식의 status_enum 조회
        DB-->>Router: 상태 반환 (ex: PROCESSING)
        Router->>KakaoAPI: 6c. 현재 상태 알림 전송
    end
    
    KakaoAPI-->>User: 8. 최종 결과 메시지 수신