"""Manager Router"""
from datetime import datetime, timezone
from fastapi import APIRouter, Request, Depends, Form, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from sqlalchemy.orm import Session
from pathlib import Path
import os
import shutil

from src.database import (
    get_db, User, Project, AccessRequest, Ticket, TicketAssignment,
    UserRole, DevRole, AccessStatus, TicketStatus, Document
)
from src.auth.jwt_handler import get_current_user_from_request, create_access_token
from src.auth.otp import send_welcome_email
from src.auth.hash import verify_password, hash_password
from src.rag.ingestion import ingest_file, SUPPORTED
from src.templates import render_template

router = APIRouter(prefix="/manager", tags=["manager"])
UPLOADS = Path(__file__).resolve().parents[2] / "uploads"
UPLOADS.mkdir(exist_ok=True)


def _require_manager(request: Request):
    user = get_current_user_from_request(request)
    if not user or user.get("role") != "manager":
        raise HTTPException(status_code=302, headers={"Location": "/auth/login"})
    return user


def _get_manager_projects(manager: User, db: Session) -> list[Project]:
    """Return all projects this manager manages or has oversight of."""
    managed = db.query(Project).filter(
        (Project.manager_id == manager.id) | 
        (Project.id == manager.project_id) |
        (Project.manager_id.is_(None))
    ).all()
    if not managed:
        managed = db.query(Project).all()
    return managed


def _get_manager_project_ids(manager: User, db: Session) -> list[int]:
    return [p.id for p in _get_manager_projects(manager, db)]


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)):
    curr = _require_manager(request)
    manager = db.query(User).filter(User.id == int(curr["sub"])).first()

    project_ids = _get_manager_project_ids(manager, db)

    # Stats
    pending_requests = db.query(AccessRequest).filter(
        AccessRequest.project_id.in_(project_ids),
        AccessRequest.status == AccessStatus.pending
    ).count()
    total_devs = db.query(User).filter(
        User.role == UserRole.developer,
        User.is_approved == True,
        User.project_id.in_(project_ids)
    ).count()
    open_tickets = db.query(Ticket).filter(
        Ticket.project_id.in_(project_ids),
        Ticket.status.in_([TicketStatus.open, TicketStatus.in_progress])
    ).count()
    resolved_tickets = db.query(Ticket).filter(
        Ticket.project_id.in_(project_ids),
        Ticket.status == TicketStatus.resolved
    ).count()

    # Recent tickets
    recent_tickets = db.query(Ticket).filter(
        Ticket.project_id.in_(project_ids)
    ).order_by(Ticket.created_at.desc()).limit(10).all()

    # Recent requests
    recent_requests = db.query(AccessRequest).filter(
        AccessRequest.status == AccessStatus.pending,
        AccessRequest.project_id.in_(project_ids)
    ).order_by(AccessRequest.created_at.desc()).limit(5).all()

    return render_template("manager/dashboard.html", request, {
        "current_user": curr,
        "manager": manager,
        "pending_requests": pending_requests,
        "pending_count": pending_requests,
        "total_devs": total_devs,
        "open_tickets": open_tickets,
        "resolved_tickets": resolved_tickets,
        "recent_tickets": recent_tickets,
        "recent_requests": recent_requests,
    })


@router.get("/requests", response_class=HTMLResponse)
async def requests_page(request: Request, db: Session = Depends(get_db)):
    curr = _require_manager(request)
    manager = db.query(User).filter(User.id == int(curr["sub"])).first()

    project_ids = _get_manager_project_ids(manager, db)

    pending = db.query(AccessRequest).filter(
        AccessRequest.project_id.in_(project_ids),
        AccessRequest.status == AccessStatus.pending
    ).order_by(AccessRequest.created_at.desc()).all()

    history = db.query(AccessRequest).filter(
        AccessRequest.project_id.in_(project_ids),
        AccessRequest.status != AccessStatus.pending
    ).order_by(AccessRequest.created_at.desc()).limit(30).all()

    # All projects for "add to team" dropdown
    all_projects = db.query(Project).all()

    return render_template("manager/requests.html", request, {
        "current_user": curr,
        "pending_requests": pending,
        "pending_count": len(pending),
        "history": history,
        "dev_roles": [r.value for r in DevRole if r != DevRole.unassigned],
        "all_projects": all_projects,
    })


