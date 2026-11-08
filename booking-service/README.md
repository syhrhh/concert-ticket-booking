# Booking Service

FastAPI service on **port 5001**. It creates, views and cancels bookings, keeps the
booking records in PostgreSQL, and coordinates with the **Availability Service**
(5002, synchronous REST) and the **Notification Service** (5003, asynchronous via an
outbox) over HTTP/JSON.

## Run it

```bash
# 1. PostgreSQL (from the repo root)
docker compose up -d postgres

# 2. This service
cd booking-service
pip install -r requirements.txt
SEED_DEMO_DATA=true uvicorn main:app --port 5001 --reload
```

`SEED_DEMO_DATA=true` inserts demo users 1-10, concert 1 and seats 1-3 (the seats the
Availability Service currently exposes). Leave it off once real data exists.
On start-up the service applies `sql/001_booking_schema.sql` (additive and repeatable; it
never edits `database/init.sql`).

| Environment variable | Default |
|---|---|
| `DATABASE_URL` | `postgresql://concert_user:concert_pass@localhost:5432/concert_booking` |
| `AVAILABILITY_URL` / `NOTIFICATION_URL` | `http://localhost:5002` / `http://localhost:5003` |
| `CORS_ORIGINS` | `http://localhost:3000,http://localhost:5173` |
| timeouts, retry and recovery settings | see `config.py` |

## API

| Method & path | Purpose | Success | Errors |
|---|---|---|---|
| `POST /api/bookings` | Create booking. Body `{user_id, concert_id, seat_id}`; header `Idempotency-Key` | `201` new, `200` replay (`Idempotent-Replay: true`) | `409 SEAT_NOT_AVAILABLE`, `404 USER_NOT_FOUND / CONCERT_NOT_FOUND / SEAT_NOT_FOUND`, `422` invalid input or `IDEMPOTENCY_KEY_REUSED`, `409 REQUEST_IN_PROGRESS`, `503 AVAILABILITY_SERVICE_UNAVAILABLE / RECOVERY_IN_PROGRESS` (+`Retry-After`) |
| `GET /api/bookings/{booking_id}` | View one booking | `200` | `404 BOOKING_NOT_FOUND` |
| `GET /api/users/{user_id}/bookings` | View a user's bookings (latest 100) | `200` list | |
| `DELETE /api/bookings/{booking_id}?user_id=` | Cancel (owner only; repeat is harmless) | `200` | `403 NOT_BOOKING_OWNER`, `404`, `409 BOOKING_NOT_CANCELLABLE` |
| `GET /health` | Liveness + database | `200` | `503` if DB down |
| `GET /health/dependencies` | Availability / Notification status and queued work | `200` | |

Booking object: `booking_id, user_id, concert_id, seat_id, status, failure_reason,
notification_status, cancellation_notification_status, seat_release_status, created_at,
updated_at`. Interactive docs: <http://localhost:5001/docs>.

## Booking states

```
          reserve OK                      cancel
PENDING ───────────────▶ CONFIRMED ─────────────▶ CANCELLED
   │ seat taken / not found
   ├─────────────────────▶ REJECTED   (final; stored)
   │ Availability unreachable
   └─────────────────────▶ FAILED     (retry with the same Idempotency-Key)
```

## Sequence: successful booking

```mermaid
sequenceDiagram
    participant C as Client (3000)
    participant B as Booking Service (5001)
    participant D as PostgreSQL (5432)
    participant A as Availability Service (5002)
    participant W as Outbox worker (in Booking)
    participant N as Notification Service (5003)
    C->>B: POST /api/bookings (Idempotency-Key)
    B->>D: INSERT booking PENDING (unique key + unique active seat)
    B->>A: POST /api/reservations {concert, seat, booking_id}
    A-->>B: 200 RESERVED
    B->>D: UPDATE CONFIRMED + INSERT outbox NOTIFY_CONFIRMED (one transaction)
    B-->>C: 201 CONFIRMED
    W->>D: claim due outbox rows
    W->>N: POST /api/notifications
    N-->>W: 200
    W->>D: outbox row DONE
```

## How each distributed behaviour is handled

