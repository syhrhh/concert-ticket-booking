-- Booking Service schema additions.
-- Applied automatically at start-up and safe to run repeatedly.
-- It only ADDS to the shared schema in database/init.sql, so it does not
-- conflict with changes the other team members make to that file.

-- Fingerprint of the original request body: lets us detect an
-- Idempotency-Key being re-used with a *different* request.
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS request_hash VARCHAR(64);
-- Why a booking was REJECTED / FAILED (machine-readable code).
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS failure_reason VARCHAR(100);

-- Booking lifecycle:
--   PENDING   -> request accepted, seat reservation in progress
--   CONFIRMED -> seat reserved at the Availability Service
--   REJECTED  -> business rejection (seat taken / not found); final
--   FAILED    -> technical failure (e.g. Availability down); client may retry
--   CANCELLED -> cancelled by the user after confirmation
-- init.sql may already define a narrower status check (without FAILED); drop it
-- so the full lifecycle below is allowed.
ALTER TABLE bookings DROP CONSTRAINT IF EXISTS bookings_status_check;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_bookings_status') THEN
        ALTER TABLE bookings ADD CONSTRAINT chk_bookings_status
            CHECK (status IN ('PENDING', 'CONFIRMED', 'REJECTED', 'FAILED', 'CANCELLED'));
    END IF;
END $$;

-- NOTE: seat exclusivity is NOT enforced here. It belongs to the Availability
-- Service (row lock + UNIQUE(concert_id, seat_id) on reservations). If an
-- earlier version of this file created the index below, remove it.
DROP INDEX IF EXISTS uq_bookings_active_seat;

CREATE INDEX IF NOT EXISTS idx_bookings_user ON bookings (user_id, created_at DESC);

-- Transactional outbox. Side effects that must survive a crash or a downstream
-- outage (confirmation / cancellation notifications, releasing a seat) are
-- written here in the SAME transaction as the booking state change, then
-- delivered by a background worker with retry and exponential back-off.
--   status: PENDING -> DONE, or DEAD after too many failed attempts
CREATE TABLE IF NOT EXISTS booking_outbox (
    outbox_id       BIGSERIAL PRIMARY KEY,
    booking_id      VARCHAR(30) NOT NULL REFERENCES bookings(booking_id),
    kind            VARCHAR(30) NOT NULL,
    payload         JSONB NOT NULL,
    status          VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    attempts        INT NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_error      TEXT,
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_outbox_due
    ON booking_outbox (next_attempt_at) WHERE status = 'PENDING';
CREATE INDEX IF NOT EXISTS idx_outbox_booking ON booking_outbox (booking_id, kind);
