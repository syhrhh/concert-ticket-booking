"""Admin API checks against the running stack (docker compose up).
    pytest tests/test_admin.py -v
Uses BOOKING_URL (default http://127.0.0.1:5001) and the default admin account."""
import os
import uuid

import requests

BOOKING = os.getenv("BOOKING_URL", "http://127.0.0.1:5001")
ADMIN = {"email": os.getenv("ADMIN_EMAIL", "admin@encore.local"),
         "password": os.getenv("ADMIN_PASSWORD", "admin123")}


def login():
    r = requests.post(f"{BOOKING}/api/admin/login", json=ADMIN, timeout=10)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_admin_routes_require_a_token():
    assert requests.get(f"{BOOKING}/api/admin/stats", timeout=10).status_code == 401
    assert requests.get(f"{BOOKING}/api/admin/bookings",
                        headers={"Authorization": "Bearer not.a.token"}, timeout=10).status_code == 401


def test_wrong_password_and_customer_account_cannot_log_in():
    for creds in ({**ADMIN, "password": "wrong"}, {"email": "user.a@example.com", "password": "x"}):
        r = requests.post(f"{BOOKING}/api/admin/login", json=creds, timeout=10)
        assert r.status_code == 401 and r.json()["detail"] == "INVALID_CREDENTIALS"


def test_stats_and_booking_list_shape():
    h = login()
    stats = requests.get(f"{BOOKING}/api/admin/stats", headers=h, timeout=10).json()
    assert set(stats["bookings_by_status"]) == {"PENDING", "CONFIRMED", "REJECTED", "FAILED", "CANCELLED"}
    assert stats["concerts"] and "booked" in stats["concerts"][0]
    rows = requests.get(f"{BOOKING}/api/admin/bookings?status=CONFIRMED", headers=h, timeout=10).json()
    assert all(r["status"] == "CONFIRMED" for r in rows)


def test_admin_can_cancel_a_customers_booking_and_it_is_idempotent():
    h = login()
    # find a free seat, book it as demo user 1, then cancel it as admin
    seats = requests.get("http://127.0.0.1:5002/api/concerts/2/seats", timeout=10).json()
    seats = seats["seats"] if isinstance(seats, dict) else seats
    seat = next(s for s in seats if s["status"] == "AVAILABLE")
    b = requests.post(f"{BOOKING}/api/bookings", timeout=15,
                      headers={"Idempotency-Key": f"admin-test-{uuid.uuid4()}"},
                      json={"user_id": 1, "concert_id": 2, "seat_id": seat["seat_id"]})
    assert b.status_code in (200, 201), b.text
    bid = b.json()["booking_id"]
    for _ in range(2):  # second call must also succeed
        r = requests.delete(f"{BOOKING}/api/admin/bookings/{bid}", headers=h, timeout=10)
        assert r.status_code == 200 and r.json()["status"] == "CANCELLED"
    assert requests.delete(f"{BOOKING}/api/admin/bookings/{bid}", timeout=10).status_code == 401


def test_blocked_seat_is_unavailable_and_cannot_be_booked_then_unblocked():
    h = login()
    seats = requests.get("http://127.0.0.1:5002/api/concerts/2/seats", timeout=10).json()
    seat = next(s for s in seats if s["status"] == "AVAILABLE")
    url = f"{BOOKING}/api/admin/concerts/2/seats/{seat['seat_id']}"
    assert requests.put(f"{url}/block", headers=h, timeout=10).json()["status"] == "BLOCKED"
    assert requests.put(f"{url}/block", headers=h, timeout=10).json()["changed"] is False  # idempotent
    status = requests.get(f"http://127.0.0.1:5002/api/concerts/2/seats/{seat['seat_id']}/availability", timeout=10).json()
    assert status["available"] is False and status["seat"]["status"] == "BLOCKED"
    b = requests.post(f"{BOOKING}/api/bookings", timeout=15,
                      headers={"Idempotency-Key": f"blocked-test-{uuid.uuid4()}"},
                      json={"user_id": 1, "concert_id": 2, "seat_id": seat["seat_id"]})
    assert b.status_code == 409 and b.json()["detail"] == "SEAT_NOT_AVAILABLE"
    assert requests.put(f"{url}/unblock", headers=h, timeout=10).json()["status"] == "AVAILABLE"
    assert requests.put(f"{url}/block", timeout=10).status_code == 401  # no token
