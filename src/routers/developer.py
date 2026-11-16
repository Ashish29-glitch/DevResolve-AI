"""Developer Router"""
import json
from datetime import datetime, timezone
from fastapi import APIRouter, Request, Depends, Form, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from sqlalchemy.orm import Session
from pathlib import Path
import shutil

from src.database import (
    get_db, User, Project, Ticket, TicketAssignment, DailyUpdate, Document,
    UserRole, TicketStatus, TicketTeam, TicketPriority, DevRole
)
from src.auth.jwt_handler import get_current_user_from_request, create_access_token
from src.auth.hash import verify_password, hash_password
from src.rag.ingestion import ingest_file, SUPPORTED
from src.config import get_settings
from src.templates import render_template

router = APIRouter(prefix="/developer", tags=["developer"])
settings = get_settings()
UPLOADS = Path(__file__).resolve().parents[2] / "uploads"
UPLOADS.mkdir(exist_ok=True)


def _require_developer(request: Request, db: Session):
    user_data = get_current_user_from_request(request)
    if not user_data or user_data.get("role") != "developer":
        raise HTTPException(status_code=302, headers={"Location": "/auth/login"})
    user = db.query(User).filter(User.id == int(user_data["sub"])).first()
    if not user or not user.is_approved:
        raise HTTPException(status_code=302, headers={"Location": "/auth/pending"})
    return user, user_data


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)):
    curr_data = get_current_user_from_request(request)
    if not curr_data or curr_data.get("role") != "developer":
        return RedirectResponse("/auth/login", status_code=302)
    dev = db.query(User).filter(User.id == int(curr_data["sub"])).first()
    if not dev or not dev.is_approved:
        return RedirectResponse("/auth/pending", status_code=302)

    # My tickets (raised)
    my_raised = db.query(Ticket).filter(Ticket.raised_by_id == dev.id).all()
    # Assigned to me (by team role)
    team_tickets = []
    if dev.dev_role and dev.dev_role.value != "unassigned":
        try:
            team_enum = TicketTeam(dev.dev_role.value)
            team_tickets = db.query(Ticket).filter(
                Ticket.project_id == dev.project_id,
                Ticket.assigned_team == team_enum,
                Ticket.status != TicketStatus.resolved,
            ).order_by(Ticket.created_at.desc()).all()
        except ValueError:
            pass

    # Recent updates
    recent_updates = db.query(DailyUpdate).filter(
        DailyUpdate.developer_id == dev.id
    ).order_by(DailyUpdate.created_at.desc()).limit(5).all()

    # Stats
    total_raised = len(my_raised)
    completed = sum(1 for t in my_raised if t.status == TicketStatus.resolved)
    pending = sum(1 for t in my_raised if t.status in [TicketStatus.open, TicketStatus.in_progress])
    in_progress = sum(1 for t in my_raised if t.status == TicketStatus.in_progress)

    # All project tickets (visible to all)
    all_project_tickets = db.query(Ticket).filter(
        Ticket.project_id == dev.project_id
    ).order_by(Ticket.created_at.desc()).limit(20).all()

    return render_template("developer/dashboard.html", request, {
        "current_user": curr_data,
        "developer": dev,
        "total_raised": total_raised,
        "completed": completed,
        "pending": pending,
        "in_progress": in_progress,
        "team_tickets": team_tickets,
        "recent_updates": recent_updates,
        "all_project_tickets": all_project_tickets,
    })


@router.get("/my-issues", response_class=HTMLResponse)
async def my_issues(request: Request, db: Session = Depends(get_db)):
    dev, curr_data = _require_developer(request, db)
    tickets = db.query(Ticket).filter(
        Ticket.raised_by_id == dev.id
    ).order_by(Ticket.created_at.desc()).all()

    return render_template("developer/my_issues.html", request, {
        "current_user": curr_data,
        "developer": dev,
        "tickets": tickets,
        "teams": [t.value for t in TicketTeam],
        "priorities": [p.value for p in TicketPriority],
    })


