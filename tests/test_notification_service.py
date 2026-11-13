"""Tests for the Notification Service (port 5003) on its own.

Like the booking tests, this starts the REAL service as a separate process
(port 15003) against the throw-away test database built from database/init.sql.

    pytest tests/test_notification_service.py -v

What is proven
    1. A notification is stored in PostgreSQL and can be read back.
    2. A retried delivery (same Idempotency-Key) never creates a second notification,
       even when 10 copies arrive at the same moment.
    3. Notifications survive a restart (they are not kept in memory).
    4. Invalid or malicious input is rejected before it reaches the database.
    5. Users only see their own notifications.
    6. The demo fault modes behave as documented.
"""
import threading

import pytest
import requests

from conftest import URLS, ManagedService, wait_until

BASE = URLS["notification"]


def payload(booking_id="B0000000000A1", user_id=1, kind="BOOKING_CONFIRMED", message=None):
    return {"booking_id": booking_id, "user_id": user_id, "type": kind,
            "message": f"Your ticket booking {booking_id} has been confirmed." if message is None else message}


def send(body, key=None):
    headers = {"Idempotency-Key": key} if key else {}
    return requests.post(f"{BASE}/api/notifications", json=body, headers=headers, timeout=10)


def mine(user_id):
    return requests.get(f"{BASE}/api/users/{user_id}/notifications", timeout=5).json()


@pytest.fixture
def notification(database):
    """A fresh Notification Service process and an empty notifications table."""
    import psycopg
    svc = ManagedService("notification", {"DATABASE_URL": database})
    svc.start()
    with psycopg.connect(database, autocommit=True) as conn:
        conn.execute("TRUNCATE notifications RESTART IDENTITY")
    yield svc
    svc.stop()


def count_rows(database):
    import psycopg
    with psycopg.connect(database, autocommit=True) as conn:
        return conn.execute("SELECT count(*) FROM notifications").fetchone()[0]


# ---------------------------------------------------------------------------
def test_health_reports_database(notification):
    r = requests.get(f"{BASE}/health", timeout=5)
    assert r.status_code == 200
    assert r.json() == {"service": "notification", "status": "UP", "database": "UP"}


def test_notification_is_stored_and_listed(notification, database):
    r = send(payload(), key="B0000000000A1:NOTIFY_CONFIRMED")
    assert r.status_code == 201
    created = r.json()
    assert created["status"] == "SENT" and created["type"] == "BOOKING_CONFIRMED"
    assert count_rows(database) == 1

    listed = mine(1)
    assert [n["notification_id"] for n in listed] == [created["notification_id"]]
    assert set(listed[0]) == {"notification_id", "booking_id", "user_id", "type",
                              "message", "status", "created_at"}


def test_retry_with_same_key_returns_original(notification, database):
    key = "B0000000000A1:NOTIFY_CONFIRMED"
    first = send(payload(), key=key)
    second = send(payload(), key=key)
    assert first.status_code == 201
    assert second.status_code == 200
    assert second.headers.get("Idempotent-Replay") == "true"
    assert second.json()["notification_id"] == first.json()["notification_id"]
    assert count_rows(database) == 1


