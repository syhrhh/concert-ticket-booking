"""Evidence for the assignment's distributed behaviours (booking side).

Run:  pytest tests -v        (see tests/README.md)

Scenario map
  1. test_successful_booking_*              -> successful booking across services
  2. test_conflicting_booking_*, test_concurrent_bookings_* -> conflict rejected
  3. test_duplicate_*, test_same_key_*      -> duplicate-request handling
  4. test_notification_down_*               -> partial failure + recovery
     test_availability_down_*, test_stale_pending_*  -> further failure cases
"""
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
import requests

from conftest import URLS, wait_until


def new_key() -> str:
    return "test-" + uuid.uuid4().hex


def burst(n, fn):
    """Run fn(i) in n threads released at the same instant."""
    gate = Barrier(n)

    def run(i):
        gate.wait()
        return fn(i)

    with ThreadPoolExecutor(max_workers=n) as pool:
        return list(pool.map(run, range(n)))


# ===========================================================================
# 1. Successful booking
# ===========================================================================
def test_successful_booking_spans_all_services(stack):
    r = stack.book(user_id=1, seat_id=1, key=new_key())
    assert r.status_code == 201
    booking = r.json()
    assert booking["status"] == "CONFIRMED"
    booking_id = booking["booking_id"]

    # Availability Service (another process) now shows the seat as booked.
    assert stack.seat_status(1) == "BOOKED"

    # The booking can be viewed again, and appears in the user's list.
    assert stack.get_booking(booking_id).json()["status"] == "CONFIRMED"
    listing = requests.get(f"{stack.booking_url}/api/users/1/bookings").json()
    assert [b["booking_id"] for b in listing] == [booking_id]

    # Notification Service (a third process) received the confirmation.
    wait_until(lambda: any(n["booking_id"] == booking_id for n in stack.notifications(1)),
               what="confirmation notification")
    assert stack.get_booking(booking_id).json()["notification_status"] == "SENT"


# ===========================================================================
# 2. Conflicting bookings are rejected
# ===========================================================================
def test_conflicting_booking_is_rejected_and_recorded(stack):
    first = stack.book(user_id=1, seat_id=2, key=new_key())
    second = stack.book(user_id=2, seat_id=2, key=new_key())

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["detail"] == "SEAT_NOT_AVAILABLE"
    assert second.json()["booking"]["status"] == "REJECTED"  # the result is stored

    rows = dict(stack.query("SELECT status, count(*) FROM bookings WHERE seat_id = 2 GROUP BY status"))
    assert rows == {"CONFIRMED": 1, "REJECTED": 1}


def test_concurrent_bookings_for_one_seat_only_one_succeeds(stack):
    """10 different users hit the same seat at the same instant."""
    responses = burst(10, lambda i: stack.book(user_id=i + 1, seat_id=3, key=new_key()))
    codes = sorted(r.status_code for r in responses)

    assert codes == [201] + [409] * 9
    active = stack.query("SELECT count(*) FROM bookings WHERE seat_id = 3 AND status IN ('PENDING','CONFIRMED')")
    assert active == [(1,)]
    assert stack.seat_status(3) == "BOOKED"


# ===========================================================================
# 3. Duplicate requests
# ===========================================================================
def test_duplicate_request_with_same_key_returns_same_booking(stack):
    key = new_key()
    first = stack.book(user_id=1, seat_id=1, key=key)
    retry = stack.book(user_id=1, seat_id=1, key=key)   # e.g. client timed out and retried

    assert first.status_code == 201
    assert retry.status_code == 200
    assert retry.headers["Idempotent-Replay"] == "true"
    assert retry.json()["booking_id"] == first.json()["booking_id"]
    assert stack.query("SELECT count(*) FROM bookings") == [(1,)]

    # ...and the customer is notified exactly once.
    wait_until(lambda: stack.notifications(1), what="notification")
    time.sleep(1.5)
    assert len(stack.notifications(1)) == 1


def test_concurrent_duplicates_with_same_key_create_one_booking(stack):
    key = new_key()
    responses = burst(10, lambda i: stack.book(user_id=1, seat_id=1, key=key))

    assert sorted(r.status_code for r in responses) == [200] * 9 + [201]
    assert len({r.json()["booking_id"] for r in responses}) == 1
    assert stack.query("SELECT count(*) FROM bookings") == [(1,)]


