from fastapi import APIRouter, Depends, Request, Query, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from sqlalchemy.orm import Session

from settings import snapshot as snap
from settings.database import get_session 

from typing import Optional, List
from datetime import date, timedelta
from urllib.parse import urlencode


router_cadastros = APIRouter(prefix="/cadastros", tags=["Cadastros Individuais"])

templates = Jinja2Templates(directory="templates")

# BACKLOG (MVP futuro — não implementado):
# - Filtro Profissional: f.co_dim_profissional -> tb_dim_profissional
#   (listar por unidade/equipe e aplicar AND no resumo).
# - Confirmar ds_tipo_saida_cadastro exato para "Mudou-se" após primeiro uso.
# - Avaliar se óbitos 30d entram no universo dos demais KPIs quando pesquisa=todos.

PERIODO_DIAS = {"7d": 7, "30d": 30, "90d": 90}
PESQUISA_OPCOES = {"ativo", "mudou_se", "todos"}

# chave URL -> (título, rótulo genitivo para "% dos X do município", predicado SQL whitelist)
CONDICOES_DETALHE = {
    "hipertensos": ("Hipertensos", "hipertensos", "f.st_hipertensao_arterial = 1"),
    "diabeticos": ("Diabéticos", "diabéticos", "f.st_diabete = 1"),
    "avc": ("AVC", "casos de AVC", "f.st_avc = 1"),
    "infarto": ("Infarto", "casos de infarto", "f.st_infarto = 1"),
    "cancer": ("Câncer", "casos de câncer", "f.st_cancer = 1"),
    "tuberculose": ("Tuberculose", "casos de tuberculose", "f.st_tuberculose = 1"),
    "hanseniase": ("Hanseníase", "casos de hanseníase", "f.st_hanseniase = 1"),
    "fumantes": ("Fumantes", "fumantes", "f.st_fumante = 1"),
    "uso_alcool": ("Uso de Álcool", "casos de uso de álcool", "f.st_alcool = 1"),
    "outras_drogas": ("Outras Drogas", "casos de outras drogas", "f.st_outra_droga = 1"),
    "acamados": ("Acamados", "acamados", "f.st_acamado = 1"),
    "domiciliados": ("Domiciliados", "domiciliados", "f.st_domiciliado = 1"),
    "internacao_12_meses": ("Internações (12m)", "internações", "f.st_internacao_12 = 1"),
    "saude_mental": ("Saúde Mental", "casos de saúde mental", "f.st_tratamento_psiquiatra = 1"),
    "plantas_medicinais": ("Plantas Medicinais", "casos de plantas medicinais", "f.st_usa_planta_medicinal = 1"),
    "pics": ("Práticas Integrativas (PICs)", "casos de PICs", "f.st_pic = 1"),
    "gestantes": ("Gestantes", "gestantes", "f.st_gestante = 1"),
    "morador_de_rua": ("Situação de Rua", "pessoas em situação de rua", "f.st_morador_rua = 1"),
}


def _normalizar_condicoes(condicao: Optional[List[str]]) -> list[str]:
    if not condicao:
        return []
    vistas: list[str] = []
    for chave in condicao:
        if not chave or chave in vistas:
            continue
        if chave not in CONDICOES_DETALHE:
            raise HTTPException(status_code=404, detail=f"Condição inválida: {chave}")
        vistas.append(chave)
    return vistas


def _resumo_url(
    condicoes: list[str],
    filtros: Optional[dict] = None,
    toggle: Optional[str] = None,
    clear_unidade: bool = False,
    clear_condicoes: bool = False,
) -> str:
    """Monta URL do resumo preservando filtros GET (exceto quando clear_*)."""
    filtros = dict(filtros or {})
    keys = [] if clear_condicoes else list(condicoes)
    if toggle:
        if toggle in keys:
            keys = [k for k in keys if k != toggle]
        else:
            keys.append(toggle)

    pairs: list[tuple[str, str]] = [("condicao", k) for k in keys]

    unidade = None if clear_unidade else filtros.get("unidade")
    if unidade:
        pairs.append(("unidade", str(unidade)))

    for campo in ("micro_area", "pesquisa", "idade_min", "idade_max"):
        val = filtros.get(campo)
        if val is None or val == "":
            continue
        if campo == "pesquisa" and val == "ativo":
            continue  # padrão — não polui a URL
        pairs.append((campo, str(val)))

    data_nasc = filtros.get("data_nascimento")
    if data_nasc:
        pairs.append(("data_nascimento", str(data_nasc)))

    if not pairs:
        return "/cadastros/resumo"
    return "/cadastros/resumo?" + urlencode(pairs)


