"""Notification Service - HTTP API (FastAPI, port 5003).

Records booking confirmations and cancellations sent by the Booking Service and
lets the client show them. No real e-mail is sent: a notification is "sent" by
saving it in PostgreSQL and writing it to the service log.

Endpoints
    POST /api/notifications                    record a notification (Idempotency-Key header)
    GET  /api/users/{user_id}/notifications    a user's notifications, oldest first
    GET  /health                               liveness + database check

Distributed-systems role
    * Independent process: if it is down, bookings still work. The Booking
      Service keeps the message in its outbox and retries until we are back.
    * Idempotent consumer: retries can deliver the same message more than once.
      The Idempotency-Key is UNIQUE in the database, so a repeat returns the
      original notification instead of creating a second one.
    * Data survives restarts because it is stored in PostgreSQL, not in memory.
"""
import logging
import time
from contextlib import asynccontextmanager
from typing import Literal, Optional

import psycopg
from fastapi import FastAPI, Header, Path, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from psycopg_pool import PoolTimeout
from pydantic import BaseModel, ConfigDict, Field

import config
import db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
log = logging.getLogger("notification.api")

INT_MAX = 2_147_483_647                          # PostgreSQL INTEGER range
BOOKING_ID_PATTERN = r"^B[0-9A-F]{12}$"           # same format the Booking Service creates
IDEMPOTENCY_KEY_PATTERN = r"^[A-Za-z0-9_.:\-]{8,128}$"
COLUMNS = "notification_id, booking_id, user_id, type, message, status, created_at"


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_pool()
    db.run_sql_file("001_notification_schema.sql")
    if config.FAULT_MODE != "off":
        log.warning("FAULT_MODE=%s is ON (demo only) - delay=%ss", config.FAULT_MODE, config.FAULT_DELAY_SECONDS)
    log.info("notification service ready")
    yield
    db.close_pool()


app = FastAPI(title="Notification Service", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Idempotency-Key"],
    expose_headers=["Idempotent-Replay"],
)


class NotificationRequest(BaseModel):
    """Strict input: unknown fields are rejected and every field is checked."""
    model_config = ConfigDict(extra="forbid")

    booking_id: str = Field(pattern=BOOKING_ID_PATTERN)
    user_id: int = Field(gt=0, le=INT_MAX)
    type: Literal["BOOKING_CONFIRMED", "BOOKING_CANCELLED"]
    message: str = Field(min_length=1, max_length=500)


def as_json(row: dict) -> dict:
    # Stored in UTC (the pool sets timezone=UTC), so mark it with "Z".
    return {**row, "created_at": row["created_at"].isoformat(timespec="seconds") + "Z"}


# --------------------------------------------------------------------------
# Error handling: never leak internals; a database outage becomes a clear 503
# --------------------------------------------------------------------------
@app.exception_handler(psycopg.OperationalError)
@app.exception_handler(PoolTimeout)
async def database_unavailable(request: Request, exc: Exception):
    log.error("database unavailable: %s", type(exc).__name__)
    return JSONResponse({"detail": "DATABASE_UNAVAILABLE"}, status_code=503, headers={"Retry-After": "5"})


@app.exception_handler(RequestValidationError)
async def invalid_request(request: Request, exc: RequestValidationError):
    fields = [".".join(str(p) for p in e["loc"][1:]) or str(e["loc"][0]) for e in exc.errors()]
    log.warning("rejected invalid request %s %s fields=%s", request.method, request.url.path, fields)
    return JSONResponse({"detail": "INVALID_REQUEST", "fields": fields}, status_code=422)


@app.exception_handler(Exception)
async def unexpected(request: Request, exc: Exception):
    log.exception("unexpected error on %s %s", request.method, request.url.path)
    return JSONResponse({"detail": "INTERNAL_SERVER_ERROR"}, status_code=500)


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------
@app.get("/health")
def health():
    db_ok = db.ping()
    body = {"service": "notification", "status": "UP" if db_ok else "DEGRADED",
            "database": "UP" if db_ok else "DOWN"}
    return JSONResponse(body, status_code=200 if db_ok else 503)


@app.post("/api/notifications", status_code=201)
def create_notification(
    body: NotificationRequest,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key",
                                            pattern=IDEMPOTENCY_KEY_PATTERN),
):
    if config.FAULT_MODE == "error":
        log.warning("FAULT_MODE=error: refusing notification for booking %s", body.booking_id)
        return JSONResponse({"detail": "SERVICE_UNAVAILABLE"}, status_code=503)

    with db.pool.connection() as conn:
        # ON CONFLICT DO NOTHING: if this key was already stored, nothing is inserted
        # and no row comes back. The UNIQUE index decides, so it is also safe when two
        # copies of the same message arrive at exactly the same moment.
        created = conn.execute(
            f"""INSERT INTO notifications (booking_id, user_id, type, message, status, idempotency_key)
                VALUES (%s, %s, %s, %s, 'SENT', %s)
                ON CONFLICT (idempotency_key) DO NOTHING
                RETURNING {COLUMNS}""",
            (body.booking_id, body.user_id, body.type, body.message, idempotency_key),
        ).fetchone()

        if created is None:
            # Duplicate delivery (a retry): return the notification we already have.
            existing = conn.execute(
                f"SELECT {COLUMNS} FROM notifications WHERE idempotency_key = %s", (idempotency_key,)
            ).fetchone()

    if created is None:
        if (existing["booking_id"], existing["type"]) != (body.booking_id, body.type):
            log.warning("Idempotency-Key %s reused for a different message - refused", idempotency_key)
            return JSONResponse({"detail": "IDEMPOTENCY_KEY_REUSED"}, status_code=422)
        log.info("DUPLICATE ignored key=%s -> already have notification #%s (booking %s)",
                 idempotency_key, existing["notification_id"], body.booking_id)
        _maybe_slow_reply()
        return JSONResponse(as_json(existing), status_code=200, headers={"Idempotent-Replay": "true"})

    # "Sending" the notification = it is now stored, plus this log line.
    log.info("SENT #%s %s for booking %s to user %s: %s",
             created["notification_id"], body.type, body.booking_id, body.user_id, body.message)
    _maybe_slow_reply()
    return JSONResponse(as_json(created), status_code=201)


def _maybe_slow_reply() -> None:
    """DEMO ONLY: the work is already saved, but the reply is late, so the caller
    times out and retries. Shows why duplicate detection is needed."""
    if config.FAULT_MODE == "slow":
        log.warning("FAULT_MODE=slow: delaying reply by %ss", config.FAULT_DELAY_SECONDS)
        time.sleep(config.FAULT_DELAY_SECONDS)


@app.get("/api/users/{user_id}/notifications")
def list_user_notifications(
    user_id: int = Path(gt=0, le=INT_MAX),
    limit: int = Query(default=50, ge=1, le=200),
):
    """Oldest first (the frontend shows the newest at the top)."""
    with db.pool.connection() as conn:
        rows = conn.execute(
            f"""SELECT {COLUMNS} FROM (
                    SELECT {COLUMNS} FROM notifications WHERE user_id = %s
                    ORDER BY notification_id DESC LIMIT %s
                ) latest ORDER BY notification_id""",
            (user_id, limit),
        ).fetchall()
    return [as_json(r) for r in rows]
