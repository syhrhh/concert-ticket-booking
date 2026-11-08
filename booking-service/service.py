"""Booking business logic.

Booking lifecycle
-----------------
    (new) -> PENDING -> CONFIRMED -> CANCELLED
                    \\-> REJECTED   (seat taken / not found: final)
                    \\-> FAILED     (Availability unreachable: client may retry)

Control points (see README for the full explanation)
-----------------------------------------------------
* Concurrency      : partial unique index on bookings(seat_id) for active
                     bookings + atomic reservation at the Availability Service.
* Duplicate request: Idempotency-Key (UNIQUE column) claimed by the very first
                     INSERT; later requests replay the stored result.
* Partial failure  : notifications and seat releases go through the outbox, and
                     an unreachable Availability Service becomes a fast 503.

Every public function returns (http_status, json_body, extra_headers).
"""
import hashlib
import logging
import time
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from psycopg import errors

import clients
import config
import db
import outbox

log = logging.getLogger("booking.service")

Result = Tuple[int, Any, Dict[str, str]]

SEAT_INDEX = "uq_bookings_active_seat"
REPLAY = {"Idempotent-Replay": "true"}

# A rejection code is also the HTTP status the client sees.
REJECTION_HTTP_STATUS = {"SEAT_NOT_AVAILABLE": 409, "SEAT_NOT_FOUND": 404}
FK_ERRORS = {
    "bookings_user_id_fkey": "USER_NOT_FOUND",
    "bookings_concert_id_fkey": "CONCERT_NOT_FOUND",
    "bookings_seat_id_fkey": "SEAT_NOT_FOUND",
}

_SELECT = """
SELECT b.booking_id, b.user_id, b.concert_id, b.seat_id, b.status, b.failure_reason,
       b.request_hash, b.created_at, b.updated_at,
       (SELECT o.status FROM booking_outbox o WHERE o.booking_id = b.booking_id
         AND o.kind = 'NOTIFY_CONFIRMED' ORDER BY o.outbox_id DESC LIMIT 1) AS confirm_notice,
       (SELECT o.status FROM booking_outbox o WHERE o.booking_id = b.booking_id
         AND o.kind = 'NOTIFY_CANCELLED' ORDER BY o.outbox_id DESC LIMIT 1) AS cancel_notice,
       (SELECT o.status FROM booking_outbox o WHERE o.booking_id = b.booking_id
         AND o.kind = 'RELEASE_SEAT' ORDER BY o.outbox_id DESC LIMIT 1) AS release
  FROM bookings b
"""

