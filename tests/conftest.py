"""Integration-test harness for the booking workflow.

The tests start the *real* services as separate OS processes on private ports
(booking 15001, availability 15002, notification 15003), talking to a throw-away
PostgreSQL database, so they exercise the same network paths as the real system
without touching the development stack on ports 5001-5003.

Requirements: a running PostgreSQL whose user may create databases (the one from
docker-compose does) and `pip install -r tests/requirements.txt`.
Service logs are written to tests/logs/ and can be used as report evidence.
"""
import os
import pathlib
import subprocess
import sys
import time
from typing import Callable, Dict, Optional

import psycopg
import pytest
import requests

ROOT = pathlib.Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "tests" / "logs"

ADMIN_URL = os.getenv("TEST_ADMIN_DATABASE_URL",
                      "postgresql://concert_user:concert_pass@localhost:5432/postgres")
TEST_DB = "concert_booking_test"
TEST_DB_URL = ADMIN_URL.rsplit("/", 1)[0] + "/" + TEST_DB

PORTS = {"booking": 15001, "availability": 15002, "notification": 15003}
URLS = {name: f"http://127.0.0.1:{port}" for name, port in PORTS.items()}
FOLDERS = {"booking": "booking-service", "availability": "availability-service",
           "notification": "notification-service"}


class ManagedService:
    """One service running as its own OS process; can be stopped and restarted
    to simulate a crash / partial failure."""

    def __init__(self, name: str, env: Optional[Dict[str, str]] = None):
        self.name = name
        self.env = {**os.environ, **(env or {})}
        self.proc: Optional[subprocess.Popen] = None

    def start(self, wait: bool = True) -> None:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        log = open(LOG_DIR / f"{self.name}-service.log", "ab")
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1",
             "--port", str(PORTS[self.name]), "--log-level", "info"],
            cwd=ROOT / FOLDERS[self.name], env=self.env, stdout=log, stderr=subprocess.STDOUT,
        )
        if wait:
            self.wait_ready()

    def wait_ready(self, timeout: float = 20) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"{self.name} service exited early; see tests/logs/")
            try:
                if requests.get(URLS[self.name] + "/health", timeout=1).status_code == 200:
                    return
            except requests.RequestException:
                time.sleep(0.2)
        raise RuntimeError(f"{self.name} service did not become ready")

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None


def wait_until(check: Callable[[], object], timeout: float = 15, interval: float = 0.2, what: str = "condition"):
    """Poll until check() returns something truthy and return it."""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = check()
        if last:
            return last
        time.sleep(interval)
    raise AssertionError(f"timed out after {timeout}s waiting for {what} (last value: {last!r})")


class Stack:
    """Convenience wrapper the tests use to talk to the running system."""

    def __init__(self, services: Dict[str, ManagedService]):
        self.services = services
        self.booking_url = URLS["booking"]

    # --- service control --------------------------------------------------
    def stop(self, name: str) -> None:
        self.services[name].stop()

    def start(self, name: str) -> None:
        self.services[name].start()

    # --- booking API ------------------------------------------------------
    def book(self, user_id: int, seat_id: int, key: Optional[str] = None, concert_id: int = 1,
             **extra) -> requests.Response:
        headers = {"Idempotency-Key": key} if key else {}
        body = {"user_id": user_id, "concert_id": concert_id, "seat_id": seat_id, **extra}
        return requests.post(f"{self.booking_url}/api/bookings", json=body, headers=headers, timeout=15)

    def get_booking(self, booking_id: str) -> requests.Response:
        return requests.get(f"{self.booking_url}/api/bookings/{booking_id}", timeout=10)

    def cancel(self, booking_id: str, user_id: int) -> requests.Response:
        return requests.delete(f"{self.booking_url}/api/bookings/{booking_id}",
                               params={"user_id": user_id}, timeout=10)

    # --- other components (to verify effects across services) --------------
    def seat_status(self, seat_id: int, concert_id: int = 1) -> str:
        seats = requests.get(f"{URLS['availability']}/api/concerts/{concert_id}/seats", timeout=5).json()
        return next(s["status"] for s in seats if s["seat_id"] == seat_id)

    def notifications(self, user_id: int) -> list:
        return requests.get(f"{URLS['notification']}/api/users/{user_id}/notifications", timeout=5).json()

    def query(self, sql: str, params: tuple = ()):
        with psycopg.connect(TEST_DB_URL, autocommit=True) as conn:
            cur = conn.execute(sql, params)
            return cur.fetchall() if cur.description else []


def _reset_database() -> None:
    with psycopg.connect(TEST_DB_URL, autocommit=True) as conn:
        conn.execute("TRUNCATE booking_outbox, bookings, reservations, notifications RESTART IDENTITY CASCADE")
        conn.execute("UPDATE seats SET status = 'AVAILABLE'")


@pytest.fixture(scope="session")
def database():
    """A fresh database built from the team's database/init.sql."""
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
        admin.execute(f"CREATE DATABASE {TEST_DB}")
    with psycopg.connect(TEST_DB_URL, autocommit=True) as conn:
        conn.execute((ROOT / "database" / "init.sql").read_text())
    yield TEST_DB_URL
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")


@pytest.fixture(scope="session")
def booking_service(database):
    if LOG_DIR.exists():
        for old in LOG_DIR.glob("*-service.log"):
            old.unlink()
    svc = ManagedService("booking", {
        "DATABASE_URL": database,
        "AVAILABILITY_URL": URLS["availability"],
        "NOTIFICATION_URL": URLS["notification"],
        "SEED_DEMO_DATA": "true",
        # Faster timings so failure/recovery tests finish quickly.
        "OUTBOX_MAX_BACKOFF_SECONDS": "2",
        "PENDING_TIMEOUT_SECONDS": "4",
        "IN_FLIGHT_WAIT_SECONDS": "5",
    })
    svc.start()
    yield svc
    svc.stop()


@pytest.fixture
def stack(booking_service):
    """Fresh availability + notification processes and an empty database for
    every test; the booking service stays up between tests."""
    _reset_database()
    services = {
        "booking": booking_service,
        # The database-backed Availability Service uses SQLAlchemy, which wants
        # the driver named in the URL (postgresql+psycopg://).
        "availability": ManagedService("availability", {
            "DATABASE_URL": TEST_DB_URL.replace("postgresql://", "postgresql+psycopg://", 1)}),
        "notification": ManagedService("notification", {"DATABASE_URL": TEST_DB_URL}),
    }
    services["availability"].start(wait=False)
    services["notification"].start(wait=False)
    services["availability"].wait_ready()
    services["notification"].wait_ready()
    yield Stack(services)
    services["availability"].stop()
    services["notification"].stop()
