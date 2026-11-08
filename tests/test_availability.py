"""Member 3 pytest evidence for the Availability Service (needs it running on :5002).

    pip install pytest requests sqlalchemy "psycopg[binary]"
    pytest tests/test_availability.py -v

Tests act as Booking Service: they insert a PENDING booking, then call the API.
"""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
import requests

import db_helpers

BASE = "http://127.0.0.1:5002"


def call(method, path, **kw):
    return requests.request(method, BASE + path, timeout=8, **kw)


def new_booking(seat_id, concert_id=1, status="PENDING"):
    b = f"T_{uuid4().hex[:16]}"
    db_helpers.create_booking(b, concert_id, seat_id, status=status)
    return b


def reserve(booking_id, seat_id, concert_id=1):
    return call("POST", "/api/reservations",
                json={"concert_id": concert_id, "seat_id": seat_id, "booking_id": booking_id})


def seat_status(seat_id):
    seats = call("GET", "/api/concerts/1/seats").json()
    return next(s["status"] for s in seats if s["seat_id"] == seat_id)


@pytest.fixture
def ctx():
    """A free seat of concert 1 plus a list of booking IDs to clean up afterwards."""
    seat = next(s for s in call("GET", "/api/concerts/1/seats").json() if s["status"] == "AVAILABLE")
    used = []
    yield seat["seat_id"], used
    db_helpers.cleanup(used)


def test_health():
    r = call("GET", "/health")
    assert r.status_code == 200 and r.json()["database"] == "CONNECTED"


def test_concerts_and_seats():
    assert len(call("GET", "/api/concerts").json()) >= 1
    assert call("GET", "/api/concerts/1/seats").status_code == 200
    r = call("GET", "/api/concerts/999")
    assert r.status_code == 404 and r.json()["error_code"] == "CONCERT_NOT_FOUND"


def test_demo1_successful_reservation(ctx):
    seat_id, used = ctx
    b = new_booking(seat_id); used.append(b)
    r = reserve(b, seat_id)
    assert r.status_code == 200 and r.json()["status"] == "RESERVED"
    assert seat_status(seat_id) == "BOOKED"
    assert call("GET", f"/api/concerts/1/seats/{seat_id}/availability").json()["available"] is False


def test_demo2_concurrent_conflict(ctx):
    seat_id, used = ctx
    ids = [new_booking(seat_id) for _ in range(20)]
    used.extend(ids)
    with ThreadPoolExecutor(20) as pool:
        res = list(pool.map(lambda b: reserve(b, seat_id), ids))
    assert Counter(r.status_code for r in res) == {200: 1, 409: 19}
    assert all(r.json()["error_code"] == "SEAT_NOT_AVAILABLE" for r in res if r.status_code == 409)


def test_demo3_duplicate_request_is_idempotent(ctx):
    seat_id, used = ctx
    b = new_booking(seat_id); used.append(b)
    with ThreadPoolExecutor(10) as pool:
        res = list(pool.map(lambda _: reserve(b, seat_id), range(10)))
    assert all(r.status_code == 200 for r in res)
    assert Counter(r.json()["already_reserved"] for r in res) == {False: 1, True: 9}


def test_cancel_releases_and_allows_rebooking(ctx):
    seat_id, used = ctx
    b = new_booking(seat_id); used.append(b)
    assert reserve(b, seat_id).status_code == 200
    assert call("DELETE", f"/api/reservations/{b}").json()["already_released"] is False
    assert call("DELETE", f"/api/reservations/{b}").json()["already_released"] is True  # retry-safe
    assert seat_status(seat_id) == "AVAILABLE"
    b2 = new_booking(seat_id); used.append(b2)
    assert reserve(b2, seat_id).status_code == 200


def test_booking_must_exist_match_and_be_active(ctx):
    seat_id, used = ctx
    r = reserve("NO_SUCH_BOOKING", seat_id)
    assert r.status_code == 404 and r.json()["error_code"] == "BOOKING_NOT_FOUND"
    b = new_booking(seat_id); used.append(b)
    other_seat = seat_id + 1
    assert reserve(b, other_seat).json()["error_code"] == "INVALID_REQUEST"  # seat != booking's seat
    db_helpers.set_booking_status(b, "CANCELLED")
    r = reserve(b, seat_id)
    assert r.status_code == 409 and r.json()["error_code"] == "INVALID_BOOKING_STATE"
    assert seat_status(seat_id) == "AVAILABLE"


@pytest.mark.parametrize("body", [{}, {"concert_id": "x", "seat_id": 1, "booking_id": "a"},
                                  {"concert_id": 1, "seat_id": 1, "booking_id": "bad id!"},
                                  {"concert_id": 1, "seat_id": -5, "booking_id": "a"}])
def test_input_validation(body):
    r = call("POST", "/api/reservations", json=body)
    assert r.status_code == 400 and r.json()["error_code"] == "INVALID_REQUEST"


def test_unknown_seat_and_booking():
    seat = call("GET", "/api/concerts/1/seats").json()[0]["seat_id"]
    assert reserve("X1", 9999).json()["error_code"] == "SEAT_NOT_FOUND"
    assert call("DELETE", "/api/reservations/NOPE").json()["error_code"] == "BOOKING_NOT_FOUND"
