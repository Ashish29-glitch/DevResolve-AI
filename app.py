"""Main FastAPI Application - DevResolve AI"""
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from dotenv import load_dotenv

load_dotenv()

from src.config import get_settings
from src.database import init_db
from src.routers import auth, manager, developer

settings = get_settings()
ROOT = Path(__file__).resolve().parent

app = FastAPI(
    title="DevResolve AI",
    version="1.0.0",
    description="Smart AI-Powered Complaint and Issue Tracking System",
)

# Session middleware (required for OAuth)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    max_age=86400,
)

# Static files
app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")
templates = Jinja2Templates(directory=str(ROOT / "templates"))

from src.templates import render_template

# Routers
app.include_router(auth.router)
app.include_router(manager.router)
app.include_router(developer.router)


@app.on_event("startup")
def startup():
    init_db()
    print("[OK] DevResolve AI started!")
    print(f"     Manager login: admin@devresolve.ai / Admin@123")
    print(f"     App URL: {settings.app_url}")


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return render_template("landing.html", request)


@app.get("/health")
def health():
    return {"status": "ok", "app": "DevResolve AI", "version": "1.0.0"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
