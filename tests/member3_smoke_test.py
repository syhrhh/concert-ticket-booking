"""Integration smoke test against an actual running availability service.

Run from repository root:
    pip install requests
    python tests/member3_smoke_test.py

Requires the demo DB (users + seats) and the DB reachable via DATABASE_URL.
Test inserts PENDING bookings itself (acting as Booking Service) and cleans them up.
Requires free sample seats. Test creates and cleans its
own bookings, but will not erase other users' reservations.
"""
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
import requests
import db_helpers

BASE_URL = "http://127.0.0.1:5002"
TIMEOUT = 6


def request(method, path, **kwargs):
    return requests.request(method, f"{BASE_URL}{path}", timeout=TIMEOUT, **kwargs)


def ensure(test_name, ok):
    if not ok:
        raise AssertionError(f"FAIL: {test_name}")
    print(f"PASS: {test_name}")


def main():
    health = request("GET", "/health")
    ensure("Service and database healthy", health.status_code == 200 and health.json().get("database") == "CONNECTED")

    concerts = request("GET", "/api/concerts")
    ensure("Concert list endpoint", concerts.status_code == 200 and len(concerts.json()) > 0)
    concert_id = concerts.json()[0]["concert_id"]

    seats = request("GET", f"/api/concerts/{concert_id}/seats")
    ensure("Seat list endpoint", seats.status_code == 200)
    free = next((seat for seat in seats.json() if seat["status"] == "AVAILABLE"), None)
    if free is None:
        raise RuntimeError("No AVAILABLE test seats: use a fresh development DB or add a test seat.")
    seat_id = free["seat_id"]

    created = []
    first_booking = f"TEST_{uuid4().hex[:16]}"
    second_booking = f"TEST_{uuid4().hex[:16]}"
    for b in (first_booking, second_booking):  # Booking Service creates PENDING first
        db_helpers.create_booking(b, concert_id, seat_id)
        created.append(b)

    def reserve(booking_id):
        if booking_id not in created:
            db_helpers.create_booking(booking_id, concert_id, seat_id)
            created.append(booking_id)
        return request("POST", "/api/reservations", json={
            "concert_id": concert_id, "seat_id": seat_id, "booking_id": booking_id
        })

    # Real simultaneous HTTP calls: only one can reserve the same seat.
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(reserve, booking_id) for booking_id in (first_booking, second_booking)]
        responses = [future.result() for future in futures]
    statuses = sorted(response.status_code for response in responses)
    ensure("Concurrent conflict: exactly one success, one 409", statuses == [200, 409])

    winner_idx = next(i for i, response in enumerate(responses) if response.status_code == 200)
    winner_id = (first_booking, second_booking)[winner_idx]

    try:
        repeated = reserve(winner_id)
        ensure("Same booking ID does not create duplicate reservation",
               repeated.status_code == 200 and repeated.json().get("already_reserved") is True)

        availability = request("GET", f"/api/concerts/{concert_id}/seats/{seat_id}/availability")
        ensure("Booked seat displays unavailable", availability.status_code == 200 and not availability.json()["available"])
    finally:
        released = request("DELETE", f"/api/reservations/{winner_id}")
        ensure("Cancel releases the owning reservation", released.status_code == 200)

    again = request("GET", f"/api/concerts/{concert_id}/seats/{seat_id}/availability")
    ensure("Seat available again after cancellation", again.status_code == 200 and again.json()["available"])

    new_id = f"TEST_{uuid4().hex[:16]}"
    second_reservation = reserve(new_id)
    try:
        ensure("Another booking succeeds after cancellation", second_reservation.status_code == 200)
    finally:
        db_helpers.cleanup(created)

    print("\nAll Member 3 smoke tests passed.")


if __name__ == "__main__":
    main()
