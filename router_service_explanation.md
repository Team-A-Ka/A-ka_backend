# AI Router Service (`router_service.py`) 설명서

이 문서는 `app/services/router_service.py` 파일의 역할과 내부 작동 방식을 설명합니다.

## 1. 역할 (Role)
사용자(카카오톡 등)로부터 들어온 **자연어 텍스트(utterance)**를 분석하여 사용자의 핵심 의도를 파악하고, 그 의도에 맞는 처리 흐름(Pipeline)으로 작업을 넘겨주는 **교통경찰(Router)** 역할을 수행합니다.

## 2. 작동 프로세스
1. **입력 수신**: 사용자가 입력한 문자열 `utterance`를 인자로 받습니다.
2. **OpenAI 의도 분석**: `gpt-4o-mini` 모델과 시스템 프롬프트를 사용하여, 복잡한 자연어 속에서 **의도(Intent)**와 **URL(링크)**을 분류해 냅니다.
3. **Structured Outputs (구조화된 출력)**: Pydantic 스키마(`IntentExtraction`)를 기반으로 OpenAI의 `beta.chat.completions.parse` 기능을 사용합니다. 이를 통해 언어 모델이 쓸데없는 말 없이 오직 `{ "intent": "...", "extracted_url": "..." }` 형태의 검증된 JSON 데이터만 반환하도록 강제합니다.
4. **분기 처리 (Routing)**:
   - `UPLOAD`: 영상을 저장해 달라는 의미입니다. 추출된 URL에서 YouTube Video ID를 찾아내고, 뒷단의 `knowledge_pipeline` 을 가동시킵니다.
   - `SEARCH`: 과거 데이터를 조회하거나 질문하는의미입니다. (향후 RAG 검색 파이프라인으로 연결)
   - `UNKNOWN`: 단순 일상 대화나 의미 없는 텍스트입니다. (향후 일반 챗봇 처리로 연결)

## 3. 왜 LangChain/LangGraph 방식을 쓰지 않았나?
* **단순하고 명확한 목적**: 이 파일의 유일한 목적은 문장을 보고 **방향(A냐 B냐)을 결정**하는 것입니다. 이런 가벼운 연산에 LangGraph 같은 무거운 상태 관리(Stateful) 프레임워크를 올리면 오버헤드(속도 저하, 메모리 낭비)가 심합니다.
* **직관적인 함수 호출**: 최신 `openai` 기본 라이브러리의 `Structured Outputs` 기능이 매우 강력해져서, 무거운 서드파티 라이브러리 없이 순정 파이썬 코드만으로 가장 빠르고 안정적인 라우팅이 가능합니다.
* *참고: LangGraph와 같은 고도화된 툴은 실제로 데이터를 요약하고, 검색하고, 답변을 만들어내는 깊은 파이프라인(예: SEARCH RAG, 요약 에이전트) 내부에서 사용되는 것이 적합합니다.*
