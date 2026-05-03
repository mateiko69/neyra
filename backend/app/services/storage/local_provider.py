from pathlib import Path
from urllib.parse import urlsplit

from app.core.config import settings
from app.services.storage.base import StorageProvider


class LocalStorageProvider(StorageProvider):
    def save(self, filename: str, content: bytes) -> str:
        upload_dir = Path(getattr(settings, "UPLOAD_DIR", None) or settings.LOCAL_UPLOAD_DIR)
        public_prefix = (getattr(settings, "UPLOAD_PUBLIC_PREFIX", None) or f"/{settings.LOCAL_UPLOAD_DIR}").strip()
        if not public_prefix.startswith("/"):
            public_prefix = f"/{public_prefix}"

        base = upload_dir
        base.mkdir(parents=True, exist_ok=True)
        target = base / filename
        target.write_bytes(content)
        # Relative path so browsers resolve via NEXT_PUBLIC_BACKEND_URL / PUBLIC_BACKEND_URL (avoids wrong absolute host in Docker).
        return f"{public_prefix}/{filename}"

    def delete(self, url_or_key: str) -> None:
        raw = (url_or_key or "").strip()
        if not raw:
            return
        upload_dir = Path(getattr(settings, "UPLOAD_DIR", None) or settings.LOCAL_UPLOAD_DIR)
        public_prefix = (getattr(settings, "UPLOAD_PUBLIC_PREFIX", None) or f"/{settings.LOCAL_UPLOAD_DIR}").strip()
        if not public_prefix.startswith("/"):
            public_prefix = f"/{public_prefix}"

        # Accept either a relative public URL (/uploads/..) or full URL (http://..../uploads/..).
        path = urlsplit(raw).path if "://" in raw else raw
        if not path.startswith(public_prefix + "/"):
            return
        filename = path[len(public_prefix) + 1 :].strip("/")
        if not filename:
            return
        target = upload_dir / filename
        try:
            if target.exists() and target.is_file():
                target.unlink()
        except Exception:
            return