| Behaviour | Mechanism | Where |
|---|---|---|
| **No double booking** | (1) PostgreSQL partial unique index `uq_bookings_active_seat` allows one `PENDING/CONFIRMED` booking per seat, so exactly one concurrent INSERT wins even across several Booking instances. (2) The Availability Service's atomic reservation is the authority for inventory. | `sql/001_booking_schema.sql`, `service._seat_already_held` |
| **Duplicate requests** | `Idempotency-Key` is a UNIQUE column claimed by the first INSERT (`ON CONFLICT DO NOTHING`). A repeat returns the stored result (`200` + `Idempotent-Replay`); a concurrent duplicate waits for the original. Same key + different body = `422`. Without a key, the same user asking for the seat they already hold gets their existing booking. | `service.create_booking`, `service._replay` |
| **Partial failure: Notification down** | The request path never calls Notification. The confirmation is an outbox row committed with the booking; a worker delivers it with timeouts, exponential back-off (1s, 2s, 4s... capped) and gives up as `DEAD` after `OUTBOX_MAX_ATTEMPTS`. Booking, viewing and cancelling continue. | `outbox.py` |
| **Partial failure: Availability down** | Short timeouts, then `503` with `Retry-After`; booking is stored as `FAILED`, a seat release is queued (the reservation may have been applied before the timeout), and a retry with the same key re-runs the same record. | `service._process`, `_retry_failed` |
| **Crash mid-request** | A booking stuck `PENDING` past `PENDING_TIMEOUT_SECONDS` is marked `FAILED` and its seat released by the worker. | `outbox._reap_stale_pending` |
| **Cancel** | State change + seat-release + notification rows committed atomically; the worker finishes them even if a service is down. | `service.cancel_booking` |
| **Security** | Strict request schema (`extra=forbid`, positive 32-bit ints), regex-checked ids and idempotency keys, parameterised SQL only, owner check on cancel, generic `500` body (no internals), no personal data in logs, credentials from environment, CORS limited to known origins. | `main.py` |
| **Scalability** | The service holds no state in memory: add instances behind a load balancer. The database enforces correctness, outbox rows are claimed with `FOR UPDATE SKIP LOCKED` so workers on different instances do not double-send, and the pool is configurable. | `db.py`, `outbox.py` |

## Trade-offs and limitations (for the report)

* **Eventual consistency after cancel/failure:** the seat is released by the worker (about a second), so re-booking immediately after cancelling can briefly be rejected.
* **Early rejection:** a second user is rejected as soon as the first holds the seat `PENDING`, even if the first later fails; they can simply try again with a new key.
* **At-least-once notifications:** a retry after a lost response could deliver twice unless Notification dedupes on `Idempotency-Key` (see below).
* **Shared database:** `bookings` has foreign keys to `users/concerts/seats`, so the services are coupled through one schema. Fully separate databases would need data replication or ID-only references.
* **Prototype identity:** `user_id` stands in for authentication; production needs verified tokens.
* **Not implemented:** circuit breaker, rate limiting, distributed tracing, message broker (the outbox + worker is the lightweight stand-in).

## What the other services/frontend must provide

These are assumptions this service makes. Please agree them with the owners.

**Availability Service**
1. `POST /api/reservations` receives `{concert_id, seat_id, booking_id}`. Return `200` if reserved, `409` if held by a *different* booking, `404` if the seat is unknown. **Make it idempotent per `booking_id`** (same booking again = `200`) and **atomic** (a conditional `UPDATE ... WHERE status='AVAILABLE'` or the `reservations` unique constraint, not read-then-write).
2. `DELETE /api/reservations/{seat_id}?concert_id=&booking_id=` must release **only if the reservation belongs to that `booking_id`**, and return `200`/`404` when there is nothing to release. This matters: queued releases can arrive late, and a release without this check could free a seat that another booking now holds.
3. `GET /health`.

**Notification Service**: `POST /api/notifications` should ignore a repeated `Idempotency-Key` header (e.g. `B123:NOTIFY_CONFIRMED`) and return the original result; `GET /health`.

**Frontend**: send a fresh UUID in `Idempotency-Key` for each booking attempt and reuse it on a retry; use `?user_id=` when cancelling; show `detail` codes and the `notification_status` / `seat_release_status` fields.

**Database**: `database/init.sql` has no seed data, and `bookings` references `users/concerts/seats`. Use `SEED_DEMO_DATA=true` for development, or add seed rows to `init.sql`.

## Tests

See [`../tests/README.md`](../tests/README.md).
