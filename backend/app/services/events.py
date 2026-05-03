from app.services.queue import enqueue

def publish_event(name: str, payload: dict):
    # Default to notifications queue for backwards compatibility.
    enqueue(name, payload, queue="notifications")
