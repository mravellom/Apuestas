from fastapi import APIRouter, HTTPException, Request, status

from app.api.deps import DB, CurrentUser
from app.rate_limit import limiter
from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from app.services.auth_service import (
    authenticate_user,
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    get_user_by_email,
    get_user_by_username,
    register_user,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
async def register(request: Request, request_body: RegisterRequest, db: DB):
    if await get_user_by_email(db, request_body.email):
        raise HTTPException(status_code=400, detail="Email already registered")
    if await get_user_by_username(db, request_body.username):
        raise HTTPException(status_code=400, detail="Username already taken")

    user = await register_user(db, request_body.email, request_body.username, request_body.password)
    return user


@router.post("/login", response_model=TokenResponse)
@limiter.limit("10/minute")
async def login(request: Request, request_body: LoginRequest, db: DB):
    user = await authenticate_user(db, request_body.email, request_body.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    user_id = str(user.id)
    return TokenResponse(
        access_token=create_access_token(user_id),
        refresh_token=create_refresh_token(user_id),
    )


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit("20/minute")
async def refresh(request: Request, request_body: RefreshRequest, db: DB):
    user_id = decode_refresh_token(request_body.refresh_token)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    return TokenResponse(
        access_token=create_access_token(user_id),
        refresh_token=create_refresh_token(user_id),
    )


@router.get("/me", response_model=UserResponse)
async def me(current_user: CurrentUser):
    return current_user
