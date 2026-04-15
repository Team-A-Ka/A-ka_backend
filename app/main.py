from fastapi import FastAPI
from app.routers.api import api_router # 경로 수정됨

app = FastAPI(title="A-Ka Backend API")

# 모아둔 라우터를 /api/v1 주소 아래에 포함시키기
app.include_router(api_router, prefix="/api/v1")

@app.get("/")
def read_root():
    return {"message": "Server is running!"}