_NOTICE = {"PENDING": "PENDING", "DONE": "SENT", "DEAD": "FAILED"}
_RELEASE = {"PENDING": "PENDING", "DONE": "RELEASED", "DEAD": "FAILED"}


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _ts(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() + "Z" if value else None


def view(row: Dict[str, Any]) -> Dict[str, Any]:
    """Public representation of a booking (no idempotency key, no hash)."""
    return {
        "booking_id": row["booking_id"],
        "user_id": row["user_id"],
        "concert_id": row["concert_id"],
        "seat_id": row["seat_id"],
        "status": row["status"],
        "failure_reason": row["failure_reason"],
        # Delivery state of side effects, so the UI can show partial failure.
        "notification_status": _NOTICE.get(row["confirm_notice"]),
        "cancellation_notification_status": _NOTICE.get(row["cancel_notice"]),
        "seat_release_status": _RELEASE.get(row["release"]),
        "created_at": _ts(row["created_at"]),
        "updated_at": _ts(row["updated_at"]),
    }


def _load(where: str, params: tuple) -> Optional[Dict[str, Any]]:
    with db.pool.connection() as conn:
        return conn.execute(_SELECT + where, params).fetchone()


def _wait_until_settled(load: Callable[[], Optional[Dict[str, Any]]]) -> Optional[Dict[str, Any]]:
    """Poll while a booking is still PENDING (i.e. another request is working on it)."""
    deadline = time.monotonic() + config.IN_FLIGHT_WAIT_SECONDS
    while True:
        row = load()
        if row is None or row["status"] != "PENDING" or time.monotonic() >= deadline:
            return row
        time.sleep(0.1)


def _in_progress() -> Result:
    return 409, {"detail": "REQUEST_IN_PROGRESS"}, {"Retry-After": "1"}


def _rejection(row: Dict[str, Any], replay: bool = False) -> Result:
    reason = row["failure_reason"] or "SEAT_NOT_AVAILABLE"
    return (REJECTION_HTTP_STATUS.get(reason, 409),
            {"detail": reason, "booking": view(row)},
            dict(REPLAY) if replay else {})


def _stored(row: Dict[str, Any]) -> Result:
    """Response for a request we have already processed (idempotent replay)."""
    if row["status"] == "REJECTED":
        return _rejection(row, replay=True)
    return 200, view(row), dict(REPLAY)


# --------------------------------------------------------------------------
# create
# --------------------------------------------------------------------------
def create_booking(user_id: int, concert_id: int, seat_id: int, key: Optional[str]) -> Result:
    request_hash = hashlib.sha256(f"{user_id}|{concert_id}|{seat_id}".encode()).hexdigest()
    booking_id = "B" + uuid.uuid4().hex[:12].upper()

    try:
        # The first INSERT is the single point that decides who "owns" the
        # idempotency key and who gets the seat. Everything else follows from it.
        with db.pool.connection() as conn:
            inserted = conn.execute(
                """
                INSERT INTO bookings (booking_id, user_id, concert_id, seat_id, status,
                                      idempotency_key, request_hash)
                VALUES (%s, %s, %s, %s, 'PENDING', %s, %s)
                ON CONFLICT (idempotency_key) DO NOTHING
                RETURNING booking_id
                """,
                (booking_id, user_id, concert_id, seat_id, key, request_hash),
            ).fetchone()
    except errors.UniqueViolation as exc:
        if exc.diag.constraint_name == SEAT_INDEX:
            return _seat_already_held(booking_id, user_id, concert_id, seat_id, key, request_hash)
        raise
    except errors.ForeignKeyViolation as exc:
        code = FK_ERRORS.get(exc.diag.constraint_name, "REFERENCE_NOT_FOUND")
        return 404, {"detail": code}, {}

    if inserted is None:  # this Idempotency-Key was used before
        return _replay(key, request_hash)

    log.info("booking %s PENDING user=%s concert=%s seat=%s", booking_id, user_id, concert_id, seat_id)
    return _process({"booking_id": booking_id, "concert_id": concert_id, "seat_id": seat_id})


def _process(b: Dict[str, Any]) -> Result:
    """Run the distributed part: reserve the seat at the Availability Service,
    then record the outcome."""
    booking_id = b["booking_id"]
    outcome = clients.reserve_seat(booking_id, b["concert_id"], b["seat_id"])

    if outcome == clients.RESERVED:
        with db.pool.connection() as conn:
            confirmed = conn.execute(
                "UPDATE bookings SET status = 'CONFIRMED', failure_reason = NULL, updated_at = now()"
                " WHERE booking_id = %s AND status = 'PENDING' RETURNING user_id",
                (booking_id,),
            ).fetchone()
            if confirmed:
                db.enqueue(conn, booking_id, outbox.NOTIFY_CONFIRMED, {
                    "booking_id": booking_id, "user_id": confirmed["user_id"],
                    "type": "BOOKING_CONFIRMED",
                    "message": f"Your ticket booking {booking_id} has been confirmed.",
                })
            else:
                # The reaper gave up on this booking while we were reserving.
                db.enqueue(conn, booking_id, outbox.RELEASE_SEAT,
                           {"concert_id": b["concert_id"], "seat_id": b["seat_id"]})
        outbox.worker.wake()
        if not confirmed:
            return 503, {"detail": "BOOKING_TIMED_OUT"}, {"Retry-After": "2"}
        log.info("booking %s CONFIRMED", booking_id)
        return 201, view(_load("WHERE b.booking_id = %s", (booking_id,))), {}

    if outcome in (clients.SEAT_TAKEN, clients.SEAT_NOT_FOUND):
        reason = "SEAT_NOT_AVAILABLE" if outcome == clients.SEAT_TAKEN else "SEAT_NOT_FOUND"
        return _reject(booking_id, reason, ("PENDING",))

    # Availability unreachable or misbehaving. The reservation may or may not
    # have been applied (e.g. read timeout), so queue a release to be safe.
    with db.pool.connection() as conn:
        conn.execute(
            "UPDATE bookings SET status = 'FAILED', failure_reason = 'AVAILABILITY_UNAVAILABLE',"
            " updated_at = now() WHERE booking_id = %s AND status = 'PENDING'",
            (booking_id,),
        )
        db.enqueue(conn, booking_id, outbox.RELEASE_SEAT,
                   {"concert_id": b["concert_id"], "seat_id": b["seat_id"]})
    outbox.worker.wake()
    log.warning("booking %s FAILED: availability service unavailable", booking_id)
    row = _load("WHERE b.booking_id = %s", (booking_id,))
    return 503, {"detail": "AVAILABILITY_SERVICE_UNAVAILABLE", "booking": view(row)}, {"Retry-After": "2"}


def _reject(booking_id: str, reason: str, from_states: Tuple[str, ...]) -> Result:
    with db.pool.connection() as conn:
        conn.execute(
            "UPDATE bookings SET status = 'REJECTED', failure_reason = %s, updated_at = now()"
            " WHERE booking_id = %s AND status = ANY(%s)",
            (reason, booking_id, list(from_states)),
        )
    log.info("booking %s REJECTED reason=%s", booking_id, reason)
    return _rejection(_load("WHERE b.booking_id = %s", (booking_id,)))


# --------------------------------------------------------------------------
# duplicate / conflicting requests
# --------------------------------------------------------------------------
def _replay(key: str, request_hash: str) -> Result:
    """Same Idempotency-Key seen before: never create a second booking."""
    row = _wait_until_settled(lambda: _load("WHERE b.idempotency_key = %s", (key,)))
    if row is None:
        return _in_progress()
    if row["request_hash"] != request_hash:
        return 422, {"detail": "IDEMPOTENCY_KEY_REUSED"}, {}
    if row["status"] == "PENDING":
        return _in_progress()
    if row["status"] == "FAILED":
        return _retry_failed(row)
    log.info("booking %s replayed for repeated Idempotency-Key", row["booking_id"])
    return _stored(row)


def _retry_failed(row: Dict[str, Any]) -> Result:
    """A technical failure is not cached: retrying with the same key re-runs it
    on the same booking record (so it can never produce a second booking)."""
    booking_id = row["booking_id"]
    with db.pool.connection() as conn:
        releasing = conn.execute(
            "SELECT 1 FROM booking_outbox WHERE booking_id = %s AND kind = 'RELEASE_SEAT'"
            " AND status = 'PENDING' LIMIT 1", (booking_id,),
        ).fetchone()
    if releasing:  # don't re-reserve while the previous attempt is being undone
        return 503, {"detail": "RECOVERY_IN_PROGRESS", "booking": view(row)}, {"Retry-After": "2"}

    try:
        with db.pool.connection() as conn:
            claimed = conn.execute(
                "UPDATE bookings SET status = 'PENDING', failure_reason = NULL, updated_at = now()"
                " WHERE booking_id = %s AND status = 'FAILED' RETURNING booking_id", (booking_id,),
            ).fetchone()
    except errors.UniqueViolation:  # someone else took the seat meanwhile
        return _reject(booking_id, "SEAT_NOT_AVAILABLE", ("FAILED",))
    if claimed is None:  # another retry already picked it up
        return _in_progress()
    log.info("booking %s retried after failure", booking_id)
    return _process(row)


def _seat_already_held(booking_id: str, user_id: int, concert_id: int, seat_id: int,
                       key: Optional[str], request_hash: str) -> Result:
    """The database refused a second active booking for this seat."""
    holder = _load("WHERE b.seat_id = %s AND b.status IN ('PENDING', 'CONFIRMED')", (seat_id,))

    if holder and holder["user_id"] == user_id and holder["concert_id"] == concert_id:
        # The same user is asking again (lost response, double click, missing
        # key): answer with their existing booking instead of an error.
        holder = _wait_until_settled(lambda: _load("WHERE b.booking_id = %s", (holder["booking_id"],))) or holder
        log.info("booking %s returned for repeated request by same user", holder["booking_id"])
        return 200, view(holder), dict(REPLAY)

    # A different user holds the seat. Store the rejection (so the request is
    # recorded and a retry with the same key gets the same answer).
    with db.pool.connection() as conn:
        stored = conn.execute(
            """
            INSERT INTO bookings (booking_id, user_id, concert_id, seat_id, status, failure_reason,
                                  idempotency_key, request_hash)
            VALUES (%s, %s, %s, %s, 'REJECTED', 'SEAT_NOT_AVAILABLE', %s, %s)
            ON CONFLICT (idempotency_key) DO NOTHING
            RETURNING booking_id
            """,
            (booking_id, user_id, concert_id, seat_id, key, request_hash),
        ).fetchone()
    if stored is None:
        return _replay(key, request_hash)
    log.info("booking %s REJECTED reason=SEAT_NOT_AVAILABLE (seat %s already held)", booking_id, seat_id)
    return _rejection(_load("WHERE b.booking_id = %s", (booking_id,)))


# --------------------------------------------------------------------------
# read / cancel
# --------------------------------------------------------------------------
def get_booking(booking_id: str) -> Result:
    row = _load("WHERE b.booking_id = %s", (booking_id,))
    if row is None:
        return 404, {"detail": "BOOKING_NOT_FOUND"}, {}
    return 200, view(row), {}


def list_user_bookings(user_id: int) -> Result:
    with db.pool.connection() as conn:
        rows: List[Dict[str, Any]] = conn.execute(
            _SELECT + "WHERE b.user_id = %s ORDER BY b.created_at DESC, b.booking_id LIMIT 100", (user_id,)
        ).fetchall()
    return 200, [view(r) for r in rows], {}


def cancel_booking(booking_id: str, user_id: int) -> Result:
    """Cancel is a state change plus two outbox rows, committed atomically.
    The seat is released (and the user notified) by the worker, with retries,
    so a cancel still succeeds if Availability or Notification is down."""
    with db.pool.connection() as conn:
        row = conn.execute(
            "SELECT booking_id, user_id, concert_id, seat_id, status FROM bookings"
            " WHERE booking_id = %s FOR UPDATE", (booking_id,),
        ).fetchone()
        if row is None:
            return 404, {"detail": "BOOKING_NOT_FOUND"}, {}
        if row["user_id"] != user_id:
            return 403, {"detail": "NOT_BOOKING_OWNER"}, {}
        if row["status"] == "CANCELLED":
            changed = False  # cancelling twice is harmless (idempotent)
        elif row["status"] != "CONFIRMED":
            return 409, {"detail": "BOOKING_NOT_CANCELLABLE", "status": row["status"]}, {}
        else:
            conn.execute("UPDATE bookings SET status = 'CANCELLED', updated_at = now()"
                         " WHERE booking_id = %s", (booking_id,))
            db.enqueue(conn, booking_id, outbox.RELEASE_SEAT,
                       {"concert_id": row["concert_id"], "seat_id": row["seat_id"]})
            db.enqueue(conn, booking_id, outbox.NOTIFY_CANCELLED, {
                "booking_id": booking_id, "user_id": user_id, "type": "BOOKING_CANCELLED",
                "message": f"Your ticket booking {booking_id} has been cancelled.",
            })
            changed = True
    if changed:
        outbox.worker.wake()
        log.info("booking %s CANCELLED", booking_id)
    return 200, view(_load("WHERE b.booking_id = %s", (booking_id,))), {}
