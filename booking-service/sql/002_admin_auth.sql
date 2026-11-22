-- Admin / staff access. Additive and safe to run repeatedly (no data is lost,
-- so `docker compose down -v` is NOT required).
-- Customers keep role CUSTOMER; staff accounts get role ADMIN.
-- The admin account itself is created at start-up by auth.ensure_admin()
-- (password hashed with PBKDF2, never stored in plain text or in this file).
ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(20) NOT NULL DEFAULT 'CUSTOMER';

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_users_role') THEN
        ALTER TABLE users ADD CONSTRAINT chk_users_role CHECK (role IN ('CUSTOMER', 'ADMIN'));
    END IF;
END $$;

-- Staff can take seats off sale: add BLOCKED to the seat status values.
-- (init.sql already has it on fresh databases; this upgrades existing ones.)
ALTER TABLE seats DROP CONSTRAINT IF EXISTS seats_status_check;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_seats_status') THEN
        ALTER TABLE seats ADD CONSTRAINT chk_seats_status
            CHECK (status IN ('AVAILABLE', 'RESERVED', 'BOOKED', 'BLOCKED'));
    END IF;
END $$;
