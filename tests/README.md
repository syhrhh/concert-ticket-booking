# Testing Evidence

Automated integration tests for the booking workflow. They start the **real services as
separate processes** on private ports (booking 15001, availability 15002, notification
15003) against a throw-away PostgreSQL database (`concert_booking_test`, created from
`database/init.sql` and dropped afterwards), so your development stack on 5001-5003 and
the `concert_booking` database are not touched.

## Run

```bash
docker compose up -d postgres        # or any PostgreSQL where concert_user / concert_pass can create databases
pip install -r tests/requirements.txt
pytest tests/test_booking_scenarios.py -v | tee tests/logs/pytest-output.txt
```

If your Postgres is elsewhere, set `TEST_ADMIN_DATABASE_URL`
(default `postgresql://concert_user:concert_pass@localhost:5432/postgres`).

Each service writes its log to `tests/logs/<name>-service.log` (git-ignored); these logs
and `pytest-output.txt` are the evidence for the report.

## Required demonstrations

| # | Demonstration | Test(s) | What to point at in the logs |
|---|---|---|---|
| 1 | Successful booking | `test_successful_booking_spans_all_services` | `booking ... PENDING` then `CONFIRMED` in the booking log; the notification printed by the notification service |
| 2 | Conflicting booking rejected | `test_conflicting_booking_is_rejected_and_recorded`, `test_concurrent_bookings_for_one_seat_only_one_succeeds` | `REJECTED reason=SEAT_NOT_AVAILABLE`; 10 simultaneous users, exactly one `201` (the Availability Service's row lock decides) |
| 3 | Duplicate request handled | `test_duplicate_request_with_same_key_returns_same_booking`, `test_concurrent_duplicates_with_same_key_create_one_booking`, `test_repeat_without_key_never_creates_a_second_confirmed_booking`, `test_same_key_with_different_request_is_refused` | `replayed for repeated Idempotency-Key`; one DB row, one notification |
| 4 | Partial failure | `test_notification_down_booking_keeps_working_and_recovers` | `outbox RETRY ... error=ConnectionError next_try_in=1s, 2s...` then `outbox DONE` after restart |
| - | Other failures | `test_availability_down_gives_fast_503_and_same_key_retry_succeeds`, `test_stale_pending_booking_is_recovered` | `availability unreachable`, `retried after failure`, `reaped 1 stale PENDING booking` |
| - | Cancel, validation, security | `test_cancel_releases_seat_and_is_idempotent`, `test_invalid_input_is_rejected`, `test_bad_idempotency_key_and_ids_are_rejected`, `test_unknown_references_give_404` | |

The tests start the Availability and Notification code that is in your checkout, so they
need the **database-backed Availability Service** (branch `availability-service`) merged
into your branch. If a service changes its API, see "Contract with the other components"
in `booking-service/README.md` and update `tests/conftest.py`.

Teammates' own tests (`test_availability.py`, `member3_smoke_test.py`) live in this folder
too, but they need the Availability Service already running on port 5002 against the
development database. That is why the command above names the booking test file: a plain
`pytest tests` would also run theirs and fail with "connection refused" unless that
service is up.
