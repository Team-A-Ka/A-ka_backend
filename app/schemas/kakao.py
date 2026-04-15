from pydantic import BaseModel
from typing import Dict, Any, List, Optional

# --- Input (카카오에서 서버로 들어오는 데이터) ---
class KakaoUser(BaseModel):
    id: str

class KakaoUserRequest(BaseModel):
    user: KakaoUser
    utterance: str  # 유저가 입력한 텍스트

class KakaoAction(BaseModel):
    name: str
    detailParams: Optional[Dict[str, Any]] = None

class KakaoWebhookRequest(BaseModel):
    userRequest: KakaoUserRequest
    action: KakaoAction

# --- Output (서버에서 카카오로 나가는 데이터) ---
class SimpleText(BaseModel):
    text: str

class Output(BaseModel):
    simpleText: SimpleText

class Template(BaseModel):
    outputs: List[Output]

class KakaoWebhookResponse(BaseModel):
    version: str = "2.0"
    template: Template