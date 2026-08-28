import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.routers import auth, dashboard, documents

SESSION_SECRET_KEY = os.environ.get("SESSION_SECRET_KEY")
if not SESSION_SECRET_KEY:
    raise RuntimeError(
        "SESSION_SECRET_KEY is not set. Generate one (e.g. `python3 -c "
        "\"import secrets; print(secrets.token_hex(32))\"`) and put it in "
        "your .env file -- see .env.example."
    )

# Cookies are only marked Secure (HTTPS-only) when explicitly told to be --
# defaults to off so local http://127.0.0.1 development still works. This
# MUST be set to a truthy value for any deployment reachable over the
# network, or session cookies can be intercepted in plain text. See
# SECURITY.md.
SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "").lower() in ("1", "true", "yes")

app = FastAPI(title="Comment Insight")
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET_KEY,
    same_site="lax",
    https_only=SESSION_COOKIE_SECURE,
    max_age=14 * 24 * 3600,
)


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    if SESSION_COOKIE_SECURE:
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    return response


app.mount("/static", StaticFiles(directory=str(Path(__file__).resolve().parent / "static")), name="static")
app.include_router(auth.router)
app.include_router(documents.router)
app.include_router(dashboard.router)


@app.get("/health")
def health():
    return {"status": "ok"}
