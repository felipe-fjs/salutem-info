from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from settings.users import authenticate

router_auth = APIRouter(tags=["Auth"])
templates = Jinja2Templates(directory="templates")


@router_auth.get("/login")
def login_page(request: Request):
    if request.session.get("user"):
        return RedirectResponse(url="/dashboard", status_code=303)
    return templates.TemplateResponse(
        request,
        "login.html",
        {"erro": None},
    )


@router_auth.post("/login")
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    user = authenticate(username, password)
    if user:
        request.session["user"] = user["username"]
        request.session["permissoes"] = user["permissoes"]
        request.session["tipo"] = user["tipo"]
        return RedirectResponse(url="/dashboard", status_code=303)
    return templates.TemplateResponse(
        request,
        "login.html",
        {"erro": "Usuário ou senha inválidos."},
        status_code=401,
    )


@router_auth.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)
