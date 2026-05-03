from sqlalchemy.orm import Session
from app.models.device_token import DeviceToken
from app.models.user import User
from app.services.push.service import get_push_provider

def send_user_notification(db: Session, user_id: int, title: str, body: str):
    u = db.query(User).filter(User.id == int(user_id)).first()
    if u and bool(getattr(u, "is_demo", False)):
        return []
    provider = get_push_provider()
    tokens = db.query(DeviceToken).filter(DeviceToken.user_id == user_id).all()
    results = []
    for row in tokens:
        results.append(provider.send(row.token, title, body))
    return results
