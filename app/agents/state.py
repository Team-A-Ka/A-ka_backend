from typing import TypedDict, List, Dict, Any, Optional
from operator import add
from typing_extensions import Annotated

class AgentState(TypedDict):
    """
    LangGraph 에이전트가 노드를 이동할 때마다 들고 다니는 상태입니다.
    """
    # 1. 초기 입력값 (웹훅에서 받아온 데이터)
    user_id: str
    original_query: str  # 유저가 입력한 원본 텍스트 (ex: 유튜브 링크 또는 질문)
    
    # 2. 분류 결과 (라우팅을 위한 데이터)
    # "ingest"(데이터 저장) 모드인지, "query"(질문 답변) 모드인지 판별
    intent: Optional[str] 
    
    # 3. RAG 검색 결과 (Query 모드일 때 사용)
    # 검색된 지식 청크들을 리스트로 담습니다. Annotated와 add를 쓰면 기존 리스트에 계속 추가됩니다.
    retrieved_chunks: Annotated[List[str], add]
    
    # 4. 외부 수집 데이터 (Ingest 모드일 때 사용)
    # 유튜브나 인스타에서 긁어온 자막, 제목 등
    extracted_metadata: Optional[Dict[str, Any]]
    
    # 5. 최종 결과물
    # 노션에 전송하기 직전의 마크다운 텍스트
    final_answer: Optional[str]