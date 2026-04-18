"""Idempotently provision a Telegram alert for an existing user.

Usage (inside the api container):
    docker compose exec -T \
        -e ALERT_USER_EMAIL=you@example.com \
        -e ALERT_CHAT_ID=123456789 \
        -e ALERT_MIN_VALUE=0.03 \
        api python scripts/seed_alert.py

If the user doesn't exist, it is created with a random password (printed once).
Re-running updates the existing alert row instead of duplicating it.
"""

import asyncio
import os
import secrets
import sys
from decimal import Decimal

from sqlalchemy import select

import bcrypt

from app.database import async_session
from app.models.alert import AlertConfig
from app.models.user import User


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


async def main() -> int:
    email = os.environ.get("ALERT_USER_EMAIL", "owner@valuebet.local")
    chat_id = os.environ.get("ALERT_CHAT_ID")
    min_value = Decimal(os.environ.get("ALERT_MIN_VALUE", "0.03"))
    channel = os.environ.get("ALERT_CHANNEL", "telegram")

    if not chat_id:
        print("ERROR: ALERT_CHAT_ID is required", file=sys.stderr)
        return 1

    async with async_session() as db:
        user = (
            await db.execute(select(User).where(User.email == email))
        ).scalar_one_or_none()

        if user is None:
            password = secrets.token_urlsafe(12)[:32]
            user = User(
                email=email,
                username=email.split("@")[0],
                hashed_password=hash_password(password),
                role="admin",
            )
            db.add(user)
            await db.flush()
            print(f"Created user {email} (password: {password})")

        alert = (
            await db.execute(
                select(AlertConfig).where(
                    AlertConfig.user_id == user.id,
                    AlertConfig.channel == channel,
                )
            )
        ).scalar_one_or_none()

        if alert is None:
            alert = AlertConfig(
                user_id=user.id,
                channel=channel,
                destination=chat_id,
                min_value_pct=min_value,
                active=True,
            )
            db.add(alert)
            action = "created"
        else:
            alert.destination = chat_id
            alert.min_value_pct = min_value
            alert.active = True
            action = "updated"

        await db.commit()
        print(
            f"Alert {action}: user={email} channel={channel} "
            f"chat_id={chat_id} min_value={min_value}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
