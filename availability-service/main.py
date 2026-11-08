"""Concert availability service (Member 3) backed by PostgreSQL.

Run from availability-service/: python -m uvicorn main:app --reload --port 5002
"""

import logging
import os
from decimal import Decimal
from typing import Annotated

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Path, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://concert_user:concert_pass@localhost:5432/concert_booking",
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args={"connect_timeout": 3})
app = FastAPI(title="Concert Availability Service", version="1.0.0")
# Allow only the local React development origins, not all websites.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type"],
)
logger = logging.getLogger("availability-service")


class ReservationRequest(BaseModel):
    concert_id: int = Field(gt=0)
    seat_id: int = Field(gt=0)
    booking_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


def api_error(status_code: int, error_code: str, message: str) -> None:
    raise HTTPException(status_code=status_code, detail={"error_code": error_code, "message": message})


@app.exception_handler(HTTPException)
async def http_error_handler(request: Request, exc: HTTPException):
    detail = exc.detail if isinstance(exc.detail, dict) else {"error_code": "HTTP_ERROR", "message": str(exc.detail)}
    return JSONResponse(status_code=exc.status_code, content={"success": False, **detail})


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=400,
        content={"success": False, "error_code": "INVALID_REQUEST", "message": "Missing or invalid input."},
    )


@app.exception_handler(SQLAlchemyError)
async def database_error_handler(request: Request, exc: SQLAlchemyError):
    logger.exception("Database operation failed")
    return JSONResponse(
        status_code=503,
        content={"success": False, "error_code": "SERVICE_UNAVAILABLE", "message": "Database is unavailable."},
    )


def serialize_concert(concert):
    row = dict(concert)
    row["concert_date"] = row["concert_date"].isoformat()
    if row["concert_time"] is not None:
        row["concert_time"] = row["concert_time"].isoformat(timespec="minutes")
    return row


def serialize_seat(seat):
    row = dict(seat)
    if isinstance(row.get("price"), Decimal):
        row["price"] = float(row["price"])
    return row


@app.get("/health")
def health():
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"service": "availability", "status": "UP", "database": "CONNECTED"}


@app.get("/api/concerts")
def list_concerts():
    with engine.connect() as conn:
        results = conn.execute(
            text("""
                SELECT concert_id, concert_name, artist_name, venue, concert_date, concert_time, description
                FROM concerts ORDER BY concert_date, concert_id
            """)
        ).mappings().all()
    return [serialize_concert(row) for row in results]


@app.get("/api/concerts/{concert_id}")
def get_concert(concert_id: Annotated[int, Path(gt=0)]):
    with engine.connect() as conn:
        result = conn.execute(
            text("""
                SELECT concert_id, concert_name, artist_name, venue, concert_date, concert_time, description
                FROM concerts WHERE concert_id = :concert_id
            """),
            {"concert_id": concert_id},
        ).mappings().first()
    if result is None:
        api_error(404, "CONCERT_NOT_FOUND", "The concert does not exist.")
    return serialize_concert(result)


@app.get("/api/concerts/{concert_id}/seats")
def list_seats(concert_id: Annotated[int, Path(gt=0)]):
    with engine.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM concerts WHERE concert_id = :concert_id"),
            {"concert_id": concert_id},
        ).scalar_one_or_none()
        if not exists:
            api_error(404, "CONCERT_NOT_FOUND", "The concert does not exist.")
        seats = conn.execute(
            text("""
                SELECT seat_id, concert_id, section, row_number, seat_number, price, status
                FROM seats WHERE concert_id = :concert_id ORDER BY seat_id
            """),
            {"concert_id": concert_id},
        ).mappings().all()
    return [serialize_seat(seat) for seat in seats]


@app.get("/api/concerts/{concert_id}/seats/{seat_id}/availability")
def seat_availability(concert_id: Annotated[int, Path(gt=0)], seat_id: Annotated[int, Path(gt=0)]):
    with engine.connect() as conn:
        seat = conn.execute(
            text("""
                SELECT seat_id, concert_id, section, row_number, seat_number, price, status
                FROM seats WHERE concert_id = :concert_id AND seat_id = :seat_id
            """),
            {"concert_id": concert_id, "seat_id": seat_id},
        ).mappings().first()
    if seat is None:
        api_error(404, "SEAT_NOT_FOUND", "This seat does not exist for the selected concert.")
    return {"available": seat["status"] == "AVAILABLE", "seat": serialize_seat(seat)}


