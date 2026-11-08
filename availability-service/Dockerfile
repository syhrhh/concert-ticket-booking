FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

EXPOSE 5002

# 0.0.0.0 so the service is reachable from outside the container
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "5002"]
