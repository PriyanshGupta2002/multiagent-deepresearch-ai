from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta, timezone
from app.core.config import settings
from app.core.exceptions import AppException
from app.modules.auth.models import User, UserSession
from app.modules.auth.schemas import RegisterRequest
from app.core.security import hash_password, verify_password
from app.core.security import (
    create_refresh_token,
    hash_refresh_token,
)
from fastapi import status


async def get_user_by_email(
    db: AsyncSession,
    email: str,
) -> User | None:
    result = await db.execute(select(User).where(User.email == email.lower()))
    return result.scalar_one_or_none()


async def register_user(
    db: AsyncSession,
    data: RegisterRequest,
) -> User:
    existing_user = await get_user_by_email(db, data.email)

    if existing_user:
        raise AppException(
            message="Email already registered",
            error_code="AUTH_EMAIL_ALREADY_REGISTERED",
            status_code=status.HTTP_409_CONFLICT,
        )

    user = User(
        email=data.email.lower(),
        full_name=data.full_name,
        hashed_password=hash_password(data.password),
    )

    db.add(user)

    await db.commit()
    await db.refresh(user)

    return user


async def authenticate_user(
    db: AsyncSession,
    email: str,
    password: str,
) -> User | None:
    user = await get_user_by_email(db, email)

    if not user:
        return None

    if not user.is_active:
        return None

    if not verify_password(password, user.hashed_password):
        return None

    return user


async def create_user_session(
    db: AsyncSession,
    user: User,
) -> tuple[UserSession, str]:

    session_id = __import__("uuid").uuid4().__str__()

    refresh_token = create_refresh_token(session_id)

    session = UserSession(
        id=session_id,
        user_id=user.id,
        refresh_token_hash=hash_refresh_token(refresh_token),
        expires_at=datetime.now(timezone.utc)
        + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )

    db.add(session)
    await db.commit()
    await db.refresh(session)

    return session, refresh_token


async def rotate_refresh_token(
    db: AsyncSession,
    refresh_token: str,
) -> tuple[User, UserSession, str] | None:

    try:
        session_id, _ = refresh_token.split(".", 1)
    except ValueError:
        return None

    result = await db.execute(
        select(UserSession).where(UserSession.id == session_id).with_for_update()
    )

    session = result.scalar_one_or_none()

    if not session:
        return None

    now = datetime.now(timezone.utc)

    if session.revoked_at is not None:
        return None

    # Reuse detection: an old token must not be accepted again.
    if session.refresh_token_hash != hash_refresh_token(refresh_token):
        session.revoked_at = now
        await db.commit()
        return None

    expires_at = session.expires_at

    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if expires_at <= now:
        session.revoked_at = now
        await db.commit()
        return None

    result = await db.execute(select(User).where(User.id == session.user_id))

    user = result.scalar_one_or_none()

    if not user or not user.is_active:
        session.revoked_at = now
        await db.commit()
        return None

    new_refresh_token = create_refresh_token(session.id)

    session.refresh_token_hash = hash_refresh_token(new_refresh_token)
    session.last_used_at = now

    await db.commit()
    await db.refresh(session)

    return user, session, new_refresh_token


async def revoke_user_session(
    db: AsyncSession,
    refresh_token: str | None,
) -> None:

    if not refresh_token:
        return

    try:
        session_id, _ = refresh_token.split(".", 1)
    except ValueError:
        return

    result = await db.execute(
        select(UserSession).where(UserSession.id == session_id).with_for_update()
    )

    session = result.scalar_one_or_none()

    if not session or session.revoked_at is not None:
        return

    if session.refresh_token_hash == hash_refresh_token(refresh_token):
        session.revoked_at = datetime.now(timezone.utc)
        await db.commit()
