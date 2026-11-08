-- Demo data for development and tests (enabled with SEED_DEMO_DATA=true).
-- Matches the seats the Availability Service currently exposes (concert 1,
-- seats 1-3). Safe to run repeatedly.

INSERT INTO users (user_id, name, email, password_hash)
SELECT n, 'Demo User ' || n, 'user' || n || '@example.com', '!demo-account-no-login'
FROM generate_series(1, 10) AS n
ON CONFLICT DO NOTHING;

INSERT INTO concerts (concert_id, concert_name, artist_name, venue, concert_date, concert_time)
VALUES (1, 'Demo Concert', 'Demo Artist', 'Main Arena', DATE '2026-12-20', TIME '20:00')
ON CONFLICT DO NOTHING;

INSERT INTO seats (seat_id, concert_id, section, row_number, seat_number, price)
VALUES (1, 1, 'A', '1', 'A1', 150.00),
       (2, 1, 'A', '1', 'A2', 150.00),
       (3, 1, 'A', '1', 'A3', 150.00)
ON CONFLICT DO NOTHING;

-- Keep the SERIAL sequences ahead of the explicit ids inserted above.
SELECT setval(pg_get_serial_sequence('users', 'user_id'), (SELECT MAX(user_id) FROM users));
SELECT setval(pg_get_serial_sequence('concerts', 'concert_id'), (SELECT MAX(concert_id) FROM concerts));
SELECT setval(pg_get_serial_sequence('seats', 'seat_id'), (SELECT MAX(seat_id) FROM seats));
