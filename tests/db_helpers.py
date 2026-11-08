"""Test-only helper: plays the role of Booking Service by inserting PENDING bookings.

Needs the same Postgres as the Availability Service (override with DATABASE_URL).
    pip install requests sqlalchemy "psycopg[binary]"
"""
import os

import requests
from sqlalchemy import create_engine, text

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://concert_user:concert_pass@127.0.0.1:5432/concert_booking",
)
AVAILABILITY_URL = "http://127.0.0.1:5002"
_engine = create_engine(DATABASE_URL)


def create_booking(booking_id, concert_id, seat_id, user_id=1, status="PENDING"):
    with _engine.begin() as conn:
        conn.execute(
            text("""INSERT INTO bookings (booking_id, user_id, concert_id, seat_id, status)
                    VALUES (:b, :u, :c, :s, :st)"""),
            {"b": booking_id, "u": user_id, "c": concert_id, "s": seat_id, "st": status},
        )


def set_booking_status(booking_id, status):
    with _engine.begin() as conn:
        conn.execute(text("UPDATE bookings SET status = :s WHERE booking_id = :b"),
                     {"s": status, "b": booking_id})


def cleanup(booking_ids):
    """Release seats through the API, then remove the test bookings."""
    for b in booking_ids:
        requests.delete(f"{AVAILABILITY_URL}/api/reservations/{b}", timeout=6)
    with _engine.begin() as conn:
        conn.execute(text("DELETE FROM bookings WHERE booking_id = ANY(:ids)"),
                     {"ids": list(booking_ids)})
