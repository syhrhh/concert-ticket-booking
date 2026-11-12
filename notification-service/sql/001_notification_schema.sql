-- Notification Service schema additions.
-- Applied automatically at start-up and safe to run repeatedly.
-- It only ADDS to the shared schema in database/init.sql.

-- The table normally comes from database/init.sql; create it here too so the
-- service also works against an empty database.
CREATE TABLE IF NOT EXISTS notifications (
    notification_id SERIAL PRIMARY KEY,
    booking_id VARCHAR(64),
    user_id INTEGER,
    type VARCHAR(50) NOT NULL,
    message TEXT NOT NULL,
    status VARCHAR(20) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Duplicate protection. The Booking Service retries until it gets a reply
-- (at-least-once delivery) and sends the same Idempotency-Key every time,
-- e.g. "B0A1B2C3D4E5F:NOTIFY_CONFIRMED". UNIQUE means a retried message can
-- never create a second notification (exactly-once effect).
-- PostgreSQL allows many NULLs in a UNIQUE column, so requests without a key still work.
ALTER TABLE notifications ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(128);
CREATE UNIQUE INDEX IF NOT EXISTS uq_notifications_idempotency_key
    ON notifications (idempotency_key);

-- Fast "show me my notifications".
CREATE INDEX IF NOT EXISTS idx_notifications_user
    ON notifications (user_id, notification_id);

-- Only the two notification types the system produces, and the one status this
-- service sets (delivery is simulated: recorded + logged = SENT).
-- NOT VALID: enforce for new rows without failing on old demo rows already in the table.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_notifications_type') THEN
        ALTER TABLE notifications ADD CONSTRAINT chk_notifications_type
            CHECK (type IN ('BOOKING_CONFIRMED', 'BOOKING_CANCELLED')) NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_notifications_status') THEN
        ALTER TABLE notifications ADD CONSTRAINT chk_notifications_status
            CHECK (status IN ('PENDING', 'SENT', 'FAILED')) NOT VALID;
    END IF;
END $$;
