from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional

# --- Input (카카오에서 들어오는 요청 규격) ---
class KakaoUser(BaseModel):
    id: str

class KakaoUserRequest(BaseModel):
    model_config = {"populate_by_name": True}
    user: KakaoUser
    user_message: str = Field(alias="utterance")  # 카카오 JSON의 'utterance' 키를 내부에서는 'user_message'로 사용

class KakaoAction(BaseModel):
    name: str
    detailParams: Optional[Dict[str, Any]] = None

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, description="사용자가 보낸 채팅 내용")

class KakaoWebhookRequest(BaseModel):
    userRequest: KakaoUserRequest
    action: KakaoAction
    contexts: Optional[List[Any]] = None
    bot: Optional[Dict[str, Any]] = None

# --- Output (서버에서 나가는 응답 규격) ---
class SimpleText(BaseModel):
    text: str

class Output(BaseModel):
    simpleText: SimpleText

class Template(BaseModel):
    outputs: List[Output]

class KakaoWebhookResponse(BaseModel):
    version: str = "2.0"
    template: Template