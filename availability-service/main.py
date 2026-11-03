from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Availability Service")

concerts = [
    {"concert_id": 1, "concert_name": "Demo Concert", "venue": "Main Arena"}
]

seats = {
    1: [
        {"seat_id": 1, "seat_number": "A1", "status": "AVAILABLE"},
        {"seat_id": 2, "seat_number": "A2", "status": "AVAILABLE"},
        {"seat_id": 3, "seat_number": "A3", "status": "AVAILABLE"}
    ]
}

class ReservationRequest(BaseModel):
    concert_id: int
    seat_id: int

@app.get("/health")
def health():
    return {"service": "availability", "status": "UP"}

@app.get("/api/concerts")
def get_concerts():
    return concerts

@app.get("/api/concerts/{concert_id}/seats")
def get_seats(concert_id: int):
    if concert_id not in seats:
        raise HTTPException(status_code=404, detail="CONCERT_NOT_FOUND")
    return seats[concert_id]

@app.get("/api/concerts/{concert_id}/seats/{seat_id}/availability")
def check_availability(concert_id: int, seat_id: int):
    for seat in seats.get(concert_id, []):
        if seat["seat_id"] == seat_id:
            return {"available": seat["status"] == "AVAILABLE", "seat": seat}
    raise HTTPException(status_code=404, detail="SEAT_NOT_FOUND")

@app.post("/api/reservations")
def reserve_seat(request: ReservationRequest):
    for seat in seats.get(request.concert_id, []):
        if seat["seat_id"] == request.seat_id:
            if seat["status"] != "AVAILABLE":
                raise HTTPException(status_code=409, detail="SEAT_NOT_AVAILABLE")
            seat["status"] = "BOOKED"
            return {"status": "RESERVED", "seat_id": request.seat_id}
    raise HTTPException(status_code=404, detail="SEAT_NOT_FOUND")

@app.delete("/api/reservations/{seat_id}")
def release_seat(seat_id: int):
    for concert_seats in seats.values():
        for seat in concert_seats:
            if seat["seat_id"] == seat_id:
                seat["status"] = "AVAILABLE"
                return {"status": "RELEASED", "seat_id": seat_id}
    raise HTTPException(status_code=404, detail="SEAT_NOT_FOUND")
