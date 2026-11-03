from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel
from typing import Optional
import requests
import uuid

app = FastAPI(title="Booking Service")

AVAILABILITY_URL = "http://localhost:5002"
NOTIFICATION_URL = "http://localhost:5003"

bookings = {}
processed_keys = {}

class BookingRequest(BaseModel):
    user_id: int
    concert_id: int
    seat_id: int

@app.get("/health")
def health():
    return {"service": "booking", "status": "UP"}

@app.post("/api/bookings")
def create_booking(
    request: BookingRequest,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key")
):
    key = idempotency_key or str(uuid.uuid4())

    if key in processed_keys:
        booking_id = processed_keys[key]
        return bookings[booking_id]

    reservation = requests.post(
        f"{AVAILABILITY_URL}/api/reservations",
        json={
            "concert_id": request.concert_id,
            "seat_id": request.seat_id
        },
        timeout=3
    )

    if reservation.status_code == 409:
        raise HTTPException(status_code=409, detail="SEAT_NOT_AVAILABLE")

    if reservation.status_code != 200:
        raise HTTPException(status_code=503, detail="AVAILABILITY_SERVICE_UNAVAILABLE")

    booking_id = f"B{len(bookings)+1:03d}"
    booking = {
        "booking_id": booking_id,
        "user_id": request.user_id,
        "concert_id": request.concert_id,
        "seat_id": request.seat_id,
        "status": "CONFIRMED",
        "notification_status": "PENDING"
    }

    bookings[booking_id] = booking
    processed_keys[key] = booking_id

    try:
        response = requests.post(
            f"{NOTIFICATION_URL}/api/notifications",
            json={
                "booking_id": booking_id,
                "user_id": request.user_id,
                "type": "BOOKING_CONFIRMED",
                "message": "Your ticket booking has been confirmed."
            },
            timeout=2
        )
        if response.status_code == 200:
            booking["notification_status"] = "SENT"
        else:
            booking["notification_status"] = "FAILED"
    except requests.RequestException:
        booking["notification_status"] = "FAILED"

    return booking

@app.get("/api/bookings/{booking_id}")
def get_booking(booking_id: str):
    if booking_id not in bookings:
        raise HTTPException(status_code=404, detail="BOOKING_NOT_FOUND")
    return bookings[booking_id]

@app.delete("/api/bookings/{booking_id}")
def cancel_booking(booking_id: str):
    if booking_id not in bookings:
        raise HTTPException(status_code=404, detail="BOOKING_NOT_FOUND")

    booking = bookings[booking_id]
    booking["status"] = "CANCELLED"

    try:
        requests.delete(
            f"{AVAILABILITY_URL}/api/reservations/{booking['seat_id']}",
            timeout=3
        )
    except requests.RequestException:
        pass

    return booking