def test_repeat_without_key_never_creates_a_second_confirmed_booking(stack):
    """Without an Idempotency-Key a repeat is indistinguishable from a second
    customer, so it is refused rather than booked twice."""
    first = stack.book(user_id=1, seat_id=1)
    again = stack.book(user_id=1, seat_id=1)
    assert first.status_code == 201
    assert again.status_code == 409
    assert stack.query("SELECT count(*) FROM bookings WHERE status = 'CONFIRMED'") == [(1,)]


def test_same_key_with_different_request_is_refused(stack):
    key = new_key()
    assert stack.book(user_id=1, seat_id=1, key=key).status_code == 201
    other = stack.book(user_id=1, seat_id=2, key=key)
    assert other.status_code == 422
    assert other.json()["detail"] == "IDEMPOTENCY_KEY_REUSED"
    assert stack.seat_status(2) == "AVAILABLE"


def test_replayed_rejection_stays_rejected(stack):
    stack.book(user_id=1, seat_id=1, key=new_key())
    key = new_key()
    a = stack.book(user_id=2, seat_id=1, key=key)
    b = stack.book(user_id=2, seat_id=1, key=key)
    assert a.status_code == b.status_code == 409
    assert a.json()["booking"]["booking_id"] == b.json()["booking"]["booking_id"]


# ===========================================================================
# Cancel
# ===========================================================================
def test_cancel_releases_seat_and_is_idempotent(stack):
    booking = stack.book(user_id=1, seat_id=1, key=new_key()).json()
    bid = booking["booking_id"]

    assert stack.cancel(bid, user_id=2).status_code == 403          # not the owner
    assert stack.get_booking(bid).json()["status"] == "CONFIRMED"

    assert stack.cancel(bid, user_id=1).json()["status"] == "CANCELLED"
    assert stack.cancel(bid, user_id=1).json()["status"] == "CANCELLED"   # repeat is harmless

    wait_until(lambda: stack.seat_status(1) == "AVAILABLE", what="seat released")
    wait_until(lambda: stack.get_booking(bid).json()["cancellation_notification_status"] == "SENT",
               what="cancellation notice")
    assert stack.get_booking(bid).json()["seat_release_status"] == "RELEASED"

    # The seat can now be booked by someone else.
    assert stack.book(user_id=2, seat_id=1, key=new_key()).status_code == 201
    assert stack.cancel("B000000000000", user_id=1).status_code == 404


# ===========================================================================
# 4. Partial failure: Notification Service down
# ===========================================================================
def test_notification_down_booking_keeps_working_and_recovers(stack):
    stack.stop("notification")                                   # <-- the partial failure

    started = time.time()
    r = stack.book(user_id=1, seat_id=1, key=new_key())
    elapsed = time.time() - started
    assert r.status_code == 201, "booking must not depend on the notification service"
    assert elapsed < 2.5, "and must not wait on it"
    first = r.json()
    assert first["notification_status"] == "PENDING"

    # Everything else still works while Notification is down.
    second = stack.book(user_id=2, seat_id=2, key=new_key())
    assert second.status_code == 201
    assert stack.get_booking(first["booking_id"]).status_code == 200
    assert stack.cancel(second.json()["booking_id"], user_id=2).status_code == 200

    # The system reports the degradation and keeps retrying with back-off.
    health = requests.get(f"{stack.booking_url}/health/dependencies").json()
    assert health["notification_service"] == "DOWN"
    assert health["availability_service"] == "UP"
    assert health["outbox_pending"]["NOTIFY_CONFIRMED"] >= 1
    wait_until(lambda: stack.query("SELECT max(attempts) FROM booking_outbox WHERE kind = 'NOTIFY_CONFIRMED'")[0][0] >= 2,
               what="at least two delivery attempts")

    stack.start("notification")                                  # <-- recovery

    wait_until(lambda: stack.get_booking(first["booking_id"]).json()["notification_status"] == "SENT",
               timeout=20, what="queued notification delivered")
    delivered = [n for n in stack.notifications(1) if n["booking_id"] == first["booking_id"]]
    assert len(delivered) == 1, "queued notification delivered exactly once"