@router.post("/raise-ticket", response_class=HTMLResponse)
async def raise_ticket(
    request: Request,
    title: str = Form(...),
    description: str = Form(...),
    assigned_team: str = Form(...),
    priority: str = Form("medium"),
    db: Session = Depends(get_db)
):
    dev, curr_data = _require_developer(request, db)

    try:
        team_enum = TicketTeam(assigned_team)
    except ValueError:
        team_enum = TicketTeam.backend

    try:
        priority_enum = TicketPriority(priority)
    except ValueError:
        priority_enum = TicketPriority.medium

    # Create ticket
    ticket = Ticket(
        title=title,
        description=description,
        raised_by_id=dev.id,
        project_id=dev.project_id,
        assigned_team=team_enum,
        priority=priority_enum,
        status=TicketStatus.open,
    )
    db.add(ticket)
    db.flush()

    # Find devs with matching role and assign
    matching_devs = db.query(User).filter(
        User.project_id == dev.project_id,
        User.dev_role == DevRole(assigned_team) if assigned_team in [r.value for r in DevRole] else User.id == -1,
        User.is_approved == True,
    ).all()

    for assignee in matching_devs:
        assignment = TicketAssignment(ticket_id=ticket.id, developer_id=assignee.id)
        db.add(assignment)

    db.commit()
    ticket_id = ticket.id

    # Run RAG asynchronously in background - trigger AI solution
    from fastapi.concurrency import run_in_threadpool
    try:
        from src.rag.self_rag import solve_ticket
        result = await run_in_threadpool(solve_ticket, title, description, assigned_team, ticket_id)
        # Update ticket with AI solution
        t = db.query(Ticket).filter(Ticket.id == ticket_id).first()
        if t:
            t.ai_solution = result.get("ai_solution", "")
            t.ai_route = result.get("ai_route", "")
            t.ai_sources = json.dumps(result.get("sources", []))
            db.commit()
    except Exception as e:
        print(f"RAG error (non-fatal): {e}")

    return RedirectResponse(f"/developer/ticket/{ticket_id}", status_code=302)


@router.get("/ticket/{ticket_id}", response_class=HTMLResponse)
async def ticket_detail(ticket_id: int, request: Request, db: Session = Depends(get_db)):
    curr_data = get_current_user_from_request(request)
    if not curr_data:
        return RedirectResponse("/auth/login", status_code=302)
    dev = db.query(User).filter(User.id == int(curr_data["sub"])).first()
    if not dev:
        return RedirectResponse("/auth/login", status_code=302)

    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(404, "Ticket not found")

    # If AI solution is not yet generated, generate it on demand
    if not ticket.ai_solution:
        try:
            from src.rag.self_rag import solve_ticket
            result = solve_ticket(
                ticket.title,
                ticket.description,
                ticket.assigned_team.value if ticket.assigned_team else "backend",
                ticket.id
            )
            ticket.ai_solution = result.get("ai_solution", "")
            ticket.ai_route = result.get("ai_route", "Project Documentation")
            ticket.ai_sources = json.dumps(result.get("sources", []))
            db.commit()
            db.refresh(ticket)
        except Exception as e:
            print(f"On-demand AI solution generation error: {e}")

    # All assignments for this ticket
    assignments = db.query(TicketAssignment).filter(TicketAssignment.ticket_id == ticket_id).all()
    accepted_assignment = next((a for a in assignments if a.is_accepted), None)
    my_assignment = next((a for a in assignments if a.developer_id == dev.id), None)

    # Sources
    sources = []
    if ticket.ai_sources:
        try:
            sources = json.loads(ticket.ai_sources)
        except Exception:
            pass

    return render_template("developer/ticket_detail.html", request, {
        "current_user": curr_data,
        "developer": dev,
        "ticket": ticket,
        "assignments": assignments,
        "accepted_assignment": accepted_assignment,
        "my_assignment": my_assignment,
        "sources": sources,
        "can_accept": my_assignment is not None and not my_assignment.is_accepted and accepted_assignment is None,
        "can_submit_remark": my_assignment is not None and my_assignment.is_accepted and not my_assignment.remark_locked,
    })


@router.post("/ticket/{ticket_id}/regenerate-ai")
async def regenerate_ai_solution(ticket_id: int, request: Request, db: Session = Depends(get_db)):
    """Regenerate AI solution for this ticket using knowledge base."""
    dev, curr_data = _require_developer(request, db)
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(404, "Ticket not found")

    try:
        from src.rag.self_rag import solve_ticket
        result = solve_ticket(
            ticket.title,
            ticket.description,
            ticket.assigned_team.value if ticket.assigned_team else "backend",
            ticket.id
        )
        ticket.ai_solution = result.get("ai_solution", "")
        ticket.ai_route = result.get("ai_route", "Project Documentation")
        ticket.ai_sources = json.dumps(result.get("sources", []))
        db.commit()
    except Exception as e:
        print(f"Regenerate AI solution notice: {e}")

    return RedirectResponse(f"/developer/ticket/{ticket_id}", status_code=302)


