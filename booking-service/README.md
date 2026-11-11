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
uvicorn main:app --port 5001 --reload
```

No Docker? Use any local PostgreSQL: create the login and database from
`docker-compose.yml` (`concert_user` / `concert_pass`, database `concert_booking`), load
`database/init.sql`, or set `DATABASE_URL` to your own.

The team's `database/init.sql` already seeds demo users 1-2, concerts and seats, so the
service runs without extra seeding. `SEED_DEMO_DATA=true` is optional: it only adds users
3-10 (and seats 1-3 if they are missing); the automated tests use it for their own database.
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
| `POST /api/bookings` | Create booking. Body `{user_id, concert_id, seat_id}`; header `Idempotency-Key` (always send it) | `201` new, `200` replay (`Idempotent-Replay: true`) | `409 SEAT_NOT_AVAILABLE`, `404 USER_NOT_FOUND / CONCERT_NOT_FOUND / SEAT_NOT_FOUND`, `422` invalid input or `IDEMPOTENCY_KEY_REUSED`, `409 REQUEST_IN_PROGRESS`, `503 AVAILABILITY_SERVICE_UNAVAILABLE / RECOVERY_IN_PROGRESS` (+`Retry-After`) |
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
    B->>D: INSERT booking PENDING (Idempotency-Key is UNIQUE)
    B->>A: POST /api/reservations {concert, seat, booking_id}
    A->>D: lock seat row, check booking is PENDING, INSERT reservation
    A-->>B: 200 RESERVED (or 409 seat taken)
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
| **No double booking** | The **Availability Service** owns this: it locks the seat row (`SELECT ... FOR UPDATE`) inside one transaction and `reservations` has `UNIQUE(concert_id, seat_id)`, so of any number of simultaneous requests exactly one gets `200` and the rest get `409`. The Booking Service stores a `409` as a `REJECTED` booking. | Availability `reserve_seat`; `service._process` |
| **Duplicate requests** | `Idempotency-Key` is a UNIQUE column claimed by the first INSERT (`ON CONFLICT DO NOTHING`). A repeat returns the stored result (`200` + `Idempotent-Replay`); a concurrent duplicate waits for the original. Same key + different body = `422`. Reserving is also idempotent per `booking_id` at Availability. Without a key a repeat looks like a new customer and is refused (`409`), so clients must always send the key. | `service.create_booking`, `service._replay` |
| **Partial failure: Notification down** | The request path never calls Notification. The confirmation is an outbox row committed with the booking; a worker delivers it with timeouts, exponential back-off (1s, 2s, 4s... capped) and gives up as `DEAD` after `OUTBOX_MAX_ATTEMPTS`. Booking, viewing and cancelling continue. | `outbox.py` |
| **Partial failure: Availability down** | Short timeouts, then `503` with `Retry-After`; booking is stored as `FAILED`, a seat release is queued (the reservation may have been applied before the timeout), and a retry with the same key re-runs the same record. | `service._process`, `_retry_failed` |
| **Crash mid-request** | A booking stuck `PENDING` past `PENDING_TIMEOUT_SECONDS` is marked `FAILED` and its seat released by the worker. | `outbox._reap_stale_pending` |
| **Cancel** | State change + seat-release + notification rows committed atomically; the worker finishes them even if a service is down. | `service.cancel_booking` |
| **Security** | Strict request schema (`extra=forbid`, positive 32-bit ints), regex-checked ids and idempotency keys, parameterised SQL only, owner check on cancel, generic `500` body (no internals), no personal data in logs, credentials from environment, CORS limited to known origins. | `main.py` |
| **Scalability** | The service holds no state in memory: add instances behind a load balancer. Correctness is enforced in the database (keys, row locks), outbox rows are claimed with `FOR UPDATE SKIP LOCKED` so workers on different instances do not double-send, and the pool is configurable. | `db.py`, `outbox.py` |

## Trade-offs and limitations (for the report)

* **Eventual consistency after cancel/failure:** the seat is released by the worker (about a second), so re-booking immediately after cancelling can briefly be rejected.
* **At-least-once notifications:** a retry after a lost response could deliver twice unless Notification dedupes on `Idempotency-Key` (see below).
* **Shared database:** Booking and Availability share one PostgreSQL schema: Availability reads the `bookings` row (it must be `PENDING` or `CONFIRMED` to reserve) and `bookings` has foreign keys to `users/concerts/seats`. This is simple and consistent, but couples the services; separate databases would need an API call or replication instead.
* **Prototype identity:** `user_id` stands in for authentication; production needs verified tokens.
* **Not implemented:** circuit breaker, rate limiting, distributed tracing, message broker (the outbox + worker is the lightweight stand-in).

## Contract with the other components

**Availability Service** (implemented on branch `availability-service`; tested together with this service)
1. `POST /api/reservations` with `{concert_id, seat_id, booking_id}`. The booking must already exist in `bookings` as `PENDING` (this service inserts it first). `200` = reserved (repeating the same `booking_id` also returns `200`), `409 SEAT_NOT_AVAILABLE` = taken, `404 SEAT_NOT_FOUND`.
2. `DELETE /api/reservations/{booking_id}` releases the seat owned by that booking. It must return `200` even when nothing is left to release, and must work for `CANCELLED` / `FAILED` bookings (the booking is already in that state when the release arrives). Only a `2xx` counts as success here; a `404` is retried, never ignored.
3. `GET /health`.

**Notification Service**: `POST /api/notifications` (types `BOOKING_CONFIRMED`, `BOOKING_CANCELLED`). Ideally ignore a repeated `Idempotency-Key` header (e.g. `B123...:NOTIFY_CONFIRMED`) so a retry after a lost response cannot notify twice; `GET /health`.

**Frontend**: send a fresh UUID in `Idempotency-Key` for each booking attempt and reuse it on a retry; use `?user_id=` when cancelling; send only `user_id, concert_id, seat_id`; show the `detail` codes and the `notification_status` / `seat_release_status` fields.

**Database**: `bookings` must allow the statuses `PENDING, CONFIRMED, REJECTED, FAILED, CANCELLED`. If `init.sql` defines a narrower check, the start-up migration replaces it. `user_id`, `concert_id` and `seat_id` must exist (foreign keys); `init.sql` seeds users 1-2 and the seats; add more users there (or use `SEED_DEMO_DATA=true`) if you need them.

## Tests

See [`../tests/README.md`](../tests/README.md).
