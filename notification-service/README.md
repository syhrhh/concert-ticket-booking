# Notification Service

FastAPI service on **port 5003**. It records booking confirmations and cancellations
sent by the **Booking Service** and lets the client show them. No real e-mail is sent
(the brief allows recording/displaying notifications): a notification is "sent" by
saving it in PostgreSQL and writing a log line.

## Run it

```bash
# whole system (from the repo root)
docker compose up -d --build

# or only this service, without Docker (PostgreSQL must be running)
cd notification-service
pip install -r requirements.txt
uvicorn main:app --port 5003 --reload
```

On start-up the service applies `sql/001_notification_schema.sql` (additive and
repeatable; it never edits `database/init.sql`).

| Environment variable | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | `postgresql://concert_user:concert_pass@localhost:5432/concert_booking` | Shared PostgreSQL |
| `CORS_ORIGINS` | `http://localhost:3000,http://localhost:5173` | Browser origins allowed |
| `FAULT_MODE` | `off` | **Demo only.** `error` = answer 503; `slow` = save, then reply after `FAULT_DELAY_SECONDS` (4 s) |

## API

| Method & path | Purpose | Success | Errors |
|---|---|---|---|
| `POST /api/notifications` | Record a notification. Body `{booking_id, user_id, type, message}`; header `Idempotency-Key` | `201` new, `200` repeat (`Idempotent-Replay: true`) | `422 INVALID_REQUEST`, `422 IDEMPOTENCY_KEY_REUSED`, `503 DATABASE_UNAVAILABLE` |
| `GET /api/users/{user_id}/notifications` | A user's notifications, oldest first (`?limit=` max 200) | `200` list | `422` invalid id |
| `GET /health` | Service + database status | `200` | `503` if the database is down |

`type` is `BOOKING_CONFIRMED` or `BOOKING_CANCELLED`. `booking_id` must look like the
Booking Service's ids (`B` + 12 hex characters). Interactive docs: <http://localhost:5003/docs>.

Notification object: `notification_id, booking_id, user_id, type, message, status, created_at`.

## How it fits the distributed behaviours

| Behaviour | What this service does |
|---|---|
| **Partial failure** | It is a separate process. If it is down, bookings still succeed: the Booking Service stores the message in its outbox and retries with back-off (1 s, 2 s, 4 s ...) until this service is back. |
| **Duplicate delivery** | Retries mean the same message can arrive more than once (e.g. we saved it but the reply was lost). The Booking Service sends the same `Idempotency-Key` each time (`<booking_id>:NOTIFY_CONFIRMED`). The key is `UNIQUE` in the table and the insert uses `ON CONFLICT DO NOTHING`, so a repeat returns the original notification and never creates a second one, even if copies arrive at the same instant. **At-least-once delivery + idempotent consumer = exactly-once effect.** |
| **Durability** | Notifications are stored in PostgreSQL, so they survive a restart of this service. |
| **Security** | Strict input schema (unknown fields rejected, `type` limited to two values, length limits, id formats checked), parameterised SQL only, generic error bodies (no stack traces), CORS limited to known origins, container runs as a non-root user. |
| **Scalability** | No state in memory, so several instances can run behind a load balancer; the database's UNIQUE index still stops duplicates across instances. |

## Evidence

| Command | Shows |
|---|---|
| `pytest tests/test_notification_service.py -v` | 19 tests: storing, duplicate handling (incl. 10 simultaneous copies), restart durability, validation, fault modes |
| `pytest tests/test_booking_scenarios.py -v` | Team tests incl. `test_notification_down_booking_keeps_working_and_recovers` |
| `python tests/demo_notification_failure.py` | Live demo: service stopped -> booking still works -> delivered once after restart |
| `python tests/demo_notification_failure.py --scenario slow` | Live demo: replies lost -> many retries -> still exactly one notification |
| Postman: import `tests/postman/notification-service.postman_collection.json`, then Run | 11 requests, 21 checks |

Watch the logs during a demo with `docker compose logs -f notification-service booking-service`.

## Limitations (for the report)

* Delivery is simulated (database + log); a real system would call an e-mail/SMS provider here.
* After an outage, queued messages can arrive **out of order** (e.g. a cancellation before
  its confirmation), because each message has its own retry timer.
* The service shares the team's PostgreSQL database; a production design would give it its
  own database.
* No authentication between services yet: any caller that can reach port 5003 can create a
  notification. A shared service key or mTLS would fix this.