@router.post("/ticket/{ticket_id}/accept")
async def accept_ticket(ticket_id: int, request: Request, db: Session = Depends(get_db)):
    dev, curr_data = _require_developer(request, db)

    # Check no one else accepted
    existing_acceptance = db.query(TicketAssignment).filter(
        TicketAssignment.ticket_id == ticket_id,
        TicketAssignment.is_accepted == True
    ).first()
    if existing_acceptance:
        raise HTTPException(400, "Ticket already accepted by another developer")

    assignment = db.query(TicketAssignment).filter(
        TicketAssignment.ticket_id == ticket_id,
        TicketAssignment.developer_id == dev.id
    ).first()
    if not assignment:
        raise HTTPException(403, "You are not assigned to this ticket")

    assignment.is_accepted = True
    assignment.accepted_at = datetime.now(timezone.utc)

    # Update ticket status
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if ticket:
        ticket.status = TicketStatus.in_progress
    db.commit()

    return RedirectResponse(f"/developer/ticket/{ticket_id}", status_code=302)


@router.post("/ticket/{ticket_id}/remark")
async def submit_remark(
    ticket_id: int,
    request: Request,
    remark: str = Form(...),
    db: Session = Depends(get_db)
):
    dev, curr_data = _require_developer(request, db)
    assignment = db.query(TicketAssignment).filter(
        TicketAssignment.ticket_id == ticket_id,
        TicketAssignment.developer_id == dev.id,
        TicketAssignment.is_accepted == True,
    ).first()
    if not assignment:
        raise HTTPException(403, "You cannot submit a remark for this ticket")
    if assignment.remark_locked:
        raise HTTPException(400, "Remark is locked after manager approval")

    assignment.remark = remark
    assignment.is_resolved = True

    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if ticket:
        ticket.status = TicketStatus.in_progress
    db.commit()

    return RedirectResponse(f"/developer/ticket/{ticket_id}", status_code=302)


@router.post("/daily-update")
async def add_daily_update(
    request: Request,
    content: str = Form(...),
    db: Session = Depends(get_db)
):
    dev, curr_data = _require_developer(request, db)
    update = DailyUpdate(developer_id=dev.id, content=content)
    db.add(update)
    db.commit()
    return RedirectResponse("/developer/dashboard", status_code=302)


@router.post("/upload-document")
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    dev, curr_data = _require_developer(request, db)

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
        count = await run_in_threadpool(ingest_file, target, dev.project_id)
    except Exception as e:
        count = 0
        print(f"Ingestion error: {e}")

    doc = Document(
        filename=safe_name,
        original_name=file.filename,
        project_id=dev.project_id,
        uploaded_by_id=dev.id,
        chunks_indexed=count,
        file_size=file_size,
    )
    db.add(doc)
    db.commit()

    return JSONResponse({"filename": safe_name, "chunks_indexed": count, "status": "ok"})


@router.get("/profile", response_class=HTMLResponse)
async def developer_profile_page(request: Request, db: Session = Depends(get_db)):
    """Developer profile view."""
    dev, curr_data = _require_developer(request, db)
    return render_template("developer/profile.html", request, {
        "current_user": curr_data,
        "developer": dev,
    })


@router.post("/profile")
async def update_developer_profile(
    request: Request,
    name: str = Form(...),
    avatar_url: str = Form(""),
    current_password: str = Form(""),
    new_password: str = Form(""),
    confirm_password: str = Form(""),
    db: Session = Depends(get_db)
):
    """Update developer profile (name, avatar, password - email is not editable)."""
    dev, curr_data = _require_developer(request, db)

    name = name.strip()
    if not name:
        return RedirectResponse("/developer/profile?error=Name+cannot+be+empty", status_code=302)

    dev.name = name
    dev.avatar_url = avatar_url.strip() if avatar_url.strip() else None

    # Handle password change if requested
    if new_password:
        if not current_password:
            return RedirectResponse("/developer/profile?error=Current+password+is+required+to+set+a+new+password", status_code=302)
        if not dev.password_hash or not verify_password(current_password, dev.password_hash):
            return RedirectResponse("/developer/profile?error=Incorrect+current+password", status_code=302)
        if len(new_password) < 6:
            return RedirectResponse("/developer/profile?error=New+password+must+be+at+least+6+characters", status_code=302)
        if new_password != confirm_password:
            return RedirectResponse("/developer/profile?error=New+passwords+do+not+match", status_code=302)
        dev.password_hash = hash_password(new_password)

    db.commit()

    # Re-issue token so updated name/avatar are reflected immediately
    token = create_access_token({
        "sub": str(dev.id),
        "email": dev.email,
        "name": dev.name,
        "role": dev.role.value,
        "dev_role": dev.dev_role.value if dev.dev_role else "unassigned",
        "project_id": dev.project_id,
        "avatar": dev.avatar_url or "",
    })

    resp = RedirectResponse("/developer/profile?success=Profile+updated+successfully", status_code=302)
    resp.set_cookie("access_token", token, httponly=True, samesite="lax", max_age=86400)
    return resp
