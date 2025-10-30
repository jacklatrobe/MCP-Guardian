"""Admin UI routes using Jinja2 templates."""
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from ..security import get_current_admin

router = APIRouter(prefix="/ADMIN", tags=["admin-ui"])

# Set up templates (using absolute path relative to this file)
templates_dir = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))


@router.get("/", response_class=HTMLResponse, dependencies=[Depends(get_current_admin)])
async def admin_index(request: Request):
    """Admin UI home page - list all services."""
    return templates.TemplateResponse(
        "admin/index.html",
        {"request": request}
    )


@router.get("/service/{name}", response_class=HTMLResponse, dependencies=[Depends(get_current_admin)])
async def admin_service_detail(request: Request, name: str):
    """Service detail page with snapshots and diff view."""
    return templates.TemplateResponse(
        "admin/snapshots.html",
        {"request": request, "service_name": name}
    )


@router.get("/service-form", response_class=HTMLResponse, dependencies=[Depends(get_current_admin)])
async def admin_service_form(request: Request):
    """Service creation/edit form."""
    return templates.TemplateResponse(
        "admin/service_form.html",
        {"request": request}
    )