def _parse_filtros_resumo(
    unidade: Optional[str] = None,
    idade_min: Optional[str] = None,
    idade_max: Optional[str] = None,
    data_nascimento: Optional[str] = None,
    micro_area: Optional[str] = None,
    pesquisa: Optional[str] = None,
) -> dict:
    unidade = unidade.strip() if unidade else None
    micro_area = micro_area.strip() if micro_area else None
    pesquisa = pesquisa if pesquisa in PESQUISA_OPCOES else "ativo"

    idade_min_val: Optional[int] = None
    if idade_min not in (None, ""):
        idade_min_val = max(0, min(125, int(idade_min)))

    idade_max_val: Optional[int] = None
    if idade_max not in (None, ""):
        idade_max_val = max(0, min(125, int(idade_max)))

    data_nascimento_val: Optional[date] = None
    if data_nascimento not in (None, ""):
        data_nascimento_val = date.fromisoformat(data_nascimento)

    # microárea só faz sentido com unidade
    if not unidade:
        micro_area = None

    return {
        "unidade": unidade,
        "idade_min": idade_min_val,
        "idade_max": idade_max_val,
        "data_nascimento": data_nascimento_val,
        "micro_area": micro_area,
        "pesquisa": pesquisa,
    }




def _montar_resumo(
    filtros: Optional[dict] = None,
    predicados: Optional[list[str]] = None,
) -> dict:
    """Monta o contexto da home a partir da cópia local da última ficha."""
    return snap.agregar_resumo(filtros, predicados)


def _listas_filtros_resumo(unidade: Optional[str] = None) -> dict:
    return snap.listas_resumo(unidade)


@router_cadastros.get("/resumo")
def obter_resumo(
    request: Request,
    unidade: Optional[str] = Query(None),
    condicao: Optional[List[str]] = Query(None),
    idade_min: Optional[str] = Query(None),
    idade_max: Optional[str] = Query(None),
    data_nascimento: Optional[str] = Query(None),
    micro_area: Optional[str] = Query(None),
    pesquisa: Optional[str] = Query(None),
):
    filtros = _parse_filtros_resumo(
        unidade=unidade,
        idade_min=idade_min,
        idade_max=idade_max,
        data_nascimento=data_nascimento,
        micro_area=micro_area,
        pesquisa=pesquisa,
    )
    condicoes_ativas = _normalizar_condicoes(condicao)
    predicados = [CONDICOES_DETALHE[c][2] for c in condicoes_ativas]
    condicoes_labels = [CONDICOES_DETALHE[c][0] for c in condicoes_ativas]

    ctx = _montar_resumo(filtros=filtros, predicados=predicados)
    listas = _listas_filtros_resumo(unidade=filtros.get("unidade"))

    filtros_url = {
        "unidade": filtros.get("unidade"),
        "idade_min": filtros.get("idade_min"),
        "idade_max": filtros.get("idade_max"),
        "data_nascimento": filtros.get("data_nascimento"),
        "micro_area": filtros.get("micro_area"),
        "pesquisa": filtros.get("pesquisa"),
    }

    toggle_urls = {
        chave: _resumo_url(condicoes_ativas, filtros_url, toggle=chave)
        for chave in CONDICOES_DETALHE
    }

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "request": request,
            "condicoes_ativas": condicoes_ativas,
            "condicoes_labels": condicoes_labels,
            "toggle_urls": toggle_urls,
            "resumo_url_atual": _resumo_url(condicoes_ativas, filtros_url),
            "resumo_url_sem_unidade": _resumo_url(condicoes_ativas, filtros_url, clear_unidade=True),
            "resumo_url_limpo": _resumo_url([], filtros_url, clear_condicoes=True),
            "filtros_ativos": filtros,
            "obitos_30_inicio": (date.today() - timedelta(days=30)).isoformat(),
            **snap.contexto_visualizacao(),
            **listas,
            **ctx,
        },
    )


@router_cadastros.get("/resumo/condicao/{condicao}")
def obter_resumo_por_condicao(
    condicao: str,
    unidade: Optional[str] = Query(None),
):
    if condicao not in CONDICOES_DETALHE:
        raise HTTPException(status_code=404, detail="Condição não encontrada")
    target = _resumo_url([condicao], {"unidade": unidade.strip() if unidade else None})
    return RedirectResponse(url=target, status_code=307)