@router.post("/requests/{req_id}/approve")
async def approve_request(
    req_id: int,
    request: Request,
    dev_role: str = Form(...),
    project_id: int = Form(None),
    db: Session = Depends(get_db)
):
    curr = _require_manager(request)
    access_req = db.query(AccessRequest).filter(AccessRequest.id == req_id).first()
    if not access_req:
        raise HTTPException(404, "Request not found")

    dev_role_enum = DevRole(dev_role) if dev_role in [r.value for r in DevRole] else DevRole.unassigned
    assigned_project_id = project_id if project_id else access_req.project_id
    project = db.query(Project).filter(Project.id == assigned_project_id).first()
    if not project:
        project = access_req.project

    dev = access_req.developer
    dev.project_id = project.id
    dev.is_approved = True
    dev.dev_role = dev_role_enum
    access_req.project_id = project.id
    access_req.status = AccessStatus.approved
    access_req.reviewed_at = datetime.now(timezone.utc)
    db.commit()

    send_welcome_email(
        dev.email, dev.name,
        project.name,
        curr.get("name", "Manager")
    )
    return RedirectResponse("/manager/requests", status_code=302)


@router.post("/requests/{req_id}/reject")
async def reject_request(req_id: int, request: Request, db: Session = Depends(get_db)):
    curr = _require_manager(request)
    access_req = db.query(AccessRequest).filter(AccessRequest.id == req_id).first()
    if not access_req:
        raise HTTPException(404, "Request not found")
    access_req.status = AccessStatus.rejected
    access_req.reviewed_at = datetime.now(timezone.utc)
    db.commit()
    return RedirectResponse("/manager/requests", status_code=302)


@router.post("/requests/{req_id}/delete")
async def delete_request(req_id: int, request: Request, db: Session = Depends(get_db)):
    """Delete an access request (only rejected ones)."""
    curr = _require_manager(request)
    access_req = db.query(AccessRequest).filter(AccessRequest.id == req_id).first()
    if not access_req:
        raise HTTPException(404, "Request not found")
    if access_req.status != AccessStatus.rejected:
        raise HTTPException(400, "Only rejected requests can be deleted")
    db.delete(access_req)
    db.commit()
    return RedirectResponse("/manager/requests", status_code=302)


@router.post("/requests/{req_id}/add-to-team")
async def add_to_team_from_request(
    req_id: int,
    request: Request,
    dev_role: str = Form(...),
    project_id: int = Form(...),
    db: Session = Depends(get_db)
):
    """Add a previously-rejected developer to a team (approve them into a project)."""
    curr = _require_manager(request)
    access_req = db.query(AccessRequest).filter(AccessRequest.id == req_id).first()
    if not access_req:
        raise HTTPException(404, "Request not found")

    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(404, "Project not found")

    dev_role_enum = DevRole(dev_role) if dev_role in [r.value for r in DevRole] else DevRole.unassigned

    dev = access_req.developer
    dev.is_approved = True
    dev.dev_role = dev_role_enum
    dev.project_id = project_id
    access_req.status = AccessStatus.approved
    access_req.reviewed_at = datetime.now(timezone.utc)
    db.commit()

    send_welcome_email(
        dev.email, dev.name,
        project.name,
        curr.get("name", "Manager")
    )
    return RedirectResponse("/manager/requests", status_code=302)


@router.get("/tickets", response_class=HTMLResponse)
async def tickets_page(request: Request, db: Session = Depends(get_db)):
    curr = _require_manager(request)
    manager = db.query(User).filter(User.id == int(curr["sub"])).first()

    project_ids = _get_manager_project_ids(manager, db)
    pending_count = db.query(AccessRequest).filter(
        AccessRequest.project_id.in_(project_ids),
        AccessRequest.status == AccessStatus.pending
    ).count()

    tickets = db.query(Ticket).filter(
        Ticket.project_id.in_(project_ids)
    ).order_by(Ticket.created_at.desc()).all()

    # Enrich with assignment info
    ticket_data = []
    for t in tickets:
        accepted_assignment = next(
            (a for a in t.assignments if a.is_accepted), None
        )
        ticket_data.append({
            "ticket": t,
            "accepted_by": accepted_assignment.developer if accepted_assignment else None,
            "assignment": accepted_assignment,
        })

    return render_template("manager/tickets.html", request, {
        "current_user": curr,
        "ticket_data": ticket_data,
        "pending_count": pending_count,
    })


@router.post("/tickets/{ticket_id}/approve-resolution")
async def approve_resolution(ticket_id: int, request: Request, db: Session = Depends(get_db)):
    curr = _require_manager(request)
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(404, "Ticket not found")

    ticket.status = TicketStatus.resolved
    # Lock remarks
    for assignment in ticket.assignments:
        if assignment.is_accepted:
            assignment.remark_locked = True
    db.commit()
    return RedirectResponse("/manager/tickets", status_code=302)


