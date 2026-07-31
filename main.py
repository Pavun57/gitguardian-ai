import os

from fastapi import FastAPI

app = FastAPI()

aws_api_key = os.environ.get("AWS_API_KEY")


@app.get("/")
async def root():
    return {"message": f"Hello World {aws_api_key}"}
