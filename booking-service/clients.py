"""HTTP clients for the services the Booking Service depends on.

Every call has an explicit timeout. Failures are reported as values/exceptions
so callers decide how to degrade (fast 503, retry later, ...).
"""
import logging
from typing import Any, Dict

import requests

import config

log = logging.getLogger("booking.clients")

# Outcomes of a seat reservation attempt.
RESERVED = "RESERVED"
SEAT_TAKEN = "SEAT_TAKEN"
SEAT_NOT_FOUND = "SEAT_NOT_FOUND"
UNAVAILABLE = "UNAVAILABLE"  # timeout, connection error or unexpected response


class DeliveryError(Exception):
    """A background delivery (notification / seat release) failed; retry later."""


def reserve_seat(booking_id: str, concert_id: int, seat_id: int) -> str:
    """Ask the Availability Service to reserve a seat for this booking.

    The booking must already exist as PENDING in the shared database (we insert
    it first). booking_id makes the call idempotent and ties the reservation
    to the booking.
    """
    try:
        resp = requests.post(
            f"{config.AVAILABILITY_URL}/api/reservations",
            json={"concert_id": concert_id, "seat_id": seat_id, "booking_id": booking_id},
            timeout=config.AVAILABILITY_TIMEOUT,
        )
    except requests.RequestException as exc:
        log.warning("availability unreachable booking=%s error=%s", booking_id, type(exc).__name__)
        return UNAVAILABLE

    code = _error_code(resp)
    if resp.status_code == 200:
        return RESERVED
    if resp.status_code == 409 and code != "INVALID_BOOKING_STATE":
        return SEAT_TAKEN
    if resp.status_code == 404 and code != "BOOKING_NOT_FOUND":
        return SEAT_NOT_FOUND
    # Anything else (including a booking the Availability Service cannot see
    # or does not accept) is a technical failure, not a verdict on the seat.
    log.warning("availability unexpected status=%s code=%s booking=%s", resp.status_code, code, booking_id)
    return UNAVAILABLE


def _error_code(resp: requests.Response) -> str:
    """Availability reports errors as JSON with an error_code field."""
    try:
        return str(resp.json().get("error_code", ""))
    except (ValueError, AttributeError):
        return ""


def release_seat(booking_id: str) -> None:
    """Release the seat owned by this booking.

    The Availability Service releases by booking id and answers 200 even when
    there is nothing left to release, so only a 2xx counts as success. A 404 is
    NOT treated as success: it would hide a wrong URL or an unknown booking and
    leave the seat locked.
    """
    try:
        resp = requests.delete(
            f"{config.AVAILABILITY_URL}/api/reservations/{booking_id}",
            timeout=config.NOTIFICATION_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise DeliveryError(type(exc).__name__) from exc
    if not 200 <= resp.status_code < 300:
        raise DeliveryError(f"availability returned {resp.status_code}")


def send_notification(booking_id: str, kind: str, payload: Dict[str, Any]) -> None:
    """Deliver one notification. The Idempotency-Key lets the Notification
    Service ignore a re-delivery if our first attempt succeeded but the
    response was lost (the outbox gives at-least-once delivery)."""
    try:
        resp = requests.post(
            f"{config.NOTIFICATION_URL}/api/notifications",
            json=payload,
            headers={"Idempotency-Key": f"{booking_id}:{kind}"},
            timeout=config.NOTIFICATION_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise DeliveryError(type(exc).__name__) from exc
    if not 200 <= resp.status_code < 300:
        raise DeliveryError(f"notification returned {resp.status_code}")


def probe(base_url: str) -> str:
    """Health probe used by /health/dependencies."""
    try:
        resp = requests.get(f"{base_url}/health", timeout=(1.0, 1.0))
        return "UP" if resp.status_code == 200 else "DOWN"
    except requests.RequestException:
        return "DOWN"
