"""Template rendering helper for Jinja2 with Starlette >= 0.35+ compatibility"""
from pathlib import Path
from fastapi import Request
from fastapi.templating import Jinja2Templates

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

def render_template(template_name: str, request: Request, context: dict = None):
    ctx = context.copy() if context else {}
    return templates.TemplateResponse(
        request=request,
        name=template_name,
        context=ctx
    )
