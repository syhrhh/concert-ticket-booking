"""Admin (staff) API, mounted by main.py under /api/admin.

    POST   /api/admin/login                 email + password -> JWT
    GET    /api/admin/me                    who am I
    GET    /api/admin/stats                 totals, per-concert seat occupancy, outbox health
    GET    /api/admin/bookings              all bookings (?status=&concert_id=&q=)
    DELETE /api/admin/bookings/{booking_id} cancel any customer's booking

Every route except /login needs `Authorization: Bearer <token>` with role ADMIN.
"""
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

import auth
import config
import db
import requests
import service

router = APIRouter(prefix="/api/admin", tags=["admin"])

BOOKING_ID_PATTERN = r"^B[0-9A-F]{12}$"
STATUSES = ("PENDING", "CONFIRMED", "REJECTED", "FAILED", "CANCELLED")


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=200)


def require_admin(authorization: Optional[str] = Header(default=None)) -> dict:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "UNAUTHORIZED")
    claims = auth.decode_token(authorization[7:].strip())
    if claims is None:
        raise HTTPException(401, "INVALID_TOKEN")
    if claims.get("role") != "ADMIN":
        raise HTTPException(403, "ADMIN_ONLY")
    return claims


@router.post("/login")
def login(body: LoginRequest):
    with db.pool.connection() as conn:
        user = conn.execute("SELECT user_id, name, email, password_hash, role FROM users WHERE email = %s",
                            (body.email.strip().lower(),)).fetchone()
    # Same error for "no such user" and "wrong password": do not reveal which.
    if user is None or user["role"] != "ADMIN" or not auth.verify_password(body.password, user["password_hash"]):
        raise HTTPException(401, "INVALID_CREDENTIALS")
    return {"token": auth.create_token(user["user_id"], user["role"]),
            "admin": {"user_id": user["user_id"], "name": user["name"], "email": user["email"]}}


@router.get("/me")
def me(claims: dict = Depends(require_admin)):
    with db.pool.connection() as conn:
        user = conn.execute("SELECT user_id, name, email, role FROM users WHERE user_id = %s",
                            (int(claims["sub"]),)).fetchone()
    if user is None or user["role"] != "ADMIN":
        raise HTTPException(401, "INVALID_TOKEN")
    return user


@router.get("/stats")
def stats(_: dict = Depends(require_admin)):
    with db.pool.connection() as conn:
        by_status = {r["status"]: r["n"] for r in conn.execute(
            "SELECT status, count(*) AS n FROM bookings GROUP BY status").fetchall()}
        revenue = conn.execute(
            "SELECT COALESCE(SUM(s.price), 0) AS total FROM bookings b JOIN seats s ON s.seat_id = b.seat_id"
            " WHERE b.status = 'CONFIRMED'").fetchone()["total"]
        concerts = conn.execute("""
            SELECT c.concert_id, c.concert_name, c.venue, c.concert_date,
                   count(s.seat_id)                                    AS total_seats,
                   count(*) FILTER (WHERE s.status = 'AVAILABLE')      AS available,
                   count(*) FILTER (WHERE s.status = 'RESERVED')       AS reserved,
                   count(*) FILTER (WHERE s.status = 'BOOKED')         AS booked,
                   count(*) FILTER (WHERE s.status = 'BLOCKED')        AS blocked
              FROM concerts c LEFT JOIN seats s ON s.concert_id = c.concert_id
             GROUP BY c.concert_id ORDER BY c.concert_id""").fetchall()
        outbox = {f"{r['kind']}:{r['status']}": r["n"] for r in conn.execute(
            "SELECT kind, status, count(*) AS n FROM booking_outbox WHERE status <> 'DONE'"
            " GROUP BY kind, status").fetchall()}
    return {
        "bookings_by_status": {s: by_status.get(s, 0) for s in STATUSES},
        "confirmed_revenue": float(revenue),
        "concerts": [{**c, "concert_date": str(c["concert_date"])} for c in concerts],
        "outbox_backlog": outbox,
    }


