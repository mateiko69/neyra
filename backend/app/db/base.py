from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    pass


# Ensure model modules are imported so Base.metadata is fully populated
# in test environments that call Base.metadata.create_all() directly.
try:
    import app.models  # noqa: F401
except Exception:
    # Avoid hard failures during partial imports or tooling.
    pass
