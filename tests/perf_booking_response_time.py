"""NFR3 evidence: booking response time under concurrent load.

Run with the whole system up (docker compose up -d):

    python tests/perf_booking_response_time.py                       # 50 bookings, 8 users at once
    python tests/perf_booking_response_time.py --requests 100 --users 8

How it works
    Each simulated user owns one free seat and repeats: book it (timed), then
    cancel it (not timed) so the seat is free for the next round. Users never
    compete for the same seat, so every booking should succeed. This works
    with the small seed data (only a handful of seats per concert).

    Each timed booking is the full path: client -> Booking Service -> Availability
    Service -> PostgreSQL -> back, plus the notification being queued.

Test conditions and target (for report sections 2.5 NFR3 and 7.1):
    * all services on one laptop via Docker Compose, PostgreSQL 16
    * N booking requests from U simultaneous users
    * target: 0 errors and 95% of bookings answered in under 1000 ms (p95 < 1 s)
"""
import argparse
import statistics
import threading
import time
import uuid

import requests

BOOKING = "http://localhost:5001"
AVAILABILITY = "http://localhost:5002"
TARGET_P95_MS = 1000


def pick_seats(users):
    """One free seat per simulated user, from the concert with the most free seats."""
    best = []
    for concert in requests.get(f"{AVAILABILITY}/api/concerts", timeout=10).json():
        seats = requests.get(f"{AVAILABILITY}/api/concerts/{concert['concert_id']}/seats", timeout=10).json()
        free = [(concert["concert_id"], s["seat_id"]) for s in seats if s["status"] == "AVAILABLE"]
        if len(free) > len(best):
            best = free
    if not best:
        raise SystemExit("No free seats - reset the data with: docker compose down -v")
    return best[:users]


def wait_until_free(concert_id, seat_id, limit=10):
    """Cancelling marks the booking CANCELLED at once; the Booking Service's outbox
    worker then releases the seat a moment later. Wait for that before rebooking."""
    deadline = time.time() + limit
    url = f"{AVAILABILITY}/api/concerts/{concert_id}/seats/{seat_id}/availability"
    while time.time() < deadline:
        if requests.get(url, timeout=5).json().get("available"):
            return
        time.sleep(0.05)
    raise SystemExit(f"Seat {seat_id} was not released within {limit} s")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--requests", type=int, default=50, help="total timed bookings")
    ap.add_argument("--users", type=int, default=8, help="simultaneous users")
    args = ap.parse_args()

    seats = pick_seats(args.users)
    users = len(seats)
    per_user = -(-args.requests // users)          # round up
    print(f"NFR3 performance test: {per_user * users} bookings from {users} simultaneous users "
          f"(concert {seats[0][0]}, book -> cancel -> book again)")

    timings, errors, lock = [], [], threading.Lock()
    start_line = threading.Barrier(users)

    def user(n, concert_id, seat_id):
        start_line.wait()
        user_id = 1 + n % 2
        for _ in range(per_user):
            t0 = time.perf_counter()
            r = requests.post(f"{BOOKING}/api/bookings",
                              json={"user_id": user_id, "concert_id": concert_id, "seat_id": seat_id},
                              headers={"Idempotency-Key": f"perf-{uuid.uuid4()}"}, timeout=15)
            ms = (time.perf_counter() - t0) * 1000
            with lock:
                timings.append(ms)
                if r.status_code != 201:
                    errors.append(r.status_code)
            if r.status_code == 201:  # free the seat again for the next round (not timed)
                requests.delete(f"{BOOKING}/api/bookings/{r.json()['booking_id']}",
                                params={"user_id": user_id}, timeout=15)
                wait_until_free(concert_id, seat_id)

    started = time.perf_counter()
    threads = [threading.Thread(target=user, args=(i, c, s)) for i, (c, s) in enumerate(seats)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    elapsed = time.perf_counter() - started

    lat = sorted(timings)
    p95 = lat[max(0, round(0.95 * len(lat)) - 1)]
    print(f"\n  Successful bookings : {len(lat) - len(errors)}/{len(lat)}"
          + (f"   failed with: {sorted(set(errors))}" if errors else ""))
    print(f"  Response time (ms)  : min {lat[0]:.0f} | median {statistics.median(lat):.0f} | "
          f"p95 {p95:.0f} | max {lat[-1]:.0f}")
    print(f"  Total run time      : {elapsed:.1f} s (includes the untimed cancellations)")
    passed = not errors and p95 < TARGET_P95_MS
    print(f"\nRESULT: {'PASS' if passed else 'FAIL'} (target: 0 errors and p95 < {TARGET_P95_MS} ms)")


if __name__ == "__main__":
    main()