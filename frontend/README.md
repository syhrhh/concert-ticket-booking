# ENCORE — frontend (Member 1)

Dark, responsive concert-ticket booking client built using **React + Vite**, connected to the group's **actual FastAPI services**. It is a UI for a distributed-systems proof of concept, not a live ticket merchant.

## What has been implemented

- Concerts come from **Availability Service :5002** (`GET /api/concerts`), including real DB data, searchable by name/artist/venue.
- Seats come from **Availability Service :5002** (`GET /api/concerts/:id/seats`); `AVAILABLE` seats are selectable, other statuses are disabled.
- Seat confirmation calls **Booking Service :5001** (`POST /api/bookings`) with `{user_id, concert_id, seat_id}` and a **new `Idempotency-Key`** per attempt. On a transport/503 retry the *same* key is reused so the server can replay the result safely. On a definitive 409 seat conflict, the user must pick a new seat.
- My Tickets calls `GET /api/users/:user_id/bookings`; cancellation calls `DELETE /api/bookings/:booking_id?user_id=...`.
- Notification bell calls **Notification Service :5003** (`GET /api/users/:id/notifications`). Delivery can be delayed if that service is down; booking status is authoritative.
- Health indicators use the real `/health` endpoints; failures show honest error states with refresh/retry actions.
- Two **demo account IDs (1, 2)** are switchable. This is not authentication. `database/init.sql` must seed them.
- Design: dark mode, yellow-to-pink gradient, glassmorphic cards, accessible focus states, hover/press feedback, and mobile responsive layout.

## On Windows, from the cloned repository

Open VS Code > Terminal > New Terminal:

```powershell
# From concert-ticket-booking repo root
cd frontend
npm install
npm run dev
```

Visit **http://localhost:3000**. You need Node.js 18 or later (Node 20/22 recommended).

### Also start your teammates' backend services

From the repository root, in separate terminals (and with dependencies installed):

```powershell
# Terminal A: PostgreSQL (if Docker is installed)
docker compose up -d postgres

# Terminal B: Availability
cd availability-service
pip install -r requirements.txt
python -m uvicorn main:app --reload --port 5002

# Terminal C: Booking
cd booking-service
pip install -r requirements.txt
python -m uvicorn main:app --reload --port 5001

# Terminal D: Notifications
cd notification-service
pip install -r requirements.txt
python -m uvicorn main:app --reload --port 5003
```

Run each command **from the repo root in a fresh terminal**, so each `cd` enters the correct folder. Your group should use a Python environment where all required packages are installed. PostgreSQL needs the `database/init.sql` schema and seed. Docker Compose **currently starts only postgres + availability** in the supplied repository; it does not automatically run booking or notification. If you prefer Compose, ask Member 4 to finish those service definitions.

### Ports and dev proxy

`frontend/vite.config.js` exposes **Vite on :3000** and proxies requests:

| Browser path | Real API |
|---|---|
| `/gateway/availability/api/concerts` | `http://127.0.0.1:5002/api/concerts` |
| `/gateway/booking/api/bookings` | `http://127.0.0.1:5001/api/bookings` |
| `/gateway/notifications/api/users/1/notifications` | `http://127.0.0.1:5003/api/users/1/notifications` |

This avoids browser CORS problems *during Vite development*; **the API services still run independently**. If running Vite inside Docker, change `vite.config.js` proxy targets to Compose service hostnames. For production, use a reverse proxy for `/gateway/*` or supply the three `VITE_*_API` variables documented in `.env.example`.

## Suggested acceptance tests

| Test | Browser action | Expected evidence |
|---|---|---|
| Concert browsing | Open Discover | Database concerts displayed; network GET returns 200 |
| Seats | View seats for a concert | Only `AVAILABLE` seats enabled |
| Booking | Click A1 > Confirm | POST with `Idempotency-Key`; booking ID and `CONFIRMED` result |
| View | Open My Tickets | GET returns the booked ticket |
| Cancel | Click Cancel ticket | DELETE with `user_id`; booking status `CANCELLED` |
| Seat conflict | User 01 and User 02 try the same seat | Only first confirmation succeeds; second receives 409 and must choose another seat |
| Duplicate retry | Send same body + same key twice in DevTools/Postman | Server returns original booking; no second booking created |
| Partial failure | Stop Notification :5003 and book another available seat | Booking still becomes CONFIRMED; notifications offline/pending, other services available |

**For your report:** take screenshots of the responsive design and network calls in browser Developer Tools (F12 > Network), especially successful POST, `409` conflict, `DELETE`, notification failure. Use Postman/pytest for truly concurrent requests because sequential UI clicks don't prove concurrency.

## Known backend limitations found in uploaded repository

- `notification-service/main.py` currently holds delivered messages in a **Python in-memory list**. They disappear when its process restarts. The Booking Service uses a database outbox for reliable *sending*; persistence on the Notification side would be an additional improvement.
- The provided `docker-compose.yml` runs PostgreSQL and Availability only. Booking and Notification must be run manually until Compose is expanded.
- This client uses a **demo user selector**, not login. Backend currently uses `user_id` as a prototype identity on cancellation; this does not provide real access control.
- Date, venue, concert art and ticket prices are derived from the API, except decorative CSS artwork which is deliberately generic. There are **no invented real concerts**.

## File map

- `src/App.jsx` — components, UI state, booking/cancellation flows, seat selection
- `src/api.js` — API methods, error parsing, safe timeout/retry contract
- `src/style.css` — visual design, glassmorphism, responsive layouts, hover states
- `vite.config.js` — Vite plugins, API gateways, port 3000
- `.env.example` — optional production API URLs

## Important group practice

Only submit **frontend/** changes to your `feature/frontend` Git branch. Don't overwrite the group's existing backend. Coordinate the actual API response format and server availability with Members 2–4, then have everyone verify the final deployment and diagrams.
