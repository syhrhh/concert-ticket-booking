CREATE TABLE IF NOT EXISTS users (
    user_id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS concerts (
    concert_id SERIAL PRIMARY KEY,
    concert_name VARCHAR(255) NOT NULL,
    artist_name VARCHAR(255),
    venue VARCHAR(255) NOT NULL,
    concert_date DATE NOT NULL,
    concert_time TIME
);

CREATE TABLE IF NOT EXISTS seats (
    seat_id SERIAL PRIMARY KEY,
    concert_id INT NOT NULL REFERENCES concerts(concert_id),
    section VARCHAR(50),
    row_number VARCHAR(20),
    seat_number VARCHAR(20) NOT NULL,
    price NUMERIC(10,2) NOT NULL CHECK (price >= 0),
    status VARCHAR(20) NOT NULL DEFAULT 'AVAILABLE',
    UNIQUE(concert_id, seat_number)
);

CREATE TABLE IF NOT EXISTS bookings (
    booking_id VARCHAR(30) PRIMARY KEY,
    user_id INT NOT NULL REFERENCES users(user_id),
    concert_id INT NOT NULL REFERENCES concerts(concert_id),
    seat_id INT NOT NULL REFERENCES seats(seat_id),
    status VARCHAR(20) NOT NULL,
    idempotency_key VARCHAR(255) UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS reservations (
    reservation_id SERIAL PRIMARY KEY,
    booking_id VARCHAR(30),
    concert_id INT NOT NULL REFERENCES concerts(concert_id),
    seat_id INT NOT NULL REFERENCES seats(seat_id),
    status VARCHAR(20) NOT NULL,
    reserved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(concert_id, seat_id)
);

CREATE TABLE IF NOT EXISTS notifications (
    notification_id SERIAL PRIMARY KEY,
    booking_id VARCHAR(30),
    user_id INT,
    type VARCHAR(50) NOT NULL,
    message TEXT NOT NULL,
    status VARCHAR(20) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
