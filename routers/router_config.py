from datetime import datetime
from urllib.parse import urlencode

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import SQLAlchemyError

from settings.database import configure_engine, test_connection
from settings.snapshot import em_execucao, horario, iniciar, salvar_horario, ultima_execucao
from settings.db_config import (
    build_database_url,
    get_form_defaults,
    load_config,
    parse_database_url,
    save_config,
)
from settings.settings import Settings

router_config = APIRouter(tags=["Configurações"])
templates = Jinja2Templates(directory="templates")


def _resolve_password(senha: str) -> str:
    if senha.strip():
        return senha
    existing = load_config()
    if existing and existing.get("senha"):
        return existing["senha"]
    from_env = parse_database_url(Settings().DATABASE_URL or "")
    if from_env and from_env.get("senha"):
        return from_env["senha"]
    return ""


@router_config.get("/configuracoes")
def configuracoes_page(request: Request):
    form = get_form_defaults()
    return templates.TemplateResponse(
        request,
        "configuracoes.html",
        {
            "form": form,
            "mensagem": None,
            "erro": None,
            "sucesso": False,
        },
    )


@router_config.post("/configuracoes")
def configuracoes_salvar(
    request: Request,
    usuario: str = Form(...),
    senha: str = Form(""),
    host: str = Form(...),
    porta: str = Form(...),
    database: str = Form(...),
    acao: str = Form("salvar"),
):
    form = {
        "usuario": usuario.strip(),
        "senha": "",
        "host": host.strip(),
        "porta": porta.strip(),
        "database": database.strip(),
        "has_saved_password": False,
    }

    resolved_senha = _resolve_password(senha)
    form["has_saved_password"] = bool(resolved_senha)

    if not all([form["usuario"], form["host"], form["porta"], form["database"]]):
        return templates.TemplateResponse(
            request,
            "configuracoes.html",
            {
                "form": form,
                "mensagem": None,
                "erro": "Preencha usuário, host, porta e nome do banco.",
                "sucesso": False,
            },
            status_code=400,
        )

    if not resolved_senha:
        return templates.TemplateResponse(
            request,
            "configuracoes.html",
            {
                "form": form,
                "mensagem": None,
                "erro": "Informe a senha do banco de dados.",
                "sucesso": False,
            },
            status_code=400,
        )

    try:
        porta_int = int(form["porta"])
    except ValueError:
        return templates.TemplateResponse(
            request,
            "configuracoes.html",
            {
                "form": form,
                "mensagem": None,
                "erro": "A porta deve ser um número.",
                "sucesso": False,
            },
            status_code=400,
        )

    url = build_database_url(
        usuario=form["usuario"],
        senha=resolved_senha,
        host=form["host"],
        porta=porta_int,
        database=form["database"],
    )

    try:
        test_connection(url)
    except SQLAlchemyError as exc:
        return templates.TemplateResponse(
            request,
            "configuracoes.html",
            {
                "form": form,
                "mensagem": None,
                "erro": f"Falha na conexão: {exc.__class__.__name__}. Verifique os dados.",
                "sucesso": False,
            },
            status_code=400,
        )
    except Exception as exc:
        return templates.TemplateResponse(
            request,
            "configuracoes.html",
            {
                "form": form,
                "mensagem": None,
                "erro": f"Falha na conexão: {exc}",
                "sucesso": False,
            },
            status_code=400,
        )

    if acao == "testar":
        form["has_saved_password"] = True
        return templates.TemplateResponse(
            request,
            "configuracoes.html",
            {
                "form": form,
                "mensagem": "Conexão testada com sucesso.",
                "erro": None,
                "sucesso": True,
            },
        )

    save_config(
        {
            "usuario": form["usuario"],
            "senha": resolved_senha,
            "host": form["host"],
            "porta": porta_int,
            "database": form["database"],
        }
    )
    configure_engine(url)
    form["has_saved_password"] = True

    return templates.TemplateResponse(
        request,
        "configuracoes.html",
        {
            "form": form,
            "mensagem": "Configuração salva e conexão aplicada.",
            "erro": None,
            "sucesso": True,
        },
    )


def _formatar_momento(valor: str | None) -> str | None:
    if not valor:
        return None
    try:
        return datetime.fromisoformat(valor).strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return valor


def _ultima_para_tela() -> dict | None:
    ultima = ultima_execucao()
    if not ultima:
        return None
    status = {
        "executando": "Em andamento",
        "ok": "Concluída",
        "erro": "Erro",
    }
    origem = {
        "agenda": "Agendada",
        "manual": "Manual",
    }
    ultima["iniciado_em"] = _formatar_momento(ultima.get("iniciado_em"))
    ultima["finalizado_em"] = _formatar_momento(ultima.get("finalizado_em"))
    ultima["status_label"] = status.get(ultima.get("status"), ultima.get("status"))
    ultima["origem_label"] = origem.get(ultima.get("origem"), ultima.get("origem"))
    return ultima


def _extracao_page(request: Request, mensagem: str | None = None, erro: str | None = None):
    return templates.TemplateResponse(
        request,
        "extracao.html",
        {
            "horario": horario(),
            "executando": em_execucao(),
            "ultima": _ultima_para_tela(),
            "mensagem": mensagem,
            "erro": erro,
        },
    )


@router_config.get("/configuracoes/extracao")
def extracao_page(
    request: Request,
    mensagem: str | None = Query(None),
    erro: str | None = Query(None),
):
    if request.session.get("tipo") != "administrador":
        return templates.TemplateResponse(
            request,
            "sem_permissao.html",
            {"permissao": "administrador"},
            status_code=403,
        )
    return _extracao_page(request, mensagem=mensagem, erro=erro)


@router_config.post("/configuracoes/extracao")
def extracao_submit(
    request: Request,
    acao: str = Form(...),
    horario_valor: str = Form("", alias="horario"),
):
    if request.session.get("tipo") != "administrador":
        return templates.TemplateResponse(
            request,
            "sem_permissao.html",
            {"permissao": "administrador"},
            status_code=403,
        )
    if acao == "salvar":
        falha = salvar_horario(horario_valor)
        if falha:
            destino = "/configuracoes/extracao?" + urlencode({"erro": falha})
        else:
            destino = "/configuracoes/extracao?" + urlencode({"mensagem": "Horário salvo."})
        return RedirectResponse(url=destino, status_code=303)
    if acao == "extrair":
        falha = iniciar("manual")
        if falha:
            destino = "/configuracoes/extracao?" + urlencode({"erro": falha})
        else:
            destino = "/configuracoes/extracao?" + urlencode({"mensagem": "Extração iniciada."})
        return RedirectResponse(url=destino, status_code=303)
    return RedirectResponse(url="/configuracoes/extracao", status_code=303)
