-- Concert Ticket Booking: PostgreSQL demo schema (development only)
-- Loaded automatically ONCE for a fresh Docker Postgres volume.
-- Keep separate booking and availability application services.

CREATE TABLE IF NOT EXISTS users (
    user_id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(255) NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS concerts (
    concert_id SERIAL PRIMARY KEY,
    concert_name VARCHAR(255) NOT NULL,
    artist_name VARCHAR(255),
    venue VARCHAR(255) NOT NULL,
    concert_date DATE NOT NULL,
    concert_time TIME,
    description TEXT
);

CREATE TABLE IF NOT EXISTS seats (
    seat_id SERIAL PRIMARY KEY,
    concert_id INTEGER NOT NULL REFERENCES concerts(concert_id),
    section VARCHAR(50),
    row_number VARCHAR(20),
    seat_number VARCHAR(20) NOT NULL,
    price NUMERIC(10, 2) NOT NULL CHECK (price >= 0),
    status VARCHAR(20) NOT NULL DEFAULT 'AVAILABLE'
        CHECK (status IN ('AVAILABLE', 'RESERVED', 'BOOKED')),
    UNIQUE (concert_id, seat_number)
);

-- Booking Service (Member 2) will persist to this table.
-- Availability Service intentionally does not write bookings directly.
CREATE TABLE IF NOT EXISTS bookings (
    booking_id VARCHAR(64) PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(user_id),
    concert_id INTEGER NOT NULL REFERENCES concerts(concert_id),
    seat_id INTEGER NOT NULL REFERENCES seats(seat_id),
    status VARCHAR(20) NOT NULL
        CHECK (status IN ('PENDING', 'CONFIRMED', 'REJECTED', 'CANCELLED')),
    idempotency_key VARCHAR(255) UNIQUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Flow: Booking Service inserts the booking as PENDING first (booking states in the
-- agreed design), then calls Availability Service to reserve the seat.
-- UNIQUE(concert_id, seat_id): only one reservation can ever exist for a seat.
-- Cancelling deletes the reservation row so the seat can be booked again.
CREATE TABLE IF NOT EXISTS reservations (
    reservation_id SERIAL PRIMARY KEY,
    booking_id VARCHAR(64) NOT NULL UNIQUE REFERENCES bookings(booking_id),
    concert_id INTEGER NOT NULL REFERENCES concerts(concert_id),
    seat_id INTEGER NOT NULL REFERENCES seats(seat_id),
    status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE')),
    reserved_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (concert_id, seat_id)
);

CREATE TABLE IF NOT EXISTS notifications (
    notification_id SERIAL PRIMARY KEY,
    booking_id VARCHAR(64),
    user_id INTEGER,
    type VARCHAR(50) NOT NULL,
    message TEXT NOT NULL,
    status VARCHAR(20) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Demo users so Booking Service inserts satisfy bookings.user_id FK.
-- Placeholder hashes only; Booking Service must not treat these as real logins.
INSERT INTO users (user_id, name, email, password_hash)
VALUES
    (1, 'Demo User A', 'user.a@example.com', 'demo-placeholder-not-a-real-hash'),
    (2, 'Demo User B', 'user.b@example.com', 'demo-placeholder-not-a-real-hash')
ON CONFLICT (user_id) DO NOTHING;

-- Demonstration data: fictional events, not actual concerts.
INSERT INTO concerts (concert_id, concert_name, artist_name, venue, concert_date, concert_time, description)
VALUES
    (1, 'Demo Concert A', 'Example Artist A', 'Sample Arena', '2027-01-15', '20:00', 'Demo concert for the booking system'),
    (2, 'Demo Concert B', 'Example Artist B', 'Sample Hall', '2027-02-07', '19:30', 'Second demo concert')
ON CONFLICT (concert_id) DO NOTHING;

-- Seats are generated from this layout table, one row per section.
-- Edit the VALUES list to add/remove sections, change prices, rows or seats per row.
-- Each section gets rows A.. (rows) x seats 1.. (seats_per_row).
-- seat_number is "<section>-<row><nn>" (e.g. 133-A12) so it stays unique per concert,
-- as required by UNIQUE(concert_id, seat_number) in the agreed design.
-- Price tiers (fictional): Zone A RM450, Zone B RM350, Zone C RM280, Zone D RM200.
WITH layout (concert_id, section, price, rows, seats_per_row) AS (
    VALUES
        -- Concert 1: arena with lower bowl (1xx) and upper bowl (2xx)
        (1, '104', 280.00, 10, 20),   -- Zone C
        (1, '105', 280.00, 10, 20),   -- Zone C
        (1, '106', 280.00, 10, 20),   -- Zone C
        (1, '111', 350.00, 10, 20),   -- Zone B
        (1, '112', 350.00, 10, 20),   -- Zone B
        (1, '114', 450.00, 10, 20),   -- Zone A
        (1, '115', 450.00, 10, 20),   -- Zone A
        (1, '116', 450.00, 10, 20),   -- Zone A
        (1, '133', 350.00, 10, 20),   -- Zone B
        (1, '207', 200.00, 10, 20),   -- Zone D
        (1, '232', 200.00, 10, 20),   -- Zone D
        (1, '233', 200.00, 10, 20),   -- Zone D
        -- Concert 2: small hall
        (2, '101', 150.00,  5, 12),
        (2, '102', 100.00,  5, 12)
)
INSERT INTO seats (concert_id, section, row_number, seat_number, price)
SELECT l.concert_id,
       l.section,
       chr(64 + r.n),
       l.section || '-' || chr(64 + r.n) || lpad(s.n::text, 2, '0'),
       l.price
FROM layout l
CROSS JOIN LATERAL generate_series(1, l.rows) AS r(n)
CROSS JOIN LATERAL generate_series(1, l.seats_per_row) AS s(n)
ORDER BY l.concert_id, l.section, r.n, s.n
ON CONFLICT (concert_id, seat_number) DO NOTHING;

-- Ensure automatically generated IDs continue after seeded explicit IDs.
SELECT setval(pg_get_serial_sequence('concerts', 'concert_id'),
    (SELECT MAX(concert_id) FROM concerts), true);
SELECT setval(pg_get_serial_sequence('seats', 'seat_id'),
    (SELECT MAX(seat_id) FROM seats), true);
SELECT setval(pg_get_serial_sequence('users', 'user_id'),
    (SELECT MAX(user_id) FROM users), true);
