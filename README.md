# Concert Ticket Booking Distributed System

Distributed Systems group assignment for XBCS3024N.

## Architecture

- Frontend: React + Vite
- Booking Service: FastAPI, port 5001
- Availability Service: FastAPI, port 5002
- Notification Service: FastAPI, port 5003
- Database: PostgreSQL, port 5432
- Communication: HTTP/REST + JSON

## Repository Structure

```text
concert-ticket-booking/
├── frontend/
├── booking-service/
├── availability-service/
├── notification-service/
├── database/
├── tests/
├── docker-compose.yml
├── .gitignore
└── README.md
```

## Service Responsibilities

### Frontend
- View concerts
- View seats
- Book a seat
- View bookings
- Cancel bookings
- Display status and errors

### Booking Service
- Create bookings
- View bookings
- Cancel bookings
- Handle duplicate requests
- Coordinate with Availability and Notification services

### Availability Service
- View concerts
- View seats
- Check seat availability
- Reserve and release seats
- Prevent conflicting bookings

### Notification Service
- Record booking confirmations
- Record cancellations
- Support partial-failure demonstration

## Default Ports

| Component | Port |
|---|---:|
| Frontend | 3000 |
| Booking Service | 5001 |
| Availability Service | 5002 |
| Notification Service | 5003 |
| PostgreSQL | 5432 |

## Recommended Team Branches

- `feature/frontend`
- `feature/booking-service`
- `feature/availability-service`
- `feature/notification-testing`

Do not commit major work directly to `main`. Use a branch and Pull Request.

## Setup

### 1. Clone
```bash
git clone <repository-url>
cd concert-ticket-booking
```

### 2. Backend services

Create a virtual environment if preferred, then install requirements in each service folder.

Example:
```bash
cd booking-service
pip install -r requirements.txt
uvicorn main:app --reload --port 5001
```

Run the other services in separate terminals:
```bash
cd availability-service
uvicorn main:app --reload --port 5002
```

```bash
cd notification-service
uvicorn main:app --reload --port 5003
```

### 3. Frontend
```bash
cd frontend
npm install
npm run dev
```

### 4. PostgreSQL
You can install PostgreSQL locally or use Docker Compose later.

## Main Demo Scenarios

1. Successful booking
2. Conflicting booking rejected
3. Duplicate request handled
4. Notification service failure while booking remains usable
