import json
import logging
import secrets
import urllib.parse
import datetime
from typing import List, Optional
import httpx
from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from fastapi.responses import RedirectResponse
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError

from database import get_db
from models import User
from schemas import (
    UserRegister, 
    UserResponse, 
    UserProfileUpdate,
    RegisterSuccessResponse, 
    UserLogin, 
    GoogleOAuthRequest,
    Token
)
from security import hash_password, verify_password, create_access_token
from config import settings
from services.habit_score_service import calculate_habit_score_snapshot
from services.sleep_quality_service import calculate_sleep_quality

# Optional Google Auth library verification
try:
    from google.oauth2 import id_token
    from google.auth.transport import requests as google_requests
    HAS_GOOGLE_AUTH = True
except ImportError:
    HAS_GOOGLE_AUTH = False

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["Authentication"])


@router.get("/config", summary="Public client authentication configuration")
def get_auth_config():
    """Returns non-sensitive public configuration (Google Client ID, frontend URL) for frontend hydration."""
    return {
        "google_client_id": settings.GOOGLE_CLIENT_ID,
        "frontend_url": settings.FRONTEND_URL
    }


@router.post(
    "/register", 
    response_model=RegisterSuccessResponse, 
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
    description="Backend Process:\n1. Receive request\n2. Validate data\n3. Check email already exists\n4. Hash password using BCrypt\n5. Save into database\n6. Return success response"
)
def register_user(payload: UserRegister, db: Session = Depends(get_db)):
    """
    Step 2: Registration API endpoint matching screenshot specification.
    """
    try:
        # 3. Check if email already exists in PostgreSQL DB
        existing_user = db.query(User).filter(User.email == payload.email.lower()).first()
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"An account with email '{payload.email}' already exists."
            )

        # 4. Hash password using BCrypt
        hashed_pwd = hash_password(payload.password)

        # 5. Save into database
        new_user = User(
            name=payload.name.strip(),
            email=payload.email.lower().strip(),
            password=hashed_pwd,
            role="USER",
            provider=payload.provider.strip() if payload.provider else "LOCAL"
        )
        
        db.add(new_user)
        db.commit()
        db.refresh(new_user)

        # 6. Return success response
        return RegisterSuccessResponse(
            status="success",
            message="User registered successfully in PostgreSQL database",
            data=UserResponse.model_validate(new_user)
        )

    except OperationalError as e:
        logger.error(f"PostgreSQL connection error during registration: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not connect to PostgreSQL database. Please check PostgreSQL password in backend/.env or start PostgreSQL service."
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error during registration: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal registration error: {str(e)}"
        )

