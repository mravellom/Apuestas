"""Rate limiting configuration."""

from app.config import settings

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["100/minute"],
    enabled=settings.APP_ENV != "testing",
)
