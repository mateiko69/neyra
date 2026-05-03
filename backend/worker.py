import time
from app.core.logging import setup_logging
from app.db.session import SessionLocal
from app.services.queue import dequeue, enqueue, dead_letter
from app.services.notifications import send_user_notification
from app.services.analytics import track_event
from app.services.retention.notification_engine import NotificationEngine

setup_logging()

_engine = NotificationEngine()


def handle_event(event: dict):
    db = SessionLocal()
    try:
        name = event["event_name"]
        payload = event["payload"]
        if name == "match_created":
            for uid in (payload.get("user_a_id"), payload.get("user_b_id")):
                if uid is None:
                    continue
                decision = _engine.decide_notification(db, int(uid), {"type": "new_match"})
                if not decision.send or decision.channel != "push":
                    continue
                body = decision.body if (decision.body or "").strip() else " "
                send_user_notification(db, int(uid), decision.title, body)
                track_event(
                    db,
                    "notification_sent",
                    user_id=int(uid),
                    payload={"event": {"type": "new_match"}, "decision": decision.to_dict(), "source": "worker"},
                )
        elif name == "message_sent":
            rid = payload.get("receiver_id")
            if rid is None:
                return
            decision = _engine.decide_notification(db, int(rid), {"type": "new_message"})
            if not decision.send or decision.channel != "push":
                return
            body = decision.body if (decision.body or "").strip() else " "
            send_user_notification(db, int(rid), decision.title, body)
            track_event(
                db,
                "notification_sent",
                user_id=int(rid),
                payload={"event": {"type": "new_message"}, "decision": decision.to_dict(), "source": "worker"},
            )
        # Future: handle ai_requests and analytics_events here.
    finally:
        db.close()

def main():
    while True:
        # Poll queues in priority order.
        event = dequeue("notifications", block_seconds=2) or dequeue("ai_requests", block_seconds=1) or dequeue("analytics_events", block_seconds=1)
        if not event:
            time.sleep(0.25)
            continue
        try:
            handle_event(event)
        except Exception as e:
            attempt = int(event.get("attempt", 0) or 0) + 1
            if attempt <= 3:
                enqueue(event.get("event_name", "unknown"), event.get("payload", {}), queue="notifications", attempt=attempt)
            else:
                dead_letter(event, reason=str(e))

if __name__ == "__main__":
    main()
