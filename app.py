from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from routers.router_auth import router_auth
from routers.router_cadastros import obter_resumo, router_cadastros
from routers.router_config import router_config
from routers.router_usuarios import router_usuarios
from settings.database import DatabaseNotConfiguredError
from settings.snapshot import init_snapshot, start_scheduler
from settings.users import init_db, tipo_do_usuario

SESSION_SECRET = "salutem-script-session-secret-change-me"

app = FastAPI()
templates = Jinja2Templates(directory="templates")

PUBLIC_PATHS = {"/login", "/logout", "/health", "/docs", "/openapi.json", "/redoc"}


def required_permission(path: str) -> str | None:
    if path == "/dashboard" or path.startswith("/cadastros/resumo"):
        return "inicio"
    if path.startswith("/cadastros/condicoes"):
        return "condicoes"
    if path.startswith("/cadastros/obitos"):
        return "obitos"
    if path.startswith("/cadastros/cadastros"):
        return "inicio"
    if path.startswith("/configuracoes"):
        return "configuracoes"
    if path.startswith("/usuarios"):
        return "usuarios"
    return None


@app.middleware("http")
async def require_login(request: Request, call_next):
    path = request.url.path
    if path in PUBLIC_PATHS or path.startswith("/static"):
        return await call_next(request)
    if not request.session.get("user"):
        return RedirectResponse(url="/login", status_code=303)
    if "tipo" not in request.session:
        request.session["tipo"] = tipo_do_usuario(request.session.get("user")) or ""
    needed = required_permission(path)
    permissoes = request.session.get("permissoes") or []
    if needed and needed not in permissoes:
        return templates.TemplateResponse(
            request,
            "sem_permissao.html",
            {"permissao": needed},
            status_code=403,
        )
    return await call_next(request)


# SessionMiddleware por último = mais externo (session disponível no require_login)
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET)


@app.on_event("startup")
def startup():
    init_db()
    init_snapshot()
    start_scheduler()


@app.exception_handler(DatabaseNotConfiguredError)
async def database_not_configured_handler(request: Request, exc: DatabaseNotConfiguredError):
    return RedirectResponse(url="/configuracoes", status_code=303)


@app.get("/")
def root():
    return RedirectResponse(url="/dashboard", status_code=303)


@app.get("/health")
def health():
    return JSONResponse({"status": "ok"})


app.include_router(router_auth)
app.include_router(router_config)
app.include_router(router_usuarios)
app.include_router(router_cadastros)
app.add_api_route("/dashboard", obter_resumo, methods=["GET"], tags=["Cadastros Individuais"])
