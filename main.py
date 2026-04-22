from fastapi import FastAPI
from database import engine
from app import models
from app.routers.api import api_router

models.Base.metadata.create_all(bind=engine)


app = FastAPI()

app.include_router(api_router, prefix="/api/v1")


@app.get("/")
def read_root():
    return {"Hello": "asd"}
