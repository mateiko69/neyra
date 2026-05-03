from types import SimpleNamespace

from app.api.v1.endpoints.messages import _attach_reactions, _message_to_json


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *_args, **_kwargs):
        return self

    def all(self):
        return list(self._rows)


class _FakeDb:
    def __init__(self, rows):
        self._rows = rows

    def query(self, _model):
        return _FakeQuery(self._rows)


def test_message_to_json_normalizes_relative_voice_url(monkeypatch):
    message = SimpleNamespace(
        id=42,
        sender_id=7,
        receiver_id=9,
        content="",
        reply_to_message_id=None,
        voice_url="/uploads/voice_7_note.webm",
        voice_mime="audio/webm",
        voice_duration_ms=1350,
        created_at=None,
    )

    payload = _message_to_json(message)

    assert payload["voice_url"] == "/uploads/voice_7_note.webm"
    assert payload["content"] == ""
    assert payload["voice_duration_ms"] == 1350


def test_attach_reactions_keeps_voice_only_messages_reactable():
    payload = [{"id": 42, "content": "", "voice_url": "http://api.test:8000/uploads/voice_7_note.webm"}]
    db = _FakeDb(
        [
          SimpleNamespace(message_id=42, user_id=7, emoji="like"),
          SimpleNamespace(message_id=42, user_id=9, emoji="like"),
          SimpleNamespace(message_id=42, user_id=7, emoji="heart"),
        ]
    )

    out = _attach_reactions(db, user_id=7, payload=payload)

    assert out[0]["reactions"] == {"like": 2, "heart": 1}
    assert out[0]["my_reactions"] == ["heart", "like"]