@router.post("/login", response_model=Token, summary="Authenticate user & return JWT token")
def login_user(payload: UserLogin, db: Session = Depends(get_db)):
    """
    Authenticates registered user credentials against PostgreSQL DB.
    """
    try:
        user = db.query(User).filter(User.email == payload.email.lower()).first()
        if not user or not verify_password(payload.password, user.password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        access_token = create_access_token(data={"sub": user.email, "role": user.role, "id": user.id})
        return Token(
            access_token=access_token,
            token_type="bearer",
            user=UserResponse.model_validate(user)
        )
    except OperationalError as e:
        logger.error(f"PostgreSQL connection error during login: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not connect to PostgreSQL database. Please check PostgreSQL password in backend/.env or start PostgreSQL service."
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error during login: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal login error: {str(e)}"
        )

@router.post("/google", response_model=Token, summary="Google OAuth Authentication & Registration")
def google_oauth_login(payload: GoogleOAuthRequest, db: Session = Depends(get_db)):
    """
    Authenticates or Registers user via Google OAuth 2.0.
    1. Verifies Google ID Token (or accepts credential payload).
    2. Saves/Updates user in PostgreSQL with provider='GOOGLE'.
    3. Returns JWT token and User response object.
    """
    email = None
    name = None

    # Verify Google ID Token if token provided
    if payload.token:
        if HAS_GOOGLE_AUTH and "demo" not in settings.GOOGLE_CLIENT_ID:
            try:
                id_info = id_token.verify_oauth2_token(
                    payload.token, 
                    google_requests.Request(), 
                    settings.GOOGLE_CLIENT_ID
                )
                email = id_info.get("email")
                name = id_info.get("name") or email.split("@")[0]
            except Exception as ve:
                logger.warning(f"Google ID Token verification fallback: {ve}")

    # Fallback to email/name from payload
    if not email and payload.email:
        email = payload.email.lower().strip()
        name = payload.name.strip() if payload.name else email.split("@")[0]

    if not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google OAuth authentication failed: Missing valid email or Google token."
        )

    if payload.role and payload.role.upper() == "ADMIN":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Google OAuth is disabled for Administrator accounts. Please sign in using Administrator database credentials."
        )

    try:
        user = db.query(User).filter(User.email == email.lower()).first()

        if user:
            if user.role.upper() == "ADMIN":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Google OAuth is disabled for Administrator accounts. Please sign in using Administrator database credentials."
                )
            # Existing user - update provider if needed
            if user.provider != "GOOGLE":
                user.provider = "GOOGLE"
                db.commit()
                db.refresh(user)
        else:
            # Register new user from Google OAuth
            random_password = secrets.token_urlsafe(16)
            hashed_pwd = hash_password(random_password)

            user = User(
                name=name or "Google User",
                email=email.lower(),
                password=hashed_pwd,
                role=payload.role.strip() if payload.role else "USER",
                provider="GOOGLE"
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            logger.info(f"Registered new Google OAuth user in PostgreSQL: {email}")

        access_token = create_access_token(data={"sub": user.email, "role": user.role, "id": user.id})
        return Token(
            access_token=access_token,
            token_type="bearer",
            user=UserResponse.model_validate(user)
        )

    except OperationalError as e:
        logger.error(f"PostgreSQL connection error during Google OAuth: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection error during Google OAuth."
        )


@router.get("/google/login", summary="Initiate Google OAuth 2.0 Authorization Flow")
def google_oauth_login_redirect(request: Request, role: str = "USER"):
    """
    Redirects the client to Google's OAuth 2.0 consent screen.
    Google will redirect back to the Railway backend /api/auth/google/callback endpoint.
    """
    client_id = settings.GOOGLE_CLIENT_ID
    if not client_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google OAuth is not configured on this server. Please provide GOOGLE_CLIENT_ID."
        )
    
    # Callback points to the Railway backend endpoint
    redirect_uri = settings.GOOGLE_REDIRECT_URI
    if not redirect_uri:
        # Fallback to current backend base URL + callback path
        redirect_uri = f"{str(request.base_url).rstrip('/')}/api/auth/google/callback"

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "online",
        "state": role
    }
    google_auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{urllib.parse.urlencode(params)}"
    return RedirectResponse(url=google_auth_url)


