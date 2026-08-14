from fastapi import FastAPI

from app.routers import documents

app = FastAPI(title="Comment Insight")
app.include_router(documents.router)


@app.get("/health")
def health():
    return {"status": "ok"}