@router_cadastros.get("/condicoes")
def obter_condicoes(
    request: Request,
    periodo: Optional[str] = Query(None),
    unidade: Optional[str] = Query(None),
    idade_min: Optional[str] = Query(None),
    idade_max: Optional[str] = Query(None),
    area: Optional[str] = Query(None),
    data_nascimento: Optional[str] = Query(None),
):
    periodo = periodo if periodo in PERIODO_DIAS else None
    unidade = unidade.strip() if unidade else None
    area = area.strip() if area else None

    idade_min_val: Optional[int] = None
    if idade_min not in (None, ""):
        idade_min_val = max(0, min(125, int(idade_min)))

    idade_max_val: Optional[int] = None
    if idade_max not in (None, ""):
        idade_max_val = max(0, min(125, int(idade_max)))

    data_nascimento_val: Optional[date] = None
    if data_nascimento not in (None, ""):
        data_nascimento_val = date.fromisoformat(data_nascimento)

    data_inicio = None
    if periodo:
        data_inicio = date.today() - timedelta(days=PERIODO_DIAS[periodo])

    res_condicoes = snap.agregar_condicoes({
        "unidade": unidade,
        "idade_min": idade_min_val,
        "idade_max": idade_max_val,
        "area": area,
        "data_nascimento": data_nascimento_val,
        "data_inicio": data_inicio,
    })
    listas = snap.listas_condicoes()

    return templates.TemplateResponse(
        request=request,
        name="condicoes.html",
        context={
            "request": request,
            "condicoes": res_condicoes,
            "lista_unidades": listas["lista_unidades"],
            "lista_areas": listas["lista_areas"],
            "periodo_ativo": periodo,
            "data_inicio": data_inicio,
            "filtros_ativos": {
                "unidade": unidade,
                "idade_min": idade_min_val,
                "idade_max": idade_max_val,
                "area": area,
                "data_nascimento": data_nascimento_val,
                "periodo": periodo,
            },
            **snap.contexto_visualizacao(),
        },
    )


@router_cadastros.get("/condicoes/{condicao}")
def detalhe_condicao_por_unidade(
    request: Request,
    condicao: str,
):
    if condicao not in CONDICOES_DETALHE:
        raise HTTPException(status_code=404, detail="Condição não encontrada")

    condicao_label, condicao_label_genitivo, predicado = CONDICOES_DETALHE[condicao]
    linhas = snap.condicao_por_unidade(predicado)
    total_geral = sum((r["total"] or 0) for r in linhas)

    for linha in linhas:
        total = linha["total"] or 0
        linha["pct"] = round((total / total_geral) * 100, 1) if total_geral else 0.0

    return templates.TemplateResponse(
        request=request,
        name="condicao_unidades.html",
        context={
            "request": request,
            "condicao": condicao,
            "condicao_label": condicao_label,
            "condicao_label_genitivo": condicao_label_genitivo,
            "linhas": linhas,
            "total_geral": total_geral,
            **snap.contexto_visualizacao(),
        },
    )


def _parse_data_filtro(valor: Optional[str]) -> Optional[date]:
    if valor is None or not str(valor).strip():
        return None
    try:
        return date.fromisoformat(str(valor).strip())
    except ValueError:
        return None


def _url_obitos(
    nome: Optional[str],
    data_inicio: Optional[date],
    data_fim: Optional[date],
    unidade: Optional[str],
    page: Optional[int] = None,
) -> str:
    pairs: list[tuple[str, str]] = []
    if nome:
        pairs.append(("nome", nome))
    if data_inicio:
        pairs.append(("data_inicio", data_inicio.isoformat()))
    if data_fim:
        pairs.append(("data_fim", data_fim.isoformat()))
    if unidade:
        pairs.append(("unidade", unidade))
    if page and page > 1:
        pairs.append(("page", str(page)))
    if not pairs:
        return "/cadastros/obitos"
    return "/cadastros/obitos?" + urlencode(pairs)


