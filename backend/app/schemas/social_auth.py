from pydantic import BaseModel, Field


class SocialAuthOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    redirect_path: str


class GoogleTokenIn(BaseModel):
    id_token: str = Field(..., min_length=20)


class AppleTokenIn(BaseModel):
    id_token: str = Field(..., min_length=20)
    first_name: str | None = Field(default=None, max_length=120)
    last_name: str | None = Field(default=None, max_length=120)


class FacebookTokenIn(BaseModel):
    access_token: str = Field(..., min_length=20)