# ===========================================================================
# Further failure cases
# ===========================================================================
def test_availability_down_gives_fast_503_and_same_key_retry_succeeds(stack):
    key = new_key()
    stack.stop("availability")

    started = time.time()
    r = stack.book(user_id=1, seat_id=1, key=key)
    assert time.time() - started < 5
    assert r.status_code == 503
    assert r.json()["detail"] == "AVAILABILITY_SERVICE_UNAVAILABLE"
    assert r.json()["booking"]["status"] == "FAILED"
    booking_id = r.json()["booking"]["booking_id"]
    assert requests.get(f"{stack.booking_url}/health").status_code == 200   # booking itself is fine

    stack.start("availability")

    def retry():
        resp = stack.book(user_id=1, seat_id=1, key=key)
        return resp if resp.status_code == 201 else None    # 503 RECOVERY_IN_PROGRESS is expected for a moment

    ok = wait_until(retry, timeout=20, interval=0.5, what="retry to succeed")
    assert ok.json()["booking_id"] == booking_id            # same record, never a second booking
    assert stack.query("SELECT count(*) FROM bookings") == [(1,)]
    assert stack.seat_status(1) == "BOOKED"


def test_stale_pending_booking_is_recovered(stack):
    """Simulates the booking service crashing mid-request: a PENDING booking
    whose seat was already reserved. The worker must free both."""
    # The booking row must exist before a seat can be reserved for it.
    stack.query("INSERT INTO bookings (booking_id, user_id, concert_id, seat_id, status)"
                " VALUES ('BC0FFEE000001', 1, 1, 3, 'PENDING')")
    requests.post(f"{URLS['availability']}/api/reservations",
                  json={"concert_id": 1, "seat_id": 3, "booking_id": "BC0FFEE000001"}).raise_for_status()
    # ...then pretend the request started a minute ago and the service died.
    stack.query("UPDATE bookings SET updated_at = (now() AT TIME ZONE 'UTC') - interval '60 seconds'"
                " WHERE booking_id = 'BC0FFEE000001'")
    assert stack.seat_status(3) == "BOOKED"

    wait_until(lambda: stack.get_booking("BC0FFEE000001").json()["status"] == "FAILED",
               timeout=20, what="stale booking marked FAILED")
    wait_until(lambda: stack.seat_status(3) == "AVAILABLE", timeout=20, what="seat released")
    assert stack.book(user_id=2, seat_id=3, key=new_key()).status_code == 201


# ===========================================================================
# Input validation / security
# ===========================================================================
@pytest.mark.parametrize("body", [
    {"user_id": 0, "concert_id": 1, "seat_id": 1},
    {"user_id": 1, "concert_id": 1, "seat_id": -5},
    {"user_id": "1; DROP TABLE bookings", "concert_id": 1, "seat_id": 1},
    {"user_id": 1, "concert_id": 1, "seat_id": 99999999999},
    {"user_id": 1, "concert_id": 1, "seat_id": 1, "status": "CONFIRMED"},   # unknown field
    {"user_id": 1, "concert_id": 1},
])
def test_invalid_input_is_rejected(stack, body):
    r = requests.post(f"{stack.booking_url}/api/bookings", json=body)
    assert r.status_code == 422
    assert stack.query("SELECT count(*) FROM bookings") == [(0,)]


def test_bad_idempotency_key_and_ids_are_rejected(stack):
    assert stack.book(1, 1, key="short").status_code == 422
    assert stack.book(1, 1, key="has spaces and ';-- chars").status_code == 422
    assert stack.get_booking("not-a-booking-id").status_code == 422


def test_unknown_references_give_404(stack):
    assert stack.book(user_id=999, seat_id=1, key=new_key()).json()["detail"] == "USER_NOT_FOUND"
    assert stack.book(user_id=1, seat_id=2_000_000_000, key=new_key()).json()["detail"] == "SEAT_NOT_FOUND"
    assert stack.book(user_id=1, seat_id=1, concert_id=999, key=new_key()).json()["detail"] == "CONCERT_NOT_FOUND"
    assert stack.query("SELECT count(*) FROM bookings") == [(0,)]
