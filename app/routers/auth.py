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


_INVALID_TOKEN_MESSAGE = "This reset link is invalid, expired, or already used. Ask whoever manages the server for a new one."


@router.get("/reset-password/{token}")
def reset_password_form(token: str, request: Request, conn: sqlite3.Connection = Depends(get_db)):
    if auth.get_valid_reset_token(conn, token) is None:
        return templates.TemplateResponse(
            request, "reset_password.html", {"error": _INVALID_TOKEN_MESSAGE, "token": None}, status_code=400
        )
    return templates.TemplateResponse(request, "reset_password.html", {"error": None, "token": token})


@router.post("/reset-password/{token}")
async def reset_password_submit(token: str, request: Request, conn: sqlite3.Connection = Depends(get_db)):
    if auth.get_valid_reset_token(conn, token) is None:
        return templates.TemplateResponse(
            request, "reset_password.html", {"error": _INVALID_TOKEN_MESSAGE, "token": None}, status_code=400
        )

    form = await request.form()
    password = form.get("password") or ""
    confirm = form.get("confirm_password") or ""

    if len(password) < 8:
        return templates.TemplateResponse(
            request, "reset_password.html", {"error": "Use at least 8 characters.", "token": token}, status_code=400
        )
    if password != confirm:
        return templates.TemplateResponse(
            request, "reset_password.html", {"error": "Passwords didn't match.", "token": token}, status_code=400
        )

    auth.reset_password(conn, token, password)
    request.session.clear()
    return templates.TemplateResponse(
        request, "login.html", {"error": None, "message": "Password updated -- log in with your new password."}
    )
