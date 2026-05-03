"""Public verification entrypoints: POST /verify/start, POST /verify/submit.

Implementation lives in `profiles.verification_*`; these routes are stable product URLs.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.models.user import User
from app.api.v1.endpoints.profiles import verification_selfie, verification_start

router = APIRouter()


@router.post("/start")
def verify_start(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return verification_start(current_user=current_user, db=db)


@router.post("/submit")
async def verify_submit(
    frames: list[UploadFile] | None = File(default=None),
    selfie: UploadFile | None = File(default=None),
    verification_source: str = Form(default="camera"),
    captured_at: str | None = Form(default=None),
    pose_challenge: str = Form(default=""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return await verification_selfie(
        frames=frames,
        selfie=selfie,
        verification_source=verification_source,
        captured_at=captured_at,
        pose_challenge=pose_challenge,
        current_user=current_user,
        db=db,
    )
