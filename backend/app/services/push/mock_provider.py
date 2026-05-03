from app.services.push.base import PushProvider

class MockPushProvider(PushProvider):
    def send(self, token: str, title: str, body: str) -> dict:
        return {"status": "mock_sent", "token": token, "title": title, "body": body}