@router.post("/tickets/{ticket_id}/delete")
async def delete_ticket(ticket_id: int, request: Request, db: Session = Depends(get_db)):
    """Delete a ticket and all its assignments."""
    curr = _require_manager(request)
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    # Delete assignments first
    for assignment in ticket.assignments:
        db.delete(assignment)
    db.delete(ticket)
    db.commit()
    return RedirectResponse("/manager/tickets", status_code=302)


@router.get("/team", response_class=HTMLResponse)
async def team_page(request: Request, db: Session = Depends(get_db)):
    curr = _require_manager(request)
    manager = db.query(User).filter(User.id == int(curr["sub"])).first()

    managed_projects = _get_manager_projects(manager, db)
    project_ids = [p.id for p in managed_projects]
    pending_count = db.query(AccessRequest).filter(
        AccessRequest.project_id.in_(project_ids),
        AccessRequest.status == AccessStatus.pending
    ).count()

    # For each project, get developers
    projects_with_devs = []
    for proj in managed_projects:
        devs = db.query(User).filter(
            User.role == UserRole.developer,
            User.is_approved == True,
            User.project_id == proj.id
        ).all()
        projects_with_devs.append({"project": proj, "developers": devs})

    # All projects for "create new team" / move developer
    all_projects = db.query(Project).all()

    return render_template("manager/team.html", request, {
        "current_user": curr,
        "projects_with_devs": projects_with_devs,
        "dev_roles": [r.value for r in DevRole if r != DevRole.unassigned],
        "all_projects": all_projects,
        "manager": manager,
        "pending_count": pending_count,
    })


@router.post("/team/{dev_id}/update-role")
async def update_dev_role(
    dev_id: int,
    request: Request,
    dev_role: str = Form(...),
    db: Session = Depends(get_db)
):
    curr = _require_manager(request)
    dev = db.query(User).filter(User.id == dev_id).first()
    if not dev:
        raise HTTPException(404, "Developer not found")
    dev.dev_role = DevRole(dev_role) if dev_role in [r.value for r in DevRole] else DevRole.unassigned
    db.commit()
    return RedirectResponse("/manager/team", status_code=302)


@router.post("/team/{dev_id}/move-project")
async def move_dev_project(
    dev_id: int,
    request: Request,
    new_project_id: int = Form(...),
    dev_role: str = Form(...),
    db: Session = Depends(get_db)
):
    """Move a developer to a different project."""
    curr = _require_manager(request)
    dev = db.query(User).filter(User.id == dev_id).first()
    if not dev:
        raise HTTPException(404, "Developer not found")
    project = db.query(Project).filter(Project.id == new_project_id).first()
    if not project:
        raise HTTPException(404, "Project not found")
    dev.project_id = new_project_id
    dev.dev_role = DevRole(dev_role) if dev_role in [r.value for r in DevRole] else DevRole.unassigned
    db.commit()
    return RedirectResponse("/manager/team?success=Developer+moved+successfully", status_code=302)


@router.post("/team/{dev_id}/remove")
async def remove_dev_from_project(dev_id: int, request: Request, db: Session = Depends(get_db)):
    """Remove a developer from their project (revoke access)."""
    curr = _require_manager(request)
    dev = db.query(User).filter(User.id == dev_id).first()
    if not dev:
        raise HTTPException(404, "Developer not found")
    dev.project_id = None
    dev.is_approved = False
    dev.dev_role = DevRole.unassigned
    db.commit()
    return RedirectResponse("/manager/team?success=Developer+removed+from+project", status_code=302)


@router.post("/team/create-project")
async def create_project(
    request: Request,
    project_name: str = Form(...),
    project_description: str = Form(""),
    db: Session = Depends(get_db)
):
    """Create a new project/team."""
    curr = _require_manager(request)
    manager = db.query(User).filter(User.id == int(curr["sub"])).first()

    existing = db.query(Project).filter(Project.name == project_name).first()
    if existing:
        # Redirect back with error (simple approach)
        return RedirectResponse("/manager/team?error=Project+name+already+exists", status_code=302)

    new_project = Project(
        name=project_name,
        description=project_description,
        manager_id=manager.id,
    )
    db.add(new_project)
    db.commit()
    return RedirectResponse("/manager/team?success=Team+created+successfully", status_code=302)


@router.get("/documents", response_class=HTMLResponse)
async def documents_page(request: Request, db: Session = Depends(get_db)):
    curr = _require_manager(request)
    manager = db.query(User).filter(User.id == int(curr["sub"])).first()

    project_ids = _get_manager_project_ids(manager, db)
    pending_count = db.query(AccessRequest).filter(
        AccessRequest.project_id.in_(project_ids),
        AccessRequest.status == AccessStatus.pending
    ).count()

    docs = db.query(Document).filter(
        Document.project_id.in_(project_ids)
    ).order_by(Document.created_at.desc()).all()

    projects = _get_manager_projects(manager, db)

    return render_template("manager/documents.html", request, {
        "current_user": curr,
        "documents": docs,
        "pending_count": pending_count,
        "projects": projects,
    })