@router.get("/google/callback", summary="Google OAuth 2.0 Backend Callback Endpoint")
async def google_oauth_callback(
    request: Request,
    code: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
    state: Optional[str] = Query("USER"),
    db: Session = Depends(get_db)
):
    """
    Callback endpoint that receives authorization code from Google, exchanges it for user credentials,
    finds or registers the user in PostgreSQL, and redirects to the Vercel frontend dashboard with session tokens.
    """
    frontend_base = settings.FRONTEND_URL.rstrip('/') if settings.FRONTEND_URL else "http://localhost:8000"
    
    if error or not code:
        logger.warning(f"Google OAuth callback received error or no code: error={error}")
        return RedirectResponse(url=f"{frontend_base}/login.html?error=google_auth_failed")

    redirect_uri = settings.GOOGLE_REDIRECT_URI
    if not redirect_uri:
        redirect_uri = str(request.url).split("?")[0]

    token_url = "https://oauth2.googleapis.com/token"
    token_payload = {
        "code": code,
        "client_id": settings.GOOGLE_CLIENT_ID,
        "client_secret": settings.GOOGLE_CLIENT_SECRET,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code"
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            token_resp = await client.post(token_url, data=token_payload)
            if token_resp.status_code != 200:
                logger.error(f"Google OAuth token exchange failed: {token_resp.text}")
                return RedirectResponse(url=f"{frontend_base}/login.html?error=token_exchange_failed")
            
            token_data = token_resp.json()
            google_access_token = token_data.get("access_token")

            # Fetch user profile info
            userinfo_resp = await client.get(
                "https://www.googleapis.com/oauth2/v2/userinfo",
                headers={"Authorization": f"Bearer {google_access_token}"}
            )
            if userinfo_resp.status_code != 200:
                logger.error(f"Google OAuth userinfo fetch failed: {userinfo_resp.text}")
                return RedirectResponse(url=f"{frontend_base}/login.html?error=userinfo_failed")
            
            userinfo = userinfo_resp.json()
            email = (userinfo.get("email") or "").lower().strip()
            name = (userinfo.get("name") or userinfo.get("given_name") or email.split("@")[0]).strip()

            if not email:
                return RedirectResponse(url=f"{frontend_base}/login.html?error=missing_email")

            # Look up or create user in PostgreSQL
            user = db.query(User).filter(User.email == email).first()
            target_role = (state or "USER").upper()
            if target_role not in ("USER", "COACH"):
                target_role = "USER"

            if user:
                if user.role.upper() == "ADMIN":
                    return RedirectResponse(url=f"{frontend_base}/login.html?error=admin_oauth_forbidden")
                if user.provider != "GOOGLE":
                    user.provider = "GOOGLE"
                    db.commit()
                    db.refresh(user)
            else:
                random_pwd = secrets.token_urlsafe(16)
                user = User(
                    name=name,
                    email=email,
                    password=hash_password(random_pwd),
                    role=target_role,
                    provider="GOOGLE"
                )
                db.add(user)
                db.commit()
                db.refresh(user)
                logger.info(f"Created new Google OAuth user in DB: {email} with role {user.role}")

            # Generate WakeWise JWT access token
            access_token = create_access_token(data={"sub": user.email, "role": user.role, "id": user.id})

            # Route user to their corresponding frontend dashboard
            role_lower = (user.role or "user").lower()
            if role_lower == "coach":
                dash_path = "coach/dashboard-coach.html"
            elif role_lower == "admin":
                dash_path = "admin/dashboard-admin.html"
            else:
                dash_path = "user/dashboard-user.html"

            # Serialize user session object for seamless frontend hydration
            session_dict = {
                "id": user.id,
                "email": user.email,
                "name": user.name,
                "role": role_lower,
                "accessToken": access_token,
                "provider": "GOOGLE",
                "loggedInAt": datetime.datetime.now(datetime.timezone.utc).isoformat()
            }
            session_param = urllib.parse.quote(json.dumps(session_dict))

            redirect_target = f"{frontend_base}/{dash_path}?token={access_token}&session={session_param}"
            return RedirectResponse(url=redirect_target)

    except Exception as exc:
        logger.error(f"Unexpected error in Google OAuth callback: {exc}")
        return RedirectResponse(url=f"{frontend_base}/login.html?error=server_error")


@router.get("/users", response_model=List[UserResponse], summary="List all registered users")
def get_all_users(db: Session = Depends(get_db)):
    """
    Fetch list of registered users from PostgreSQL database with live individual habit & sleep scores.
    """
    try:
        users = db.query(User).all()
        results = []
        for u in users:
            h_snap = calculate_habit_score_snapshot(db, u.id, period_days=7)
            sq_snap = calculate_sleep_quality(db, u.id, days=7)

            u_dict = {
                "id": u.id,
                "name": u.name,
                "email": u.email,
                "role": u.role,
                "provider": u.provider,
                "target_bedtime": u.target_bedtime,
                "target_wake_time": u.target_wake_time,
                "phone_number": u.phone_number,
                "inactivity_threshold_minutes": u.inactivity_threshold_minutes,
                "last_meaningful_activity_at": u.last_meaningful_activity_at,
                "estimated_sleep_start": u.estimated_sleep_start,
                "estimated_sleep_end": u.estimated_sleep_end,
                "created_at": u.created_at,
                "updated_at": u.updated_at,
                "habit_score": h_snap.get("habit_score", 0.0),
                "sleep_quality_score": sq_snap.get("score"),
                "habit_breakdown": h_snap.get("breakdown"),
            }
            results.append(UserResponse(**u_dict))
        return results
    except OperationalError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not connect to PostgreSQL database."
        )

