from __future__ import annotations

import math
from dataclasses import dataclass
from io import BytesIO

import requests
from PIL import Image


@dataclass(frozen=True)
class VisualEmbedding:
    """Lightweight, privacy-preserving visual embedding.

    MVP implementation (CPU-only):
    - Uses a perceptual embedding derived from the primary profile photo
    - No raw face data is stored; only a numeric vector is persisted
    - Designed to be replaced with a true face-embedding model later
    """

    vector: list[float]

    def serialize(self) -> str:
        return ",".join(f"{x:.6f}" for x in self.vector)

    @staticmethod
    def deserialize(value: str) -> VisualEmbedding | None:
        if not value:
            return None
        parts = [p.strip() for p in value.split(",") if p.strip()]
        if len(parts) < 8:
            return None
        out: list[float] = []
        for p in parts:
            try:
                out.append(float(p))
            except ValueError:
                return None
        return VisualEmbedding(out)


def _l2_normalize(v: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / norm for x in v]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    return sum(x * y for x, y in zip(a, b))


def _image_to_embedding(img: Image.Image) -> VisualEmbedding:
    # Small, stable embedding: 32x32 grayscale pixels + coarse color averages.
    img = img.convert("RGB")
    small = img.resize((32, 32), Image.BICUBIC)
    pixels = list(small.getdata())
    # grayscale vector
    gray: list[float] = []
    r_sum = g_sum = b_sum = 0.0
    for (r, g, b) in pixels:
        r_sum += r
        g_sum += g
        b_sum += b
        gray.append((0.299 * r + 0.587 * g + 0.114 * b) / 255.0)
    # add coarse global color features (style/vibe weighting)
    n = float(len(pixels) or 1)
    color = [(r_sum / n) / 255.0, (g_sum / n) / 255.0, (b_sum / n) / 255.0]
    vec = _l2_normalize(gray + color)
    return VisualEmbedding(vec)


def compute_visual_embedding_from_url(url: str, timeout_s: float = 5.0) -> VisualEmbedding | None:
    if not url:
        return None
    u = url.strip()
    if not u:
        return None
    try:
        resp = requests.get(u, timeout=timeout_s)
        resp.raise_for_status()
        img = Image.open(BytesIO(resp.content))
        return _image_to_embedding(img)
    except Exception:
        return None


def compute_visual_embedding_from_bytes(blob: bytes) -> VisualEmbedding | None:
    if not blob:
        return None
    try:
        img = Image.open(BytesIO(blob))
        return _image_to_embedding(img)
    except Exception:
        return None

