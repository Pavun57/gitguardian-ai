from fastapi import FastAPI
app = FastAPI() 
aws_api_key="AWYJSPKNSHWIMOA"
@app.get("/")
async def root():
    return {"message": f"Hello World {aws_api_key}"}