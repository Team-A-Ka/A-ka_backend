from pydantic import BaseModel
from typing import Dict, Any, List, Optional

# --- Input (카카오에서 들어오는 요청 규격) ---
class KakaoUser(BaseModel):
    id: str

class KakaoUserRequest(BaseModel):
    user: KakaoUser
    utterance: str  # 유저가 카카오톡에 입력한 텍스트

class KakaoAction(BaseModel):
    name: str
    detailParams: Optional[Dict[str, Any]] = None

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