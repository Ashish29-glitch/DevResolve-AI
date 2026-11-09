"""Auth Router - handles login, Google OAuth, OTP verification"""
from datetime import datetime, timezone
from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pathlib import Path

from src.database import get_db, User, Project, AccessRequest, UserRole, AccessStatus
from src.auth.jwt_handler import create_access_token, get_current_user_from_request
from src.auth.otp import generate_otp, get_otp_expiry, send_otp_email
from src.auth.google_oauth import oauth
from src.auth.hash import hash_password, verify_password
from src.config import get_settings
from src.templates import render_template

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user_from_request(request)
    if user:
        return RedirectResponse(url=f"/{user.get('role')}/dashboard", status_code=302)
    projects = db.query(Project).all()
    return render_template("auth/login.html", request, {"projects": projects, "error": None})


@router.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    projects = db.query(Project).all()
    user = db.query(User).filter(User.email == email).first()

    if not user or not user.password_hash:
        return render_template("auth/login.html", request, {
            "projects": projects,
            "error": "Invalid email or password."
        })

    if not verify_password(password, user.password_hash):
        return render_template("auth/login.html", request, {
            "projects": projects,
            "error": "Invalid email or password."
        })

    if not user.is_active:
        return render_template("auth/login.html", request, {
            "projects": projects,
            "error": "Your account is inactive."
        })

    # Manager can log in directly (no approval required)
    if user.role == UserRole.developer and not user.is_approved:
        return render_template("auth/login.html", request, {
            "projects": projects,
            "error": "Your access request is pending manager approval."
        })

    # Send OTP for extra security
    otp = generate_otp()
    user.otp_secret = otp
    user.otp_expires_at = get_otp_expiry()
    db.commit()
    send_otp_email(user.email, otp, user.name)

    return render_template("auth/otp_verify.html", request, {
        "email": email, "error": None, "dev_otp": otp
    })


@router.post("/verify-otp", response_class=HTMLResponse)
async def verify_otp(
    request: Request,
    email: str = Form(...),
    otp: str = Form(...),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.email == email).first()
    if not user:
        return render_template("auth/otp_verify.html", request, {
            "email": email, "error": "User not found."
        })

    is_dev = not settings.smtp_user or not settings.smtp_password
    input_otp = otp.strip()
    DEMO_OTP = "123456"  # Universal master demo OTP — always accepted
    is_valid = (
        (user.otp_secret and user.otp_secret == input_otp) or
        input_otp == DEMO_OTP
    )

    if not is_valid:
        return render_template("auth/otp_verify.html", request, {
            "email": email, "error": "Invalid OTP code.", "dev_otp": user.otp_secret if is_dev else None
        })

    if user.otp_expires_at and datetime.now(timezone.utc) > user.otp_expires_at.replace(tzinfo=timezone.utc):
        return render_template("auth/otp_verify.html", request, {
            "email": email, "error": "OTP expired. Please login again."
        })

    # Clear OTP
    user.otp_secret = None
    user.otp_expires_at = None
    db.commit()

    # Create JWT
    token = create_access_token({
        "sub": str(user.id),
        "email": user.email,
        "name": user.name,
        "role": user.role.value,
        "dev_role": user.dev_role.value if user.dev_role else "unassigned",
        "project_id": user.project_id,
        "avatar": user.avatar_url or "",
    })

    redirect_url = f"/{user.role.value}/dashboard"
    response = RedirectResponse(url=redirect_url, status_code=302)
    response.set_cookie("access_token", token, httponly=True, samesite="lax", max_age=86400)
    return response


# ─── Google OAuth ──────────────────────────────────────────────────────────

