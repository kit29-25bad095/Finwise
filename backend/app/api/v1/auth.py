import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db_session
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    TokenRevocationStore,
)
from app.services.auth_service import AuthService
from app.services.tenant_service import TenantService
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, RefreshTokenRequest
from app.schemas.user import UserRead
from app.schemas.tenant import TenantMembershipRead
from app.models.user import User
from app.api.deps import get_current_user, security_scheme

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(
    request: Request,
    response: Response,
    req: RegisterRequest,
    session: Session = Depends(get_db_session)
):
    client_ip = request.client.host if request.client else None
    token_resp = AuthService.register_user_with_tenant(session, req, ip_address=client_ip)
    
    # Also generate refresh token
    refresh_token = create_refresh_token(
        subject=token_resp.user.id,
        tenant_id=str(token_resp.active_tenant_id) if token_resp.active_tenant_id else None
    )
    token_resp.refresh_token = refresh_token

    response.set_cookie(
        key="access_token",
        value=token_resp.access_token,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    )
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400
    )
    return token_resp


@router.post("/login", response_model=TokenResponse)
def login(
    req: LoginRequest,
    response: Response,
    session: Session = Depends(get_db_session)
):
    user = AuthService.authenticate_user(session, req.email, req.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
            headers={"WWW-Authenticate": "Bearer"}
        )

    memberships = TenantService.get_user_memberships(session, user.id)
    if not memberships:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is not associated with any active business tenant."
        )

    selected_membership = None
    if req.tenant_id:
        for m in memberships:
            if m.tenant_id == req.tenant_id:
                selected_membership = m
                break
        if not selected_membership:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User does not have access to the specified tenant."
            )
    else:
        selected_membership = next((m for m in memberships if m.is_default), memberships[0])

    access_token = AuthService.create_token_for_user(
        user=user,
        tenant_id=selected_membership.tenant_id,
        role=selected_membership.role
    )
    refresh_token = create_refresh_token(
        subject=user.id,
        tenant_id=str(selected_membership.tenant_id)
    )

    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    )
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400
    )

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        user=UserRead.model_validate(user),
        active_tenant_id=selected_membership.tenant_id,
        active_role=selected_membership.role,
        memberships=[TenantMembershipRead.model_validate(m) for m in memberships]
    )


@router.post("/refresh", response_model=TokenResponse)
def refresh_token_endpoint(
    request: Request,
    response: Response,
    req_body: Optional[RefreshTokenRequest] = None,
    session: Session = Depends(get_db_session)
):
    token_str: Optional[str] = None
    if req_body and req_body.refresh_token:
        token_str = req_body.refresh_token
    elif request.cookies.get("refresh_token"):
        token_str = request.cookies.get("refresh_token")

    if not token_str:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token was not provided.",
            headers={"WWW-Authenticate": "Bearer"}
        )

    payload = decode_refresh_token(token_str)
    if not payload or "sub" not in payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid, expired, or revoked refresh token.",
            headers={"WWW-Authenticate": "Bearer"}
        )

    try:
        user_id = uuid.UUID(payload["sub"])
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed token subject identifier."
        )

    user = session.execute(
        select(User).where(User.id == user_id, User.is_active == True)
    ).scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account does not exist or has been deactivated."
        )

    memberships = TenantService.get_user_memberships(session, user.id)
    if not memberships:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is not associated with any active business tenant."
        )

    tenant_id_str = payload.get("tenant_id")
    selected_membership = None
    if tenant_id_str:
        try:
            t_id = uuid.UUID(tenant_id_str)
            selected_membership = next((m for m in memberships if m.tenant_id == t_id), None)
        except ValueError:
            pass

    if not selected_membership:
        selected_membership = next((m for m in memberships if m.is_default), memberships[0])

    # Rotate refresh token: revoke consumed token and generate a fresh pair
    TokenRevocationStore.revoke_token(token_str)

    new_access_token = create_access_token(
        subject=user.id,
        tenant_id=str(selected_membership.tenant_id),
        role=selected_membership.role
    )
    new_refresh_token = create_refresh_token(
        subject=user.id,
        tenant_id=str(selected_membership.tenant_id)
    )

    response.set_cookie(
        key="access_token",
        value=new_access_token,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    )
    response.set_cookie(
        key="refresh_token",
        value=new_refresh_token,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400
    )

    return TokenResponse(
        access_token=new_access_token,
        refresh_token=new_refresh_token,
        token_type="bearer",
        user=UserRead.model_validate(user),
        active_tenant_id=selected_membership.tenant_id,
        active_role=selected_membership.role,
        memberships=[TenantMembershipRead.model_validate(m) for m in memberships]
    )


@router.post("/logout", status_code=status.HTTP_200_OK)
def logout(
    request: Request,
    response: Response,
    auth: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme),
    current_user: User = Depends(get_current_user)
):
    # Revoke access token if provided in header
    if auth and auth.credentials:
        TokenRevocationStore.revoke_token(auth.credentials)
    # Revoke access token if in cookie
    cookie_access = request.cookies.get("access_token")
    if cookie_access:
        TokenRevocationStore.revoke_token(cookie_access)

    # Revoke refresh token if in cookie
    cookie_refresh = request.cookies.get("refresh_token")
    if cookie_refresh:
        TokenRevocationStore.revoke_token(cookie_refresh)

    # Clear auth cookies
    response.delete_cookie(key="access_token")
    response.delete_cookie(key="refresh_token")

    return {"message": "Successfully logged out. Tokens have been revoked."}


@router.get("/me", response_model=UserRead)
def get_current_user_profile(
    current_user: User = Depends(get_current_user)
):
    return UserRead.model_validate(current_user)

