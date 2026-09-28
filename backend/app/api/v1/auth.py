"""
Authentication API endpoints.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_auth_service, get_current_user
from app.core.exceptions import AuthenticationError, ConflictError
from app.models import User
from app.schemas import LoginRequest, Token, UserCreate, UserOut
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(payload: UserCreate, auth_service: AuthService = Depends(get_auth_service)):
    try:
        user = auth_service.register(
            email=payload.email,
            full_name=payload.full_name,
            password=payload.password,
        )
        # If a custom role was passed in payload, assign it
        if hasattr(payload, "role") and payload.role:
            user.role = payload.role.lower()
            auth_service.user_repo.commit()
            auth_service.user_repo.refresh(user)
        return user
    except ConflictError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


@router.post("/login", response_model=Token)
def login(payload: LoginRequest, auth_service: AuthService = Depends(get_auth_service)):
    try:
        access_token = auth_service.login(email=payload.email, password=payload.password)
        return Token(access_token=access_token)
    except AuthenticationError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        )


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user
