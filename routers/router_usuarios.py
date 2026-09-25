from typing import List, Optional

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from settings.users import (
    PERMISSION_LABELS,
    PERMISSIONS,
    TIPO_LABELS,
    TIPO_USUARIO,
    create_user,
    delete_user,
    list_users,
    update_user,
)

router_usuarios = APIRouter(prefix="/usuarios", tags=["Usuários"])
templates = Jinja2Templates(directory="templates")


def _page(
    request: Request,
    erro: str | None = None,
    mensagem: str | None = None,
    form: dict | None = None,
):
    return templates.TemplateResponse(
        request,
        "usuarios.html",
        {
            "usuarios": list_users(),
            "permissoes_catalogo": [(p, PERMISSION_LABELS[p]) for p in PERMISSIONS],
            "tipos": [(codigo, TIPO_LABELS[codigo]) for codigo in TIPO_LABELS],
            "erro": erro,
            "mensagem": mensagem,
            "form": form,
        },
    )


def _sync_session(request: Request, user_id: int, username_antes: str | None) -> None:
    if not username_antes or request.session.get("user") != username_antes:
        return
    for user in list_users():
        if user["id"] == user_id:
            request.session["user"] = user["username"]
            request.session["permissoes"] = user["permissoes"]
            request.session["tipo"] = user["tipo"]
            return


@router_usuarios.get("")
def usuarios_page(request: Request):
    return _page(request)


@router_usuarios.post("")
def usuarios_criar(
    request: Request,
    nome: str = Form(""),
    username: str = Form(...),
    password: str = Form(...),
    tipo: str = Form(TIPO_USUARIO),
    permissoes: Optional[List[str]] = Form(None),
):
    escolhidas = permissoes or []
    erro = create_user(username, password, escolhidas, nome, tipo)
    if erro:
        return _page(
            request,
            erro=erro,
            form={
                "id": None,
                "nome": nome,
                "username": username,
                "tipo": tipo,
                "permissoes": escolhidas,
                "is_admin": False,
            },
        )
    return RedirectResponse(url="/usuarios", status_code=303)


@router_usuarios.post("/{user_id}")
def usuarios_atualizar(
    request: Request,
    user_id: int,
    nome: str = Form(""),
    username: str = Form(""),
    password: str = Form(""),
    tipo: str = Form(TIPO_USUARIO),
    permissoes: Optional[List[str]] = Form(None),
):
    escolhidas = permissoes or []
    antes = next((u for u in list_users() if u["id"] == user_id), None)
    erro = update_user(user_id, escolhidas, password, nome, username, tipo)
    if erro:
        return _page(
            request,
            erro=erro,
            form={
                "id": user_id,
                "nome": nome,
                "username": username,
                "tipo": tipo,
                "permissoes": escolhidas,
                "is_admin": bool(antes and antes["is_admin"]),
            },
        )
    _sync_session(request, user_id, antes["username"] if antes else None)
    return RedirectResponse(url="/usuarios", status_code=303)


@router_usuarios.post("/{user_id}/excluir")
def usuarios_excluir(request: Request, user_id: int):
    erro = delete_user(user_id)
    if erro:
        return _page(request, erro=erro)
    return RedirectResponse(url="/usuarios", status_code=303)