def test_ten_simultaneous_copies_create_one_notification(notification, database):
    key, codes = "B0000000000B2:NOTIFY_CONFIRMED", []
    barrier = threading.Barrier(10)

    def deliver():
        barrier.wait()
        codes.append(send(payload("B0000000000B2"), key=key).status_code)

    threads = [threading.Thread(target=deliver) for _ in range(10)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(codes) == [200] * 9 + [201]
    assert count_rows(database) == 1


def test_same_key_for_a_different_message_is_refused(notification, database):
    send(payload("B0000000000A1"), key="B0000000000A1:NOTIFY_CONFIRMED")
    r = send(payload("B0000000000A2"), key="B0000000000A1:NOTIFY_CONFIRMED")
    assert r.status_code == 422 and r.json()["detail"] == "IDEMPOTENCY_KEY_REUSED"
    assert count_rows(database) == 1


def test_confirmation_and_cancellation_are_separate_notifications(notification):
    send(payload(), key="B0000000000A1:NOTIFY_CONFIRMED")
    send(payload(kind="BOOKING_CANCELLED", message="Your ticket booking B0000000000A1 has been cancelled."),
         key="B0000000000A1:NOTIFY_CANCELLED")
    assert [n["type"] for n in mine(1)] == ["BOOKING_CONFIRMED", "BOOKING_CANCELLED"]


def test_notifications_survive_a_restart(notification):
    send(payload(), key="B0000000000A1:NOTIFY_CONFIRMED")
    notification.stop()                       # service crashes / is switched off
    notification.start()                      # ...and comes back
    assert len(mine(1)) == 1                  # nothing was lost


def test_users_only_see_their_own_notifications(notification):
    send(payload("B0000000000A1", user_id=1), key="B0000000000A1:NOTIFY_CONFIRMED")
    send(payload("B0000000000A2", user_id=2), key="B0000000000A2:NOTIFY_CONFIRMED")
    assert [n["booking_id"] for n in mine(1)] == ["B0000000000A1"]
    assert [n["booking_id"] for n in mine(2)] == ["B0000000000A2"]
    assert mine(3) == []


@pytest.mark.parametrize("body", [
    payload(kind="SPAM"),                                    # unknown type
    payload(user_id=0),                                      # not a valid user id
    payload(user_id=99_999_999_999),                         # too big for INTEGER
    payload(booking_id="B1'; DROP TABLE notifications;--"),  # SQL injection attempt
    payload(message=""),                                     # empty message
    payload(message="x" * 501),                              # too long
    {**payload(), "status": "FAILED"},                       # unknown field
    {"user_id": 1, "type": "BOOKING_CONFIRMED"},             # missing fields
])
def test_invalid_input_is_rejected(notification, database, body):
    r = send(body, key="B0000000000A1:NOTIFY_CONFIRMED")
    assert r.status_code == 422 and r.json()["detail"] == "INVALID_REQUEST"
    assert count_rows(database) == 0


def test_bad_idempotency_key_and_user_id_are_rejected(notification):
    assert send(payload(), key="short").status_code == 422
    assert send(payload(), key="has spaces;--").status_code == 422
    assert requests.get(f"{BASE}/api/users/0/notifications", timeout=5).status_code == 422
    assert requests.get(f"{BASE}/api/users/abc/notifications", timeout=5).status_code == 422


def test_fault_mode_error_returns_503_and_stores_nothing(database):
    import psycopg
    with psycopg.connect(database, autocommit=True) as conn:
        conn.execute("TRUNCATE notifications RESTART IDENTITY")
    svc = ManagedService("notification", {"DATABASE_URL": database, "FAULT_MODE": "error"})
    svc.start()
    try:
        r = send(payload(), key="B0000000000A1:NOTIFY_CONFIRMED")
        assert r.status_code == 503
        assert count_rows(database) == 0
    finally:
        svc.stop()


def test_fault_mode_slow_saves_first_then_replies_late(database):
    """Simulates a lost/late reply: the caller times out, but the notification is
    already stored, so the caller's retry must be recognised as a duplicate."""
    import psycopg
    with psycopg.connect(database, autocommit=True) as conn:
        conn.execute("TRUNCATE notifications RESTART IDENTITY")
    svc = ManagedService("notification", {"DATABASE_URL": database, "FAULT_MODE": "slow",
                                           "FAULT_DELAY_SECONDS": "3"})
    svc.start()
    try:
        key = "B0000000000A1:NOTIFY_CONFIRMED"
        with pytest.raises(requests.Timeout):          # like the Booking Service's 2 s timeout
            requests.post(f"{BASE}/api/notifications", json=payload(),
                          headers={"Idempotency-Key": key}, timeout=1)
        wait_until(lambda: count_rows(database) == 1, what="notification stored despite timeout")
        retry = requests.post(f"{BASE}/api/notifications", json=payload(),
                              headers={"Idempotency-Key": key}, timeout=10)
        assert retry.status_code == 200 and retry.headers.get("Idempotent-Replay") == "true"
        assert count_rows(database) == 1               # the retry did not duplicate it
    finally:
        svc.stop()
