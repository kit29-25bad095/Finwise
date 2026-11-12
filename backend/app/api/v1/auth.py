from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.database import get_db_session
from app.core.rate_limiter import auth_rate_limiter
from app.services.auth_service import AuthService
from app.services.tenant_service import TenantService
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse
from app.schemas.user import UserRead
from app.schemas.tenant import TenantMembershipRead
from app.models.user import User
from app.api.deps import get_current_user

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(
    request: Request,
    req: RegisterRequest,
    session: Session = Depends(get_db_session)
):
    auth_rate_limiter.check_rate_limit(request)
    client_ip = request.client.host if request.client else None
    return AuthService.register_user_with_tenant(session, req, ip_address=client_ip)


@router.post("/login", response_model=TokenResponse)
def login(
    request: Request,
    req: LoginRequest,
    session: Session = Depends(get_db_session)
):
    auth_rate_limiter.check_rate_limit(request)
    user = AuthService.authenticate_user(session, req.email, req.password)
    if not user:
        auth_rate_limiter.record_failure(request)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
            headers={"WWW-Authenticate": "Bearer"}
        )

    auth_rate_limiter.record_success(request)

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

    token = AuthService.create_token_for_user(
        user=user,
        tenant_id=selected_membership.tenant_id,
        role=selected_membership.role
    )

    return TokenResponse(
        access_token=token,
        token_type="bearer",
        user=UserRead.model_validate(user),
        active_tenant_id=selected_membership.tenant_id,
        active_role=selected_membership.role,
        memberships=[TenantMembershipRead.model_validate(m) for m in memberships]
    )


@router.get("/me", response_model=UserRead)
def get_current_user_profile(
    current_user: User = Depends(get_current_user)
):
    return UserRead.model_validate(current_user)
