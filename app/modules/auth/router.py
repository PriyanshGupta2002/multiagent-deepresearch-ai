from fastapi import (
    APIRouter,
    Depends,
    Response,
    Cookie,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.dependencies import get_db
from app.core.exceptions import AppException
from app.core.security import create_access_token
from app.modules.auth.models import User
from app.modules.auth.schemas import (
    RegisterRequest,
    LoginRequest,
    UserResponse,
)
from app.modules.auth.services import (
    register_user,
    authenticate_user,
    create_user_session,
    rotate_refresh_token,
    revoke_user_session,
)
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.utils import (
    set_auth_cookies,
    clear_auth_cookies,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register(
    data: RegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    return await register_user(db, data)


@router.post("/login", response_model=UserResponse)
async def login(
    data: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    user = await authenticate_user(
        db,
        data.email,
        data.password,
    )

    if not user:
        raise AppException(
            message="Invalid email or password",
            error_code="AUTH_INVALID_CREDENTIALS",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    session, refresh_token = await create_user_session(db, user)

    access_token = create_access_token(
        user_id=user.id,
        session_id=session.id,
    )

    set_auth_cookies(
        response,
        access_token,
        refresh_token,
    )

    return user


@router.post("/refresh", response_model=UserResponse)
async def refresh(
    response: Response,
    refresh_token: str | None = Cookie(
        default=None,
        alias="refresh_token",
    ),
    db: AsyncSession = Depends(get_db),
):
    if not refresh_token:
        raise AppException(
            message="Refresh token missing",
            error_code="AUTH_REFRESH_TOKEN_MISSING",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    result = await rotate_refresh_token(db, refresh_token)

    if not result:
        clear_auth_cookies(response)

        raise AppException(
            message="Invalid or expired refresh token",
            error_code="AUTH_INVALID_REFRESH_TOKEN",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    user, session, new_refresh_token = result

    access_token = create_access_token(
        user_id=user.id,
        session_id=session.id,
    )

    set_auth_cookies(
        response,
        access_token,
        new_refresh_token,
    )

    return user


@router.post("/logout")
async def logout(
    response: Response,
    refresh_token: str | None = Cookie(
        default=None,
        alias="refresh_token",
    ),
    db: AsyncSession = Depends(get_db),
):
    await revoke_user_session(db, refresh_token)

    clear_auth_cookies(response)

    return {"message": "Successfully logged out"}


@router.get("/me", response_model=UserResponse)
async def get_me(
    current_user: User = Depends(get_current_user),
):
    return current_user
