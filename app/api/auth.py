from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import Dict, Any, Optional

from app.services.auth_service import auth_service

router = APIRouter()
security = HTTPBearer(auto_error=False)

class UserCreate(BaseModel):
    username: str
    password: str

class UserLogin(BaseModel):
    username: str
    password: str

async def get_current_user(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> Dict[str, Any]:
    """Dependency for authenticating requests and getting the current user."""
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = credentials.credentials
    user = auth_service.get_user_by_token(token)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user

async def get_current_user_optional(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> Optional[Dict[str, Any]]:
    """Optional dependency for getting the current user if authenticated."""
    if not credentials:
        return None
    return auth_service.get_user_by_token(credentials.credentials)

async def get_current_admin(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """Dependency for admin-only routes."""
    if user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions. Admin access required."
        )
    return user

@router.post("/register")
async def register(user: UserCreate):
    """User registration."""
    success = auth_service.register(user.username, user.password)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already exists or registration failed."
        )
    return {"message": "User registered successfully"}

@router.post("/login")
async def login(user: UserLogin):
    """User login. Returns an access token."""
    token = auth_service.login(user.username, user.password)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    user_info = auth_service.get_user_by_token(token)
    return {
        "access_token": token,
        "token_type": "bearer",
        "username": user_info["username"],
        "role": user_info["role"]
    }

@router.get("/me")
async def read_users_me(current_user: Dict[str, Any] = Depends(get_current_user)):
    """Get current user details."""
    return current_user

@router.post("/logout")
async def logout(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Invalidate current session token."""
    token = credentials.credentials
    auth_service.logout(token)
    return {"message": "Logged out successfully"}
