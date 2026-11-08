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

INSERT INTO seats (seat_id, concert_id, section, row_number, seat_number, price)
VALUES
    (1, 1, 'VIP', 'A', 'A1', 250.00),
    (2, 1, 'VIP', 'A', 'A2', 250.00),
    (3, 1, 'VIP', 'A', 'A3', 250.00),
    (4, 1, 'STANDARD', 'B', 'B1', 120.00),
    (5, 1, 'STANDARD', 'B', 'B2', 120.00),
    (6, 1, 'STANDARD', 'B', 'B3', 120.00),
    (7, 2, 'STANDARD', 'A', 'A1', 100.00),
    (8, 2, 'STANDARD', 'A', 'A2', 100.00),
    -- Seats used by the four compulsory demos (A12 success, A13 conflict, A14 partial failure)
    (9, 1, 'VIP', 'A', 'A12', 250.00),
    (10, 1, 'VIP', 'A', 'A13', 250.00),
    (11, 1, 'VIP', 'A', 'A14', 250.00)
ON CONFLICT (seat_id) DO NOTHING;

-- Ensure automatically generated IDs continue after seeded explicit IDs.
SELECT setval(pg_get_serial_sequence('concerts', 'concert_id'),
    (SELECT MAX(concert_id) FROM concerts), true);
SELECT setval(pg_get_serial_sequence('seats', 'seat_id'),
    (SELECT MAX(seat_id) FROM seats), true);
SELECT setval(pg_get_serial_sequence('users', 'user_id'),
    (SELECT MAX(user_id) FROM users), true);
