from fastapi import FastAPI

from app.routers import dashboard, documents

app = FastAPI(title="Comment Insight")
app.include_router(documents.router)
app.include_router(dashboard.router)


@app.get("/health")
def health():
    return {"status": "ok"}
