"""LIVE DEMO: partial failure of the Notification Service (compulsory demo 4).

Run it while the whole system is up (docker compose up -d, or each service in its
own terminal). The script tells you when to stop and restart the Notification
Service and waits until it detects the change, then prints the evidence.

    python tests/demo_notification_failure.py               # service switched OFF
    python tests/demo_notification_failure.py --scenario slow   # reply lost / timeout

Scenario "down" (default)
    1. Notification Service is stopped.
    2. A booking is still CONFIRMED, fast - booking does not wait for notifications.
    3. The Booking Service reports Notification DOWN and keeps the message queued.
    4. Notification Service is restarted -> the queued message is delivered
       automatically, exactly once.

Scenario "slow"
    The Notification Service saves the message but answers after 4 s, longer than
    the Booking Service's 2 s timeout, so every reply is "lost" and the Booking
    Service keeps retrying. Our Idempotency-Key check makes every retry a no-op:
    the user still gets exactly ONE notification.

Only uses the public REST APIs (no database access), like a real client.
"""
import argparse
import sys
import time
import uuid

import requests

BOOKING = "http://localhost:5001"
AVAILABILITY = "http://localhost:5002"
NOTIFICATION = "http://localhost:5003"
USER_ID = 1
CONCERT_ID = 1


def line(title=""):
    print("\n" + "=" * 70 + (f"\n {title}\n" + "=" * 70 if title else ""))


def up(url):
    try:
        return requests.get(f"{url}/health", timeout=1.5).status_code == 200
    except requests.RequestException:
        return False


def wait_for(url, want_up, instruction):
    if up(url) == want_up:
        return
    print(f"\n  >>> {instruction}")
    print("      waiting", end="", flush=True)
    while up(url) != want_up:
        time.sleep(1)
        print(".", end="", flush=True)
    print(" detected.\n")


def free_seat():
    seats = requests.get(f"{AVAILABILITY}/api/concerts/{CONCERT_ID}/seats", timeout=5).json()
    for s in reversed(seats):
        if s["status"] == "AVAILABLE":
            return s
    sys.exit("No free seats left for this concert - reset the database first.")


def book(seat):
    started = time.perf_counter()
    r = requests.post(f"{BOOKING}/api/bookings",
                      json={"user_id": USER_ID, "concert_id": CONCERT_ID, "seat_id": seat["seat_id"]},
                      headers={"Idempotency-Key": f"demo-{uuid.uuid4()}"}, timeout=15)
    return r, (time.perf_counter() - started) * 1000


def booking(bid):
    return requests.get(f"{BOOKING}/api/bookings/{bid}", timeout=5).json()


def notes_for(bid):
    return [n for n in requests.get(f"{NOTIFICATION}/api/users/{USER_ID}/notifications", timeout=5).json()
            if n["booking_id"] == bid]


def poll(check, timeout, what):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if check():
            return True
        time.sleep(1)
    print(f"  [!] gave up waiting for {what}")
    return False


def scenario_down():
    line("PARTIAL FAILURE: Notification Service is DOWN")
    wait_for(NOTIFICATION, False, "STOP the Notification Service now:\n"
             "        docker compose stop notification-service      (or Ctrl+C in its terminal)")
    print(f"  Booking :5001 = {'UP' if up(BOOKING) else 'DOWN'}   "
          f"Availability :5002 = {'UP' if up(AVAILABILITY) else 'DOWN'}   Notification :5003 = DOWN")

    seat = free_seat()
    r, ms = book(seat)
    b = r.json()
    print(f"\n  1. POST /api/bookings seat {seat['seat_number']} -> HTTP {r.status_code} in {ms:.0f} ms")
    print(f"     booking_id={b.get('booking_id')} status={b.get('status')} "
          f"notification_status={b.get('notification_status')}")
    if r.status_code != 201:
        sys.exit(f"  Booking failed: {b}")
    print("     -> booking succeeds and does NOT wait for the notification service")

    deps = requests.get(f"{BOOKING}/health/dependencies", timeout=5).json()
    print(f"\n  2. GET /health/dependencies -> notification_service={deps['notification_service']}, "
          f"outbox_pending={deps['outbox_pending']}")
    print("     -> the notification is safely queued in the Booking Service's outbox")
    print("     (the booking-service log shows: outbox RETRY ... next_try_in=1s, 2s, 4s ...)")
    time.sleep(5)

    wait_for(NOTIFICATION, True, "Now START the Notification Service again:\n"
             "        docker compose start notification-service     (or re-run uvicorn)")
    t0 = time.time()
    if poll(lambda: booking(b["booking_id"])["notification_status"] == "SENT", 30, "delivery"):
        print(f"  3. notification_status = SENT, {time.time() - t0:.0f} s after the service came back")
    delivered = notes_for(b["booking_id"])
    print(f"  4. GET /api/users/{USER_ID}/notifications -> {len(delivered)} notification(s) for "
          f"{b['booking_id']}: {[n['message'] for n in delivered]}")
    ok = len(delivered) == 1
    print("\nRESULT:", "PASS - queued notification delivered exactly once after recovery" if ok else "FAIL")


def scenario_slow():
    line("PARTIAL FAILURE: replies are LOST (Notification Service too slow)")
    print("  Restart the Notification Service in slow mode first:")
    print('     PowerShell:  $env:NOTIFICATION_FAULT_MODE="slow"; docker compose up -d notification-service')
    print("     (without Docker:  $env:FAULT_MODE=\"slow\"; uvicorn main:app --port 5003)")
    input("  Press Enter when it is running in slow mode... ")
    wait_for(NOTIFICATION, True, "Waiting for the Notification Service")

    seat = free_seat()
    r, ms = book(seat)
    b = r.json()
    print(f"\n  1. POST /api/bookings -> HTTP {r.status_code} in {ms:.0f} ms, booking {b.get('booking_id')} "
          f"{b.get('status')}")
    print("     Waiting 12 s while the Booking Service delivers, times out (2 s) and retries...")
    time.sleep(12)
    print(f"  2. notification_status still {booking(b['booking_id'])['notification_status']} "
          "(every reply arrived too late)")
    print(f"     but the Notification Service holds {len(notes_for(b['booking_id']))} notification(s) "
          "- each retry was recognised as a DUPLICATE")
    print("     (notification-service log: 'DUPLICATE ignored key=...:NOTIFY_CONFIRMED')")

    print("\n  Now restart it in NORMAL mode:")
    print('     PowerShell:  $env:NOTIFICATION_FAULT_MODE="off"; docker compose up -d notification-service')
    input("  Press Enter when it is running normally... ")
    wait_for(NOTIFICATION, True, "Waiting for the Notification Service")
    poll(lambda: booking(b["booking_id"])["notification_status"] == "SENT", 30, "delivery")
    delivered = notes_for(b["booking_id"])
    print(f"  3. notification_status = {booking(b['booking_id'])['notification_status']}, "
          f"notifications for this booking = {len(delivered)}")
    ok = len(delivered) == 1
    print("\nRESULT:", "PASS - many deliveries, exactly one notification" if ok else "FAIL")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", choices=["down", "slow"], default="down")
    args = ap.parse_args()
    if not (up(BOOKING) and up(AVAILABILITY)):
        sys.exit("Booking (5001) and Availability (5002) must be running first.")
    scenario_down() if args.scenario == "down" else scenario_slow()