@app.post("/api/reservations", status_code=200)
def reserve_seat(payload: ReservationRequest):
    """Atomically reserve a seat for a booking (called by Booking Service).

    The booking must already exist as PENDING. Seat states: AVAILABLE -> RESERVED
    -> BOOKED. Both transitions happen inside one transaction under a row lock on
    the seat, so concurrent requests for the same seat are serialized and exactly
    one succeeds. UNIQUE(concert_id, seat_id) on reservations is the second line
    of defence. Retrying the same booking_id returns the existing reservation.
    """
    params = payload.model_dump()
    try:
        with engine.begin() as conn:
            seat = conn.execute(
                text("""
                    SELECT seat_id, status FROM seats
                    WHERE concert_id = :concert_id AND seat_id = :seat_id
                    FOR UPDATE
                """),
                params,
            ).mappings().first()
            if seat is None:
                api_error(404, "SEAT_NOT_FOUND", "This seat does not exist for the selected concert.")

            booking = conn.execute(
                text("SELECT concert_id, seat_id, status FROM bookings WHERE booking_id = :booking_id"),
                params,
            ).mappings().first()
            if booking is None:
                api_error(404, "BOOKING_NOT_FOUND", "Booking does not exist. Create it as PENDING first.")
            if booking["concert_id"] != payload.concert_id or booking["seat_id"] != payload.seat_id:
                api_error(400, "INVALID_REQUEST", "Concert/seat does not match the booking.")

            # Checked after the seat lock so concurrent retries see a consistent state.
            previous = conn.execute(
                text("SELECT reservation_id FROM reservations WHERE booking_id = :booking_id"),
                params,
            ).mappings().first()
            if previous is not None:
                return {
                    "reservation_id": previous["reservation_id"],
                    "booking_id": payload.booking_id,
                    "seat_id": payload.seat_id,
                    "status": "RESERVED",
                    "already_reserved": True,
                }

            if booking["status"] not in ("PENDING", "CONFIRMED"):
                api_error(409, "INVALID_BOOKING_STATE", "Only PENDING or CONFIRMED bookings can reserve a seat.")
            if seat["status"] != "AVAILABLE":
                api_error(409, "SEAT_NOT_AVAILABLE", "The selected seat is no longer available.")

            conn.execute(text("UPDATE seats SET status = 'RESERVED' WHERE seat_id = :seat_id"), params)
            reservation_id = conn.execute(
                text("""
                    INSERT INTO reservations (booking_id, concert_id, seat_id, status)
                    VALUES (:booking_id, :concert_id, :seat_id, 'ACTIVE')
                    RETURNING reservation_id
                """),
                params,
            ).scalar_one()
            conn.execute(text("UPDATE seats SET status = 'BOOKED' WHERE seat_id = :seat_id"), params)
        return {
            "reservation_id": reservation_id,
            "booking_id": payload.booking_id,
            "seat_id": payload.seat_id,
            "status": "RESERVED",
            "already_reserved": False,
        }
    except IntegrityError:
        api_error(409, "SEAT_NOT_AVAILABLE", "The selected seat is no longer available.")


@app.get("/api/reservations/{booking_id}")
def get_reservation(booking_id: str):
    with engine.connect() as conn:
        result = conn.execute(
            text("""
                SELECT reservation_id, booking_id, concert_id, seat_id, status
                FROM reservations WHERE booking_id = :booking_id
            """),
            {"booking_id": booking_id},
        ).mappings().first()
    if result is None:
        api_error(404, "RESERVATION_NOT_FOUND", "Reservation not found.")
    return dict(result)


@app.delete("/api/reservations/{booking_id}")
def release_seat(booking_id: str):
    """Release the seat owned by this booking (BOOKED -> AVAILABLE). Safe to retry."""
    with engine.begin() as conn:
        initial = conn.execute(
            text("SELECT seat_id FROM reservations WHERE booking_id = :booking_id"),
            {"booking_id": booking_id},
        ).mappings().first()
        if initial is None:
            booking = conn.execute(
                text("SELECT seat_id FROM bookings WHERE booking_id = :booking_id"),
                {"booking_id": booking_id},
            ).mappings().first()
            if booking is None:
                api_error(404, "BOOKING_NOT_FOUND", "Booking does not exist.")
            return {"booking_id": booking_id, "seat_id": booking["seat_id"],
                    "status": "RELEASED", "already_released": True}

        # Lock the seat first, same order as reserve_seat (no deadlocks).
        conn.execute(
            text("SELECT seat_id FROM seats WHERE seat_id = :seat_id FOR UPDATE"),
            {"seat_id": initial["seat_id"]},
        ).first()
        deleted = conn.execute(
            text("DELETE FROM reservations WHERE booking_id = :booking_id"),
            {"booking_id": booking_id},
        ).rowcount
        conn.execute(
            text("UPDATE seats SET status = 'AVAILABLE' WHERE seat_id = :seat_id AND status = 'BOOKED'"),
            {"seat_id": initial["seat_id"]},
        )
    return {"booking_id": booking_id, "seat_id": initial["seat_id"],
            "status": "RELEASED", "already_released": deleted == 0}
