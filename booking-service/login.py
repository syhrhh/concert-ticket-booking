"""Sign-in for both roles, mounted by main.py under /api/auth.

    POST /api/auth/register  name + email + password -> new CUSTOMER account, signed in
    POST /api/auth/login     email + password -> JWT + user {user_id, name, email, role}
    GET  /api/auth/me      the signed-in user (Authorization: Bearer <token>)

The browser uses `role` to decide between the customer site and the staff console.
"""
from typing import Optional

import re

from fastapi import APIRouter, Header, HTTPException
from psycopg import errors
from pydantic import BaseModel, ConfigDict, Field

import auth
import db

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=200)


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class RegisterRequest(BaseModel):
    """Customers only. There is deliberately no `role` field (and extra fields are
    rejected), so a staff account can never be created through this endpoint."""
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=8, max_length=200)


def _public(user: dict) -> dict:
    return {"user_id": user["user_id"], "name": user["name"], "email": user["email"], "role": user["role"]}


@router.post("/register", status_code=201)
def register(body: RegisterRequest):
    email, name = body.email.strip().lower(), body.name.strip()
    if not name:
        raise HTTPException(422, "INVALID_NAME")
    if not EMAIL_RE.match(email):
        raise HTTPException(422, "INVALID_EMAIL")
    try:
        with db.pool.connection() as conn:
            user = conn.execute(
                "INSERT INTO users (name, email, password_hash, role) VALUES (%s, %s, %s, 'CUSTOMER')"
                " RETURNING user_id, name, email, role",
                (name, email, auth.hash_password(body.password))).fetchone()
    except errors.UniqueViolation:
        raise HTTPException(409, "EMAIL_TAKEN")
    return {"token": auth.create_token(user["user_id"], user["role"]), "user": _public(user)}


@router.post("/login")
def login(body: LoginRequest):
    with db.pool.connection() as conn:
        user = conn.execute("SELECT user_id, name, email, password_hash, role FROM users WHERE email = %s",
                            (body.email.strip().lower(),)).fetchone()
    # One error for "unknown e-mail" and "wrong password": do not reveal which.
    if user is None or not auth.verify_password(body.password, user["password_hash"]):
        raise HTTPException(401, "INVALID_CREDENTIALS")
    return {"token": auth.create_token(user["user_id"], user["role"]), "user": _public(user)}


@router.get("/me")
def me(authorization: Optional[str] = Header(default=None)):
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "UNAUTHORIZED")
    claims = auth.decode_token(authorization[7:].strip())
    if claims is None:
        raise HTTPException(401, "INVALID_TOKEN")
    with db.pool.connection() as conn:
        user = conn.execute("SELECT user_id, name, email, role FROM users WHERE user_id = %s",
                            (int(claims["sub"]),)).fetchone()
    if user is None:
        raise HTTPException(401, "INVALID_TOKEN")
    return _public(user)