@router_cadastros.get("/obitos")
def listar_obitos(
    request: Request,
    nome: Optional[str] = Query(None),
    data_inicio: Optional[str] = Query(None),
    data_fim: Optional[str] = Query(None),
    unidade: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
):
    limit = 15
    nome = nome.strip() if nome else None
    unidade = unidade.strip() if unidade else None
    inicio = _parse_data_filtro(data_inicio)
    fim = _parse_data_filtro(data_fim)

    pagina = snap.listar_obitos(nome, inicio, fim, unidade, page, limit)
    page = pagina["page"]
    total_registros = pagina["total_registros"]
    total_pages = pagina["total_pages"]
    resultados = pagina["obitos"]
    offset = (page - 1) * limit
    listas = _listas_filtros_resumo()
    inicio_exibicao = offset + 1 if total_registros else 0
    fim_exibicao = min(offset + len(resultados), total_registros)

    return templates.TemplateResponse(
        request=request,
        name="obitos.html",
        context={
            "request": request,
            "obitos": resultados,
            "page": page,
            "total_pages": total_pages,
            "total_registros": total_registros,
            "inicio_exibicao": inicio_exibicao,
            "fim_exibicao": fim_exibicao,
            "lista_unidades": listas["lista_unidades"],
            "filtros": {
                "nome": nome or "",
                "data_inicio": inicio.isoformat() if inicio else "",
                "data_fim": fim.isoformat() if fim else "",
                "unidade": unidade or "",
            },
            "url_anterior": _url_obitos(nome, inicio, fim, unidade, page - 1) if page > 1 else None,
            "url_proxima": _url_obitos(nome, inicio, fim, unidade, page + 1) if page < total_pages else None,
            **snap.contexto_visualizacao(),
        },
    )


@router_cadastros.get("/cadastros", tags=["listar"])
def listar_cadastros(
    request: Request,
    nome: Optional[str] = None,
    cpf: Optional[str] = None,
    cns: Optional[str] = None,
    nome_mae: Optional[str] = None,
    nome_pai: Optional[str] = None,
    data_nascimento: Optional[date] = None,
    page: int = Query(1, ge=1),
    session: Session = Depends(get_session)
):
    limit = 15
    offset = (page - 1) * limit
    
    # 1. Base das Queries
    query_base = """
        SELECT co_seq_cidadao, no_cidadao, nu_cpf, nu_cns, dt_nascimento, no_mae, no_pai 
        FROM tb_cidadao 
        WHERE st_ativo = 1 AND (st_faleceu = 0 OR st_faleceu IS NULL)
    """
    count_base = """
        SELECT COUNT(*) as total 
        FROM tb_cidadao 
        WHERE st_ativo = 1 AND (st_faleceu = 0 OR st_faleceu IS NULL)
    """
    
    # 2. Dicionário de Filtros Dinâmicos
    # Formato: "nome_do_parametro": ("condição_sql", valor_processado)
    filtros = {
        "nome": ("no_cidadao ILIKE :nome", f"%{nome}%" if nome else None),
        "cpf": ("nu_cpf = :cpf", cpf),
        "cns": ("nu_cns = :cns", cns),
        "nome_mae": ("no_mae ILIKE :nome_mae", f"%{nome_mae}%" if nome_mae else None),
        "nome_pai": ("no_pai ILIKE :nome_pai", f"%{nome_pai}%" if nome_pai else None),
        "dt_nascimento": ("dt_nascimento = :dt_nascimento", data_nascimento)
    }

    params = {}
    clausulas_extras = ""

    for chave, (condicao_sql, valor) in filtros.items():
        if valor: # Se o usuário preencheu o campo
            clausulas_extras += f" AND {condicao_sql}"
            params[chave] = valor
            
    # 4. Junta tudo e adiciona a paginação
    query_str = query_base + clausulas_extras + " ORDER BY no_cidadao ASC LIMIT :limit OFFSET :offset"
    count_str = count_base + clausulas_extras
    
    params['limit'] = limit
    params['offset'] = offset
    
    # 5. Executa no banco
    total_registros = session.execute(text(count_str), params).scalar()
    resultados = session.execute(text(query_str), params).mappings().all()
    
    total_pages = (total_registros + limit - 1) // limit

    return templates.TemplateResponse(
        request=request,
        name="cadastros.html",
        context={
            "cadastros": resultados,
            "page": page,
            "total_pages": total_pages,
            "total_registros": total_registros,
            "filtros_ativos": {
                "nome": nome, "cpf": cpf, "cns": cns, 
                "nome_mae": nome_mae, "nome_pai": nome_pai, 
                "data_nascimento": data_nascimento
            }
        }
    )