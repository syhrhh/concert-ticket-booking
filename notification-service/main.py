from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="Notification Service")

notifications = []

class NotificationRequest(BaseModel):
    booking_id: str
    user_id: int
    type: str
    message: str

@app.get("/health")
def health():
    return {"service": "notification", "status": "UP"}

@app.post("/api/notifications")
def create_notification(request: NotificationRequest):
    notification = {
        "notification_id": len(notifications) + 1,
        **request.model_dump(),
        "status": "SENT"
    }
    notifications.append(notification)
    print(notification)
    return notification

@app.get("/api/users/{user_id}/notifications")
def get_notifications(user_id: int):
    return [n for n in notifications if n["user_id"] == user_id]