@router.get("/bookings")
def list_bookings(
    status: Optional[str] = Query(default=None, pattern=r"^(PENDING|CONFIRMED|REJECTED|FAILED|CANCELLED)$"),
    concert_id: Optional[int] = Query(default=None, gt=0),
    q: Optional[str] = Query(default=None, max_length=100, description="booking id, customer name or e-mail"),
    limit: int = Query(default=200, ge=1, le=500),
    _: dict = Depends(require_admin),
):
    where, params = [], []
    if status:
        where.append("x.status = %s"); params.append(status)
    if concert_id:
        where.append("x.concert_id = %s"); params.append(concert_id)
    if q:
        where.append("(x.booking_id ILIKE %s OR u.name ILIKE %s OR u.email ILIKE %s)")
        params += [f"%{q}%"] * 3
    sql = f"""
        SELECT x.*, u.name AS customer_name, u.email AS customer_email,
               c.concert_name, s.seat_number, s.section, s.price
          FROM ({service._SELECT}) x
          JOIN users u    ON u.user_id = x.user_id
          JOIN concerts c ON c.concert_id = x.concert_id
          JOIN seats s    ON s.seat_id = x.seat_id
         {'WHERE ' + ' AND '.join(where) if where else ''}
         ORDER BY x.created_at DESC, x.booking_id LIMIT %s"""
    with db.pool.connection() as conn:
        rows = conn.execute(sql, (*params, limit)).fetchall()
    return [{**service.view(r), "customer_name": r["customer_name"], "customer_email": r["customer_email"],
             "concert_name": r["concert_name"], "seat_number": r["seat_number"],
             "section": r["section"], "price": float(r["price"])} for r in rows]


@router.delete("/bookings/{booking_id}")
def cancel_any_booking(booking_id: str = Path(pattern=BOOKING_ID_PATTERN), _: dict = Depends(require_admin)):
    """Same code path as a customer cancel (state change + outbox in one
    transaction), acting on behalf of the owner. Idempotent."""
    with db.pool.connection() as conn:
        row = conn.execute("SELECT user_id FROM bookings WHERE booking_id = %s", (booking_id,)).fetchone()
    if row is None:
        return JSONResponse({"detail": "BOOKING_NOT_FOUND"}, status_code=404)
    status, body, headers = service.cancel_booking(booking_id, row["user_id"])
    return JSONResponse(body, status_code=status, headers=headers)


# --------------------------------------------------------------------------
# Seat control: the Availability Service owns seat state, so these routes only
# check the admin token and forward the request to it.
# --------------------------------------------------------------------------
def _forward(path: str) -> JSONResponse:
    try:
        r = requests.put(f"{config.AVAILABILITY_URL}{path}", timeout=config.AVAILABILITY_TIMEOUT)
    except requests.RequestException:
        return JSONResponse({"detail": "AVAILABILITY_SERVICE_UNAVAILABLE"}, status_code=503)
    try:
        body = r.json()
    except ValueError:
        body = {"detail": "AVAILABILITY_SERVICE_UNAVAILABLE"}
    return JSONResponse(body, status_code=r.status_code)


@router.put("/concerts/{concert_id}/seats/{seat_id}/{action}")
def set_seat(concert_id: int = Path(gt=0), seat_id: int = Path(gt=0),
             action: str = Path(pattern=r"^(block|unblock)$"), _: dict = Depends(require_admin)):
    return _forward(f"/api/concerts/{concert_id}/seats/{seat_id}/{action}")


@router.put("/concerts/{concert_id}/sections/{section}/{action}")
def set_section(concert_id: int = Path(gt=0), section: str = Path(max_length=50),
                action: str = Path(pattern=r"^(block|unblock)$"), _: dict = Depends(require_admin)):
    from urllib.parse import quote
    return _forward(f"/api/concerts/{concert_id}/sections/{quote(section, safe='')}/{action}")
