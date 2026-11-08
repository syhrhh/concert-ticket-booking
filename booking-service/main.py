"""Booking Service - HTTP API (FastAPI, port 5001).

Endpoints
    POST   /api/bookings                   create a booking   (Idempotency-Key header)
    GET    /api/bookings/{booking_id}      view one booking
    GET    /api/users/{user_id}/bookings   view a user's bookings
    DELETE /api/bookings/{booking_id}?user_id=   cancel a booking
    GET    /health, /health/dependencies   liveness / dependency status
"""
import logging
import re
from contextlib import asynccontextmanager
from typing import Optional

import psycopg
from fastapi import FastAPI, Header, Path, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from psycopg_pool import PoolTimeout
from pydantic import BaseModel, ConfigDict, Field

import clients
import config
import db
import outbox
import service

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
log = logging.getLogger("booking.api")

INT_MAX = 2_147_483_647  # PostgreSQL INT range
BOOKING_ID_PATTERN = r"^B[0-9A-F]{12}$"
IDEMPOTENCY_KEY_PATTERN = r"^[A-Za-z0-9_.:\-]{8,128}$"


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_pool()
    db.run_sql_file("001_booking_schema.sql")
    if config.SEED_DEMO_DATA:
        db.run_sql_file("demo_seed.sql")
    outbox.worker.start()
    yield
    outbox.worker.stop()
    db.close_pool()


app = FastAPI(title="Booking Service", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Idempotency-Key"],
    expose_headers=["Idempotent-Replay", "Retry-After"],
)


class BookingRequest(BaseModel):
    """Strict input: unknown fields are rejected, ids must be positive ints."""
    model_config = ConfigDict(extra="forbid")

    user_id: int = Field(gt=0, le=INT_MAX)
    concert_id: int = Field(gt=0, le=INT_MAX)
    seat_id: int = Field(gt=0, le=INT_MAX)


def reply(result: service.Result) -> JSONResponse:
    status, body, headers = result
    return JSONResponse(content=body, status_code=status, headers=headers)


# --------------------------------------------------------------------------
# error handling: never leak internals, degrade to 503 when the DB is down
# --------------------------------------------------------------------------
@app.exception_handler(psycopg.OperationalError)
@app.exception_handler(PoolTimeout)
async def database_unavailable(request: Request, exc: Exception):
    log.error("database unavailable: %s", type(exc).__name__)
    return JSONResponse({"detail": "DATABASE_UNAVAILABLE"}, status_code=503, headers={"Retry-After": "5"})


@app.exception_handler(Exception)
async def unexpected_error(request: Request, exc: Exception):
    log.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse({"detail": "INTERNAL_ERROR"}, status_code=500)


# --------------------------------------------------------------------------
# routes
# --------------------------------------------------------------------------
@app.get("/health")
def health():
    db_up = db.ping()
    body = {"service": "booking", "status": "UP" if db_up else "DEGRADED",
            "database": "UP" if db_up else "DOWN"}
    return JSONResponse(body, status_code=200 if db_up else 503)


@app.get("/health/dependencies")
def health_dependencies():
    """Shows partial failure at a glance: which downstream service is down and
    how much work is queued for it."""
    with db.pool.connection() as conn:
        backlog = conn.execute(
            "SELECT kind, count(*) AS n FROM booking_outbox WHERE status = 'PENDING' GROUP BY kind"
        ).fetchall()
    return {
        "service": "booking",
        "database": "UP" if db.ping() else "DOWN",
        "availability_service": clients.probe(config.AVAILABILITY_URL),
        "notification_service": clients.probe(config.NOTIFICATION_URL),
        "outbox_pending": {r["kind"]: r["n"] for r in backlog},
    }


@app.post("/api/bookings")
def create_booking(
    request: BookingRequest,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key",
                                            pattern=IDEMPOTENCY_KEY_PATTERN),
):
    """Create a booking. Send a unique Idempotency-Key per booking attempt (a
    UUID is ideal) and reuse it when retrying the same attempt."""
    return reply(service.create_booking(request.user_id, request.concert_id, request.seat_id,
                                        idempotency_key))


@app.get("/api/bookings/{booking_id}")
def get_booking(booking_id: str = Path(pattern=BOOKING_ID_PATTERN)):
    return reply(service.get_booking(booking_id))


@app.get("/api/users/{user_id}/bookings")
def list_user_bookings(user_id: int = Path(gt=0, le=INT_MAX)):
    return reply(service.list_user_bookings(user_id))


@app.delete("/api/bookings/{booking_id}")
def cancel_booking(
    booking_id: str = Path(pattern=BOOKING_ID_PATTERN),
    user_id: int = Query(gt=0, le=INT_MAX, description="Caller; must own the booking"),
):
    """user_id stands in for authentication in this prototype; a production
    system would take the caller's identity from a verified token."""
    return reply(service.cancel_booking(booking_id, user_id))
