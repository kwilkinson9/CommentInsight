from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app import auth
from app.database import get_db

router = APIRouter(tags=["auth"])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


@router.get("/login")
def login_form(request: Request):
    if request.session.get("user_id"):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"error": None})


@router.post("/login")
async def login_submit(request: Request, conn: sqlite3.Connection = Depends(get_db)):
    form = await request.form()
    email = form.get("email") or ""
    password = form.get("password") or ""

    user = auth.authenticate(conn, email, password)
    if user is None:
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Incorrect email or password, or too many attempts -- try again shortly."},
            status_code=401,
        )

    request.session.clear()
    request.session["user_id"] = user["id"]
    request.session["email"] = user["email"]
    return RedirectResponse("/", status_code=303)


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