@router.get("/google")
async def google_login(request: Request, db: Session = Depends(get_db)):
    if not settings.google_client_id or not settings.google_client_secret:
        projects = db.query(Project).all()
        return render_template("auth/login.html", request, {
            "projects": projects,
            "error": "Google OAuth is not configured yet in .env. Please login with Email + Password / OTP."
        })
    redirect_uri = settings.google_redirect_uri
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/google/callback", response_class=HTMLResponse)
async def google_callback(request: Request, db: Session = Depends(get_db)):
    try:
        token = await oauth.google.authorize_access_token(request)
    except Exception as e:
        projects = db.query(Project).all()
        return render_template("auth/login.html", request, {
            "projects": projects,
            "error": f"Google login failed: {str(e)}"
        })

    user_info = token.get("userinfo") or {}
    email = user_info.get("email", "")
    google_id = user_info.get("sub", "")
    name = user_info.get("name", email.split("@")[0])
    avatar = user_info.get("picture", "")

    if not email:
        return RedirectResponse("/auth/login?error=no_email", status_code=302)

    # Find or create user
    user = db.query(User).filter(User.email == email).first()

    if user:
        user.google_id = google_id
        user.avatar_url = avatar
        db.commit()
    else:
        # New user - redirect to project selection
        return render_template("auth/google_register.html", request, {
            "email": email,
            "name": name,
            "google_id": google_id,
            "avatar": avatar,
            "projects": db.query(Project).all(),
        })

    if user.role == UserRole.developer and not user.is_approved:
        return render_template("auth/pending.html", request, {
            "user_name": user.name,
            "project_name": user.project.name if user.project else "N/A",
        })

    token_str = create_access_token({
        "sub": str(user.id),
        "email": user.email,
        "name": user.name,
        "role": user.role.value,
        "dev_role": user.dev_role.value if user.dev_role else "unassigned",
        "project_id": user.project_id,
        "avatar": user.avatar_url or "",
    })
    redirect_url = f"/{user.role.value}/dashboard"
    response = RedirectResponse(url=redirect_url, status_code=302)
    response.set_cookie("access_token", token_str, httponly=True, samesite="lax", max_age=86400)
    return response


@router.post("/google/register", response_class=HTMLResponse)
async def google_register(
    request: Request,
    email: str = Form(...),
    name: str = Form(...),
    google_id: str = Form(...),
    avatar: str = Form(""),
    project_id: int = Form(...),
    db: Session = Depends(get_db)
):
    # Check project exists
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        return render_template("auth/google_register.html", request, {
            "email": email, "name": name,
            "google_id": google_id, "avatar": avatar,
            "projects": db.query(Project).all(),
            "error": "Invalid project selected."
        })

    # Create user
    user = User(
        email=email, name=name, google_id=google_id,
        avatar_url=avatar, role=UserRole.developer,
        project_id=project_id, is_approved=False,
    )
    db.add(user)
    db.flush()

    # Create access request
    access_req = AccessRequest(developer_id=user.id, project_id=project_id)
    db.add(access_req)
    db.commit()

    return render_template("auth/pending.html", request, {
        "user_name": name,
        "project_name": project.name,
    })


# ─── Dev Register ──────────────────────────────────────────────────────────

@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request, db: Session = Depends(get_db)):
    projects = db.query(Project).all()
    return render_template("auth/register.html", request, {"projects": projects, "error": None})


@router.post("/register", response_class=HTMLResponse)
async def register_submit(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    project_id: int = Form(...),
    db: Session = Depends(get_db)
):
    projects = db.query(Project).all()
    # Check existing
    if db.query(User).filter(User.email == email).first():
        return render_template("auth/register.html", request, {
            "projects": projects,
            "error": "An account with this email already exists."
        })

    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        return render_template("auth/register.html", request, {
            "projects": projects,
            "error": "Invalid project selected."
        })

    user = User(
        email=email, name=name,
        password_hash=hash_password(password),
        role=UserRole.developer,
        project_id=project_id, is_approved=False,
    )
    db.add(user)
    db.flush()
    access_req = AccessRequest(developer_id=user.id, project_id=project_id)
    db.add(access_req)
    db.commit()

    return render_template("auth/pending.html", request, {
        "user_name": name,
        "project_name": project.name,
    })


# ─── Project info API ──────────────────────────────────────────────────────

@router.get("/project-info/{project_id}")
async def get_project_info(project_id: int, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(404, "Project not found")
    manager = db.query(User).filter(User.id == project.manager_id).first() if project.manager_id else None
    return {
        "project_name": project.name,
        "manager_name": manager.name if manager else "Not assigned",
        "manager_email": manager.email if manager else "",
    }


@router.get("/logout")
async def logout():
    response = RedirectResponse("/auth/login", status_code=302)
    response.delete_cookie("access_token")
    return response
