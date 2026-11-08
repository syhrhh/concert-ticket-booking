"""Runtime configuration for the Booking Service.

Everything is read from environment variables so the same code runs locally,
in tests and in containers. Defaults match the ports in the project README.
"""
import os


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, default))


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, default))


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


# --- Infrastructure -------------------------------------------------------
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://concert_user:concert_pass@localhost:5432/concert_booking",
)
AVAILABILITY_URL = os.getenv("AVAILABILITY_URL", "http://localhost:5002").rstrip("/")
NOTIFICATION_URL = os.getenv("NOTIFICATION_URL", "http://localhost:5003").rstrip("/")

DB_POOL_MAX = _int("DB_POOL_MAX", 20)
DB_CONNECT_TIMEOUT = _float("DB_CONNECT_TIMEOUT", 30)

# Insert demo users / concert / seats at start-up (development and tests only).
SEED_DEMO_DATA = _bool("SEED_DEMO_DATA", False)

# Browser origins allowed to call this API (the React dev server).
CORS_ORIGINS = [
    o.strip()
    for o in os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",")
    if o.strip()
]

# --- Synchronous calls on the booking request path -------------------------
# (connect timeout, read timeout) in seconds. Kept short so a slow or dead
# Availability Service turns into a fast 503 instead of a hanging request.
AVAILABILITY_TIMEOUT = (_float("AVAILABILITY_CONNECT_TIMEOUT", 1.0), _float("AVAILABILITY_READ_TIMEOUT", 3.0))
# Used by the background worker (notifications, seat release).
NOTIFICATION_TIMEOUT = (_float("NOTIFICATION_CONNECT_TIMEOUT", 1.0), _float("NOTIFICATION_READ_TIMEOUT", 2.0))

# --- Idempotency -----------------------------------------------------------
# How long a duplicate request waits for the original, still-running request.
IN_FLIGHT_WAIT_SECONDS = _float("IN_FLIGHT_WAIT_SECONDS", 5)
# A booking stuck in PENDING longer than this (e.g. the service crashed
# mid-request) is marked FAILED and its seat reservation is released.
PENDING_TIMEOUT_SECONDS = _float("PENDING_TIMEOUT_SECONDS", 30)

# --- Outbox worker (reliable notification + seat release) ------------------
OUTBOX_POLL_SECONDS = _float("OUTBOX_POLL_SECONDS", 1.0)
OUTBOX_BATCH_SIZE = _int("OUTBOX_BATCH_SIZE", 10)
OUTBOX_LEASE_SECONDS = _float("OUTBOX_LEASE_SECONDS", 30)
OUTBOX_MAX_ATTEMPTS = _int("OUTBOX_MAX_ATTEMPTS", 30)
OUTBOX_MAX_BACKOFF_SECONDS = _float("OUTBOX_MAX_BACKOFF_SECONDS", 10)
