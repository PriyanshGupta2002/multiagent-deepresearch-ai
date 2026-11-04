from fastapi import Cookie, Depends, status
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.dependencies import get_db
from app.core.exceptions import AppException
from app.core.security import decode_access_token
from app.modules.auth.models import User, UserSession


async def get_current_user(
    access_token: str | None = Cookie(
        default=None,
        alias="access_token",
    ),
    db: AsyncSession = Depends(get_db),
) -> User:

    credentials_error = AppException(
        message="Not authenticated",
        error_code="AUTH_NOT_AUTHENTICATED",
        status_code=status.HTTP_401_UNAUTHORIZED,
    )

    if not access_token:
        raise credentials_error

    try:
        payload = decode_access_token(access_token)

        if payload.get("type") != "access":
            raise credentials_error

        user_id = payload.get("sub")
        session_id = payload.get("sid")

        if not user_id or not session_id:
            raise credentials_error

    except JWTError:
        raise credentials_error

    result = await db.execute(
        select(UserSession).where(
            UserSession.id == session_id,
            UserSession.user_id == user_id,
        )
    )

    session = result.scalar_one_or_none()

    if not session or session.revoked_at is not None:
        raise credentials_error

    from datetime import datetime, timezone

    expires_at = session.expires_at

    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if expires_at <= datetime.now(timezone.utc):
        raise credentials_error

    result = await db.execute(select(User).where(User.id == user_id))

    user = result.scalar_one_or_none()

    if not user or not user.is_active:
        raise credentials_error

    return user
