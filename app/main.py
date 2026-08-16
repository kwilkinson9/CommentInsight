from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.routers import dashboard, documents

app = FastAPI(title="Comment Insight")
app.mount("/static", StaticFiles(directory=str(Path(__file__).resolve().parent / "static")), name="static")
app.include_router(documents.router)
app.include_router(dashboard.router)


@app.get("/health")
def health():
    return {"status": "ok"}
