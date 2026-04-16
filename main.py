from fastapi import FastAPI
from database import engine
from app import models

models.Base.metadata.create_all(bind=engine)


app = FastAPI()


@app.get("/")
def read_root():
    return {"Hello": "asd"}
