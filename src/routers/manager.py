"""Manager Router"""
from datetime import datetime, timezone
from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from sqlalchemy.orm import Session
from pathlib import Path

from src.database import (
    get_db, User, Project, AccessRequest, Ticket, TicketAssignment,
    UserRole, DevRole, AccessStatus, TicketStatus, Document
)
from src.auth.jwt_handler import get_current_user_from_request, create_access_token
from src.auth.otp import send_welcome_email
from src.templates import render_template

router = APIRouter(prefix="/manager", tags=["manager"])


def _require_manager(request: Request):
    user = get_current_user_from_request(request)
    if not user or user.get("role") != "manager":
        raise HTTPException(status_code=302, headers={"Location": "/auth/login"})
    return user


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)):
    curr = _require_manager(request)
    manager = db.query(User).filter(User.id == int(curr["sub"])).first()

    # Stats
    pending_requests = db.query(AccessRequest).filter(AccessRequest.status == AccessStatus.pending).count()
    total_devs = db.query(User).filter(
        User.role == UserRole.developer,
        User.is_approved == True,
        User.project_id == manager.project_id
    ).count()
    open_tickets = db.query(Ticket).filter(
        Ticket.project_id == manager.project_id,
        Ticket.status.in_([TicketStatus.open, TicketStatus.in_progress])
    ).count()
    resolved_tickets = db.query(Ticket).filter(
        Ticket.project_id == manager.project_id,
        Ticket.status == TicketStatus.resolved
    ).count()

    # Recent tickets
    recent_tickets = db.query(Ticket).filter(
        Ticket.project_id == manager.project_id
    ).order_by(Ticket.created_at.desc()).limit(10).all()

    # Recent requests
    recent_requests = db.query(AccessRequest).filter(
        AccessRequest.status == AccessStatus.pending,
        AccessRequest.project_id == manager.project_id
    ).order_by(AccessRequest.created_at.desc()).limit(5).all()

    return render_template("manager/dashboard.html", request, {
        "current_user": curr,
        "manager": manager,
        "pending_requests": pending_requests,
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

    pending = db.query(AccessRequest).filter(
        AccessRequest.project_id == manager.project_id,
        AccessRequest.status == AccessStatus.pending
    ).order_by(AccessRequest.created_at.desc()).all()

    history = db.query(AccessRequest).filter(
        AccessRequest.project_id == manager.project_id,
        AccessRequest.status != AccessStatus.pending
    ).order_by(AccessRequest.created_at.desc()).limit(30).all()

    return render_template("manager/requests.html", request, {
        "current_user": curr,
        "pending_requests": pending,
        "history": history,
        "dev_roles": [r.value for r in DevRole if r != DevRole.unassigned],
    })


@router.post("/requests/{req_id}/approve")
async def approve_request(
    req_id: int,
    request: Request,
    dev_role: str = Form(...),
    db: Session = Depends(get_db)
):
    curr = _require_manager(request)
    access_req = db.query(AccessRequest).filter(AccessRequest.id == req_id).first()
    if not access_req:
        raise HTTPException(404, "Request not found")

    dev_role_enum = DevRole(dev_role) if dev_role in [r.value for r in DevRole] else DevRole.unassigned

    dev = access_req.developer
    dev.is_approved = True
    dev.dev_role = dev_role_enum
    access_req.status = AccessStatus.approved
    access_req.reviewed_at = datetime.now(timezone.utc)
    db.commit()

    send_welcome_email(
        dev.email, dev.name,
        access_req.project.name,
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


@router.get("/tickets", response_class=HTMLResponse)
async def tickets_page(request: Request, db: Session = Depends(get_db)):
    curr = _require_manager(request)
    manager = db.query(User).filter(User.id == int(curr["sub"])).first()

    tickets = db.query(Ticket).filter(
        Ticket.project_id == manager.project_id
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


@router.get("/team", response_class=HTMLResponse)
async def team_page(request: Request, db: Session = Depends(get_db)):
    curr = _require_manager(request)
    manager = db.query(User).filter(User.id == int(curr["sub"])).first()

    devs = db.query(User).filter(
        User.role == UserRole.developer,
        User.is_approved == True,
        User.project_id == manager.project_id
    ).all()

    return render_template("manager/team.html", request, {
        "current_user": curr,
        "developers": devs,
        "dev_roles": [r.value for r in DevRole if r != DevRole.unassigned],
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


@router.get("/documents", response_class=HTMLResponse)
async def documents_page(request: Request, db: Session = Depends(get_db)):
    curr = _require_manager(request)
    manager = db.query(User).filter(User.id == int(curr["sub"])).first()
    docs = db.query(Document).filter(Document.project_id == manager.project_id).order_by(Document.created_at.desc()).all()
    return render_template("manager/documents.html", request, {
        "current_user": curr,
        "documents": docs,
    })