@router.post("/upload-document")
async def upload_document_manager(
    request: Request,
    file: UploadFile = File(...),
    project_id: int = Form(...),
    db: Session = Depends(get_db)
):
    """Allow manager to upload documentation to any of their managed projects."""
    curr = _require_manager(request)
    manager = db.query(User).filter(User.id == int(curr["sub"])).first()

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in SUPPORTED:
        raise HTTPException(400, "Supported file types: PDF, TXT, MD, DOCX")

    safe_name = Path(file.filename).name
    target = UPLOADS / safe_name
    with target.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    file_size = target.stat().st_size

    try:
        from fastapi.concurrency import run_in_threadpool
        count = await run_in_threadpool(ingest_file, target, project_id)
    except Exception as e:
        count = 0
        print(f"Ingestion error: {e}")

    doc = Document(
        filename=safe_name,
        original_name=file.filename,
        project_id=project_id,
        uploaded_by_id=manager.id,
        chunks_indexed=count,
        file_size=file_size,
    )
    db.add(doc)
    db.commit()

    return JSONResponse({"filename": safe_name, "chunks_indexed": count, "status": "ok"})


@router.post("/documents/{doc_id}/delete")
async def delete_document(doc_id: int, request: Request, db: Session = Depends(get_db)):
    """Delete an uploaded document and remove its file from disk."""
    curr = _require_manager(request)
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(404, "Document not found")

    # Remove physical file
    uploads_dir = Path(__file__).resolve().parents[2] / "uploads"
    file_path = uploads_dir / doc.filename
    if file_path.exists():
        try:
            os.remove(file_path)
        except Exception:
            pass  # File removal failure is non-fatal

    db.delete(doc)
    db.commit()
    return RedirectResponse("/manager/documents", status_code=302)


@router.get("/profile", response_class=HTMLResponse)
async def manager_profile_page(request: Request, db: Session = Depends(get_db)):
    """Manager profile page to view and edit profile details."""
    curr = _require_manager(request)
    manager = db.query(User).filter(User.id == int(curr["sub"])).first()
    project_ids = _get_manager_project_ids(manager, db)
    pending_count = db.query(AccessRequest).filter(
        AccessRequest.project_id.in_(project_ids),
        AccessRequest.status == AccessStatus.pending
    ).count()
    managed_projects = _get_manager_projects(manager, db)

    return render_template("manager/profile.html", request, {
        "current_user": curr,
        "manager": manager,
        "pending_count": pending_count,
        "managed_projects": managed_projects,
    })


@router.post("/profile")
async def update_manager_profile(
    request: Request,
    name: str = Form(...),
    avatar_url: str = Form(""),
    current_password: str = Form(""),
    new_password: str = Form(""),
    confirm_password: str = Form(""),
    db: Session = Depends(get_db)
):
    """Update manager profile details (name, avatar, password - email is not editable)."""
    curr = _require_manager(request)
    manager = db.query(User).filter(User.id == int(curr["sub"])).first()

    name = name.strip()
    if not name:
        return RedirectResponse("/manager/profile?error=Name+cannot+be+empty", status_code=302)

    manager.name = name
    manager.avatar_url = avatar_url.strip() if avatar_url.strip() else None

    # Handle password change if requested
    if new_password:
        if not current_password:
            return RedirectResponse("/manager/profile?error=Current+password+is+required+to+set+a+new+password", status_code=302)
        if not manager.password_hash or not verify_password(current_password, manager.password_hash):
            return RedirectResponse("/manager/profile?error=Incorrect+current+password", status_code=302)
        if len(new_password) < 6:
            return RedirectResponse("/manager/profile?error=New+password+must+be+at+least+6+characters", status_code=302)
        if new_password != confirm_password:
            return RedirectResponse("/manager/profile?error=New+passwords+do+not+match", status_code=302)
        manager.password_hash = hash_password(new_password)

    db.commit()

    # Re-issue token so updated name/avatar are reflected immediately
    token = create_access_token({
        "sub": str(manager.id),
        "email": manager.email,
        "name": manager.name,
        "role": manager.role.value,
        "dev_role": manager.dev_role.value if manager.dev_role else "unassigned",
        "project_id": manager.project_id,
        "avatar": manager.avatar_url or "",
    })

    resp = RedirectResponse("/manager/profile?success=Profile+updated+successfully", status_code=302)
    resp.set_cookie("access_token", token, httponly=True, samesite="lax", max_age=86400)
    return resp
