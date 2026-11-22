FROM python:3.12-slim

# Logs go straight to `docker compose logs` (useful as report evidence)
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Code plus sql/ (the service applies sql/001_notification_schema.sql at start-up)
COPY . .

# Do not run as root inside the container
RUN adduser --disabled-password --gecos "" --no-create-home appuser
USER appuser

EXPOSE 5003

# 0.0.0.0 so the service is reachable from outside the container
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "5003"]
