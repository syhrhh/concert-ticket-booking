"""Runtime configuration for the Notification Service.

Everything is read from environment variables so the same code runs locally,
in the tests and inside Docker. Defaults match the ports in the project README.
"""
import os

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://concert_user:concert_pass@localhost:5432/concert_booking",
)
DB_POOL_MAX = int(os.getenv("DB_POOL_MAX", "10"))
DB_CONNECT_TIMEOUT = float(os.getenv("DB_CONNECT_TIMEOUT", "30"))

# Browser origins allowed to call this API directly (the React dev server).
CORS_ORIGINS = [
    o.strip()
    for o in os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",")
    if o.strip()
]

# --- Fault injection (DEMO ONLY) -----------------------------------------
# Lets us show failures without editing code:
#   off   -> normal behaviour (default)
#   error -> every POST /api/notifications answers 503 (service "broken")
#   slow  -> the notification is saved, but the reply is delayed by
#            FAULT_DELAY_SECONDS, longer than the Booking Service's 2 s timeout.
#            This simulates "the work was done but the response was lost",
#            the case that makes duplicate detection necessary.
FAULT_MODE = os.getenv("FAULT_MODE", "off").strip().lower()
FAULT_DELAY_SECONDS = float(os.getenv("FAULT_DELAY_SECONDS", "4"))