@router.delete("/users/{email}", summary="Delete user by email")
def delete_user_by_email(email: str, db: Session = Depends(get_db)):
    """
    Deletes a user account from PostgreSQL database by email.
    """
    try:
        user = db.query(User).filter(User.email == email.lower().strip()).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, 
                detail=f"User with email '{email}' not found."
            )
        
        db.delete(user)
        db.commit()
        return {"status": "success", "message": f"User '{email}' deleted successfully from database."}
    except OperationalError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, 
            detail="Database connection error during user deletion."
        )


# JWT Authentication Dependency matching spec
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        # Fallback to check if Bearer token was passed in the request headers manually
        # (in case the browser didn't use tokenUrl form structure)
        raise credentials_exception

    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    
    user = db.query(User).filter(User.email == email.lower()).first()
    if user is None:
        raise credentials_exception
    return user


@router.get("/me", response_model=UserResponse, summary="Get current logged-in user profile")
def get_me(current_user: User = Depends(get_current_user)):
    """Returns the authenticated user details including sleep schedule preferences."""
    return current_user


@router.put("/profile", response_model=UserResponse, summary="Update user profile settings")
def update_profile(
    payload: UserProfileUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Updates user profile details such as name, email, target_bedtime, target_wake_time, inactivity threshold."""
    if payload.name is not None:
        current_user.name = payload.name.strip()
    if payload.email is not None:
        current_user.email = payload.email.lower().strip()
    if payload.phone_number is not None:
        raw_phone = payload.phone_number.strip()
        if raw_phone:
            import re
            clean = re.sub(r"[\s\-\(\)\.]", "", raw_phone)
            if not re.match(r"^\+?[1-9]\d{6,14}$", clean):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid phone number format. Please provide a valid 10-15 digit phone number."
                )
            current_user.phone_number = clean
        else:
            current_user.phone_number = None
    if payload.target_bedtime is not None:
        current_user.target_bedtime = payload.target_bedtime.strip() if payload.target_bedtime else None
    if payload.target_wake_time is not None:
        current_user.target_wake_time = payload.target_wake_time.strip() if payload.target_wake_time else None
    if payload.inactivity_threshold_minutes is not None:
        current_user.inactivity_threshold_minutes = max(5, min(180, int(payload.inactivity_threshold_minutes)))

    db.commit()
    db.refresh(current_user)
    return current_user


def get_current_admin_user(current_user: User = Depends(get_current_user)) -> User:
    """
    Enforces server-side administrator authorization.
    Rejects any request not made by an authenticated user with ADMIN role.
    """
    role = (current_user.role or "").strip().upper()
    if role != "ADMIN" and "ADMIN" not in role:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator access required. Your account does not have sufficient permissions."
        )
    return current_user


def get_current_coach_user(current_user: User = Depends(get_current_user)) -> User:
    """
    Enforces server-side wellness coach or admin authorization.
    """
    role = (current_user.role or "").strip().upper()
    if "COACH" not in role and "ADMIN" not in role:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Wellness Coach or Administrator access required."
        )
    return current_user


