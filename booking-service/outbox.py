"""Background worker: reliable delivery of side effects (outbox pattern).

The booking request path never calls the Notification Service directly. It
writes an outbox row in the same transaction as the booking change; this worker
delivers it. That is what keeps booking usable while Notification is down, and
what makes recovery automatic once it is back.

Per row:   PENDING --(success)--> DONE
           PENDING --(failure)--> PENDING, retried with exponential back-off
           PENDING --(too many failures)--> DEAD   (needs manual attention)

Delivery is at-least-once. Several Booking Service instances can run this
worker at once: rows are claimed with FOR UPDATE SKIP LOCKED + a short lease.
"""
import logging
import threading
import time
from typing import Any, Dict

import clients
import config
import db

log = logging.getLogger("booking.outbox")

NOTIFY_CONFIRMED = "NOTIFY_CONFIRMED"
NOTIFY_CANCELLED = "NOTIFY_CANCELLED"
RELEASE_SEAT = "RELEASE_SEAT"


class OutboxWorker:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread = threading.Thread(target=self._run, name="outbox-worker", daemon=True)

    def start(self) -> None:
        self._thread.start()
        log.info("outbox worker started")

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        self._thread.join(timeout=5)

    def wake(self) -> None:
        """Deliver new work immediately instead of waiting for the next poll."""
        self._wake.set()

    # ------------------------------------------------------------------
    def _run(self) -> None:
        last_reap = 0.0
        while not self._stop.is_set():
            try:
                if time.monotonic() - last_reap >= 5:
                    self._reap_stale_pending()
                    last_reap = time.monotonic()
                handled = self._process_batch()
                if handled >= config.OUTBOX_BATCH_SIZE:
                    continue  # more work is probably waiting
            except Exception:  # noqa: BLE001 - e.g. database briefly down; keep looping
                log.exception("outbox loop error")
            self._wake.wait(config.OUTBOX_POLL_SECONDS)
            self._wake.clear()

    def _reap_stale_pending(self) -> None:
        """Recover bookings left PENDING by a crash: mark them FAILED and
        release whatever seat reservation may have been made for them."""
        with db.pool.connection() as conn:
            rows = conn.execute(
                """
                UPDATE bookings
                   SET status = 'FAILED', failure_reason = 'STALE_PENDING', updated_at = now()
                 WHERE status = 'PENDING'
                   AND updated_at < now() - make_interval(secs => %s)
             RETURNING booking_id, concert_id, seat_id
                """,
                (config.PENDING_TIMEOUT_SECONDS,),
            ).fetchall()
            for r in rows:
                db.enqueue(conn, r["booking_id"], RELEASE_SEAT,
                           {"concert_id": r["concert_id"], "seat_id": r["seat_id"]})
        if rows:
            log.warning("reaped %d stale PENDING booking(s): %s", len(rows),
                        ", ".join(r["booking_id"] for r in rows))

    def _claim_batch(self):
        """Claim due rows by pushing next_attempt_at forward (a lease). If this
        process dies mid-delivery the row simply becomes due again."""
        with db.pool.connection() as conn:
            return conn.execute(
                """
                UPDATE booking_outbox
                   SET next_attempt_at = now() + make_interval(secs => %s), updated_at = now()
                 WHERE outbox_id IN (
                        SELECT outbox_id FROM booking_outbox
                         WHERE status = 'PENDING' AND next_attempt_at <= now()
                         ORDER BY outbox_id
                         LIMIT %s
                           FOR UPDATE SKIP LOCKED)
             RETURNING outbox_id, booking_id, kind, payload, attempts
                """,
                (config.OUTBOX_LEASE_SECONDS, config.OUTBOX_BATCH_SIZE),
            ).fetchall()

    def _process_batch(self) -> int:
        items = self._claim_batch()
        for item in items:
            self._deliver(item)
        return len(items)

    def _deliver(self, item: Dict[str, Any]) -> None:
        attempt = item["attempts"] + 1
        try:
            self._dispatch(item)
        except clients.DeliveryError as exc:
            self._record_failure(item, attempt, str(exc))
        else:
            with db.pool.connection() as conn:
                conn.execute(
                    "UPDATE booking_outbox SET status = 'DONE', attempts = %s, last_error = NULL,"
                    " updated_at = now() WHERE outbox_id = %s",
                    (attempt, item["outbox_id"]),
                )
            log.info("outbox DONE id=%s kind=%s booking=%s attempt=%d",
                     item["outbox_id"], item["kind"], item["booking_id"], attempt)

    @staticmethod
    def _dispatch(item: Dict[str, Any]) -> None:
        kind, payload = item["kind"], item["payload"]
        if kind in (NOTIFY_CONFIRMED, NOTIFY_CANCELLED):
            clients.send_notification(item["booking_id"], kind, payload)
        elif kind == RELEASE_SEAT:
            clients.release_seat(item["booking_id"])
        else:
            raise clients.DeliveryError(f"unknown outbox kind {kind}")

    @staticmethod
    def _record_failure(item: Dict[str, Any], attempt: int, error: str) -> None:
        dead = attempt >= config.OUTBOX_MAX_ATTEMPTS
        delay = min(2 ** (attempt - 1), config.OUTBOX_MAX_BACKOFF_SECONDS)
        with db.pool.connection() as conn:
            conn.execute(
                """
                UPDATE booking_outbox
                   SET status = %s, attempts = %s, last_error = %s, updated_at = now(),
                       next_attempt_at = now() + make_interval(secs => %s)
                 WHERE outbox_id = %s
                """,
                ("DEAD" if dead else "PENDING", attempt, error[:200], delay, item["outbox_id"]),
            )
        if dead:
            log.error("outbox DEAD id=%s kind=%s booking=%s after %d attempts (%s) - needs manual action",
                      item["outbox_id"], item["kind"], item["booking_id"], attempt, error)
        else:
            log.warning("outbox RETRY id=%s kind=%s booking=%s attempt=%d error=%s next_try_in=%ss",
                        item["outbox_id"], item["kind"], item["booking_id"], attempt, error, delay)


worker = OutboxWorker()
