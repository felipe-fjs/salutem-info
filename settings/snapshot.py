"""Cópia local da última ficha individual de cada cidadão.

O PostgreSQL do e-SUS só é consultado na extração. Resumo, condições e óbitos
leem snapshot_cidadao no mesmo SQLite do app (data/app.db).
"""

from __future__ import annotations

import logging
import re
import sqlite3
import threading
import time
from datetime import date, datetime, timedelta

from sqlalchemy import text

from settings.database import get_engine
from settings.users import DB_PATH

log = logging.getLogger(__name__)

HORARIO_PADRAO = "05:00"
_HORARIO_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_PRED_RE = re.compile(r"^(?:f\.)?(st_[a-z0-9_]+) = 1$")

_lock = threading.Lock()
_rodando = False
_agenda_iniciada = False

IDENTIDADE = (
    "co_seq_cidadao",
    "no_cidadao",
    "no_sexo",
    "dt_nascimento",
    "nu_cpf",
    "nu_cns",
    "st_ativo",
    "st_faleceu",
    "nu_cnes",
    "no_unidade_saude",
    "nu_micro_area",
    "no_bairro",
    "dt_obito",
    "dt_registro",
    "ds_tipo_saida",
)

FLAGS = (
    "st_fumante",
    "st_alcool",
    "st_outra_droga",
    "st_hipertensao_arterial",
    "st_diabete",
    "st_avc",
    "st_infarto",
    "st_hanseniase",
    "st_tuberculose",
    "st_cancer",
    "st_internacao_12",
    "st_tratamento_psiquiatra",
    "st_gestante",
    "st_acamado",
    "st_domiciliado",
    "st_usa_planta_medicinal",
    "st_pic",
    "st_deficiencia",
    "st_defi_visual",
    "st_defi_auditiva",
    "st_defi_intelectual_cognitiva",
    "st_defi_fisica",
    "st_defi_outra",
    "st_doenca_respiratoria",
    "st_doenca_respira_asma",
    "st_doenca_respira_dpoc_enfisem",
    "st_doenca_respira_outra",
    "st_doenca_respira_n_sabe",
    "st_doenca_cardiaca",
    "st_doenca_card_insuficiencia",
    "st_doenca_card_outro",
    "st_doenca_card_n_sabe",
    "st_problema_rins",
    "st_problema_rins_insuficiencia",
    "st_problema_rins_outro",
    "st_problema_rins_nao_sabe",
    "st_frequenta_cuidador",
    "st_participa_grupo_comunitario",
    "st_plano_saude_privado",
    "st_alimentos_acab_sem_dinheiro",
    "st_comeu_que_tinha_dnheir_acab",
    "st_morador_rua",
    "st_recusa_cadastro",
    "st_responsavel_familiar",
)

FLAG_SET = frozenset(FLAGS)
COLUNAS = IDENTIDADE + FLAGS

EQ1 = (
    ("fumantes", "st_fumante"),
    ("uso_alcool", "st_alcool"),
    ("outras_drogas", "st_outra_droga"),
    ("hipertensos", "st_hipertensao_arterial"),
    ("diabeticos", "st_diabete"),
    ("avc", "st_avc"),
    ("infarto", "st_infarto"),
    ("hanseniase", "st_hanseniase"),
    ("tuberculose", "st_tuberculose"),
    ("cancer", "st_cancer"),
    ("internacao_12_meses", "st_internacao_12"),
    ("saude_mental", "st_tratamento_psiquiatra"),
    ("gestantes", "st_gestante"),
    ("acamados", "st_acamado"),
    ("domiciliados", "st_domiciliado"),
    ("plantas_medicinais", "st_usa_planta_medicinal"),
    ("pics", "st_pic"),
    ("deficiencia_total", "st_deficiencia"),
    ("deficiencia_visual", "st_defi_visual"),
    ("deficiencia_auditiva", "st_defi_auditiva"),
    ("deficiencia_intelectual", "st_defi_intelectual_cognitiva"),
    ("deficiencia_fisica", "st_defi_fisica"),
    ("deficiencia_outra", "st_defi_outra"),
    ("respiratoria_total", "st_doenca_respiratoria"),
    ("respiratoria_asma", "st_doenca_respira_asma"),
    ("respiratoria_dpoc", "st_doenca_respira_dpoc_enfisem"),
    ("respiratoria_outra", "st_doenca_respira_outra"),
    ("respiratoria_nao_sabe", "st_doenca_respira_n_sabe"),
    ("cardiaca_total", "st_doenca_cardiaca"),
    ("cardiaca_insuficiencia", "st_doenca_card_insuficiencia"),
    ("cardiaca_outra", "st_doenca_card_outro"),
    ("cardiaca_nao_sabe", "st_doenca_card_n_sabe"),
    ("rins_total", "st_problema_rins"),
    ("rins_insuficiencia", "st_problema_rins_insuficiencia"),
    ("rins_outra", "st_problema_rins_outro"),
    ("rins_nao_sabe", "st_problema_rins_nao_sabe"),
    ("cuidador_tradicional", "st_frequenta_cuidador"),
    ("grupo_comunitario", "st_participa_grupo_comunitario"),
    ("plano_saude_privado", "st_plano_saude_privado"),
    ("alimentos_acabaram", "st_alimentos_acab_sem_dinheiro"),
    ("comeu_alguns_alimentos", "st_comeu_que_tinha_dnheir_acab"),
    ("morador_de_rua", "st_morador_rua"),
    ("recusa_cadastro", "st_recusa_cadastro"),
    ("responsavel_familiar", "st_responsavel_familiar"),
)

ISNULL = (
    ("avc_nao_inf", "st_avc"),
    ("infarto_nao_inf", "st_infarto"),
    ("cancer_nao_inf", "st_cancer"),
    ("tuberculose_nao_inf", "st_tuberculose"),
    ("hanseniase_nao_inf", "st_hanseniase"),
    ("fumantes_nao_inf", "st_fumante"),
    ("alcool_nao_inf", "st_alcool"),
    ("drogas_nao_inf", "st_outra_droga"),
    ("internacao_nao_inf", "st_internacao_12"),
    ("saude_mental_nao_inf", "st_tratamento_psiquiatra"),
    ("plantas_nao_inf", "st_usa_planta_medicinal"),
    ("pics_nao_inf", "st_pic"),
    ("hipertensao_nao_inf", "st_hipertensao_arterial"),
    ("diabete_nao_inf", "st_diabete"),
    ("acamados_nao_inf", "st_acamado"),
    ("domiciliados_nao_inf", "st_domiciliado"),
)

DEMO_KEYS = (
    "total_cadastros_unicos",
    "sexo_masculino",
    "sexo_feminino",
    "menores_18",
    "adultos",
    "idosos",
    "cadastros_com_cpf",
    "cadastros_sem_cpf",
    "cadastros_com_cns",
    "sem_cpf_e_cns",
)

COND_KEYS = ("total_base",) + tuple(a for a, _ in EQ1) + tuple(a for a, _ in ISNULL)

_IDADE = """(
    CASE
        WHEN dt_nascimento IS NULL OR length(dt_nascimento) < 10 THEN NULL
        ELSE (
            CAST(strftime('%Y', 'now', 'localtime') AS INTEGER) - CAST(substr(dt_nascimento, 1, 4) AS INTEGER)
            - CASE
                WHEN strftime('%m-%d', 'now', 'localtime') < substr(dt_nascimento, 6, 5) THEN 1
                ELSE 0
            END
        )
    END
)"""

_CPF_OK = "(nu_cpf IS NOT NULL AND TRIM(nu_cpf) <> '' AND nu_cpf <> '0')"
_CNS_OK = "(nu_cns IS NOT NULL AND TRIM(nu_cns) <> '' AND nu_cns <> '0')"


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _tabela_existe(conn: sqlite3.Connection, nome: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (nome,),
    ).fetchone()
    return row is not None


def init_snapshot() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS snapshot_execucao (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                iniciado_em TEXT NOT NULL,
                finalizado_em TEXT,
                status TEXT NOT NULL,
                quantidade INTEGER,
                mensagem TEXT,
                origem TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS snapshot_config (
                chave TEXT PRIMARY KEY,
                valor TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "INSERT OR IGNORE INTO snapshot_config (chave, valor) VALUES ('horario', ?)",
            (HORARIO_PADRAO,),
        )
        conn.execute(
            """
            UPDATE snapshot_execucao
            SET status = 'erro',
                finalizado_em = ?,
                mensagem = 'Extração interrompida antes de terminar.'
            WHERE status = 'executando'
            """,
            (_agora(),),
        )
        conn.commit()


def horario() -> str:
    init_snapshot()
    with _connect() as conn:
        row = conn.execute(
            "SELECT valor FROM snapshot_config WHERE chave = 'horario'"
        ).fetchone()
    if row and _HORARIO_RE.match(row["valor"] or ""):
        return row["valor"]
    return HORARIO_PADRAO


def salvar_horario(valor: str) -> str | None:
    valor = (valor or "").strip()
    if len(valor) >= 5 and valor[2] == ":":
        valor = valor[:5]
    if not _HORARIO_RE.match(valor):
        return "Informe um horário válido (HH:MM)."
    init_snapshot()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO snapshot_config (chave, valor) VALUES ('horario', ?)
            ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor
            """,
            (valor,),
        )
        conn.commit()
    return None


def em_execucao() -> bool:
    with _lock:
        return _rodando


def tem_snapshot() -> bool:
    init_snapshot()
    with _connect() as conn:
        return _tabela_existe(conn, "snapshot_cidadao")


def ultima_execucao() -> dict | None:
    init_snapshot()
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT id, iniciado_em, finalizado_em, status, quantidade, mensagem, origem
            FROM snapshot_execucao
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
    if row is None:
        return None
    return dict(row)


def contexto_visualizacao() -> dict:
    ok = _ultima_ok()
    tem = tem_snapshot()
    return {
        "sem_extracao": not tem,
        "extracao_em": _formatar(ok["finalizado_em"]) if ok and tem else None,
    }


def iniciar(origem: str) -> str | None:
    global _rodando
    if origem not in ("agenda", "manual"):
        return "Origem de extração inválida."
    with _lock:
        if _rodando:
            return "Já existe uma extração em andamento."
        _rodando = True
    threading.Thread(
        target=_executar,
        args=(origem,),
        name="extracao-esus",
        daemon=True,
    ).start()
    return None


def start_scheduler() -> None:
    global _agenda_iniciada
    init_snapshot()
    with _lock:
        if _agenda_iniciada:
            return
        _agenda_iniciada = True
    threading.Thread(target=_agenda_loop, name="extracao-agenda", daemon=True).start()


def agregar_resumo(filtros: dict | None = None, predicados: list[str] | None = None) -> dict:
    filtros = dict(filtros or {"pesquisa": "ativo"})
    unidade = filtros.get("unidade")
    vazio = _resumo_vazio(unidade)
    if not tem_snapshot():
        return vazio

    where, params = _where(filtros, predicados)
    row = _contar(where, params)

    filtros_unidades = dict(filtros)
    filtros_unidades["unidade"] = None
    where_u, params_u = _where(filtros_unidades, predicados)
    unidades = _por_unidade(where_u, params_u)

    filtros_obito = dict(filtros)
    if filtros_obito.get("pesquisa") == "ativo":
        filtros_obito["pesquisa"] = "todos"
    where_o, params_o = _where(filtros_obito, predicados)
    obitos = _escalar(
        f"""
        SELECT COUNT(*)
        FROM snapshot_cidadao
        WHERE dt_obito IS NOT NULL AND TRIM(dt_obito) <> ''
        AND dt_obito >= ?
        {where_o}
        """,
        [(date.today() - timedelta(days=30)).isoformat(), *params_o],
    )

    nome_unidade = None
    if unidade:
        for item in unidades:
            if item.get("nu_cnes") == unidade:
                nome_unidade = item.get("no_unidade_saude")
                break

    demo = {k: int(row.get(k) or 0) for k in DEMO_KEYS}
    cond = {k: int(row.get(k) or 0) for k in COND_KEYS}
    return {
        "resumo_cidadao": demo,
        "condicoes": cond,
        "cadastros_por_unidade": unidades,
        "total_geral_unidades": sum(item["total_cadastros"] for item in unidades),
        "unidade_ativa": unidade,
        "nome_unidade": nome_unidade,
        "obitos_30_dias": obitos,
    }


def agregar_condicoes(filtros: dict) -> dict:
    zeros = {k: 0 for k in COND_KEYS}
    if not tem_snapshot():
        return zeros
    where, params = _where(filtros, ativo_fixo=True)
    row = _contar(where, params)
    return {k: int(row.get(k) or 0) for k in COND_KEYS}


def condicao_por_unidade(predicado: str) -> list[dict]:
    if not tem_snapshot():
        return []
    coluna = _coluna_predicado(predicado)
    where, params = _where({}, ativo_fixo=True, predicados=[f"{coluna} = 1"])
    with _connect() as conn:
        rows = conn.execute(
            f"""
            SELECT
                COALESCE(NULLIF(TRIM(no_unidade_saude), ''), 'Sem unidade registrada') AS no_unidade_saude,
                nu_cnes,
                COUNT(*) AS total
            FROM snapshot_cidadao
            WHERE 1 = 1
            {where}
            GROUP BY 1, 2
            ORDER BY total DESC
            """,
            params,
        ).fetchall()
    return [
        {
            "no_unidade_saude": r["no_unidade_saude"],
            "nu_cnes": r["nu_cnes"],
            "total": int(r["total"] or 0),
        }
        for r in rows
    ]


def listas_resumo(unidade: str | None = None) -> dict:
    if not tem_snapshot():
        return {"lista_unidades": [], "lista_micro_areas": []}
    with _connect() as conn:
        unidades = conn.execute(
            """
            SELECT DISTINCT
                nu_cnes,
                COALESCE(NULLIF(TRIM(no_unidade_saude), ''), 'Sem unidade') AS no_unidade_saude
            FROM snapshot_cidadao
            WHERE nu_cnes IS NOT NULL AND TRIM(nu_cnes) <> ''
            ORDER BY no_unidade_saude ASC
            """
        ).fetchall()
        micros: list[sqlite3.Row] = []
        if unidade:
            micros = conn.execute(
                """
                SELECT DISTINCT nu_micro_area
                FROM snapshot_cidadao
                WHERE nu_cnes = ?
                AND nu_micro_area IS NOT NULL
                AND TRIM(nu_micro_area) <> ''
                ORDER BY nu_micro_area ASC
                """,
                (unidade,),
            ).fetchall()
    return {
        "lista_unidades": [dict(r) for r in unidades],
        "lista_micro_areas": [r["nu_micro_area"] for r in micros],
    }


def listas_condicoes() -> dict:
    if not tem_snapshot():
        return {"lista_unidades": [], "lista_areas": []}
    base = listas_resumo()
    with _connect() as conn:
        areas = conn.execute(
            """
            SELECT DISTINCT no_bairro
            FROM snapshot_cidadao
            WHERE no_bairro IS NOT NULL AND TRIM(no_bairro) <> ''
            ORDER BY no_bairro ASC
            """
        ).fetchall()
    return {
        "lista_unidades": base["lista_unidades"],
        "lista_areas": [r["no_bairro"] for r in areas],
    }


def listar_obitos(
    nome: str | None,
    data_inicio: date | None,
    data_fim: date | None,
    unidade: str | None,
    page: int,
    limit: int = 15,
) -> dict:
    if not tem_snapshot():
        return {
            "obitos": [],
            "total_registros": 0,
            "total_pages": 1,
            "page": 1,
        }
    clauses = ["dt_obito IS NOT NULL", "TRIM(dt_obito) <> ''"]
    params: list = []
    if nome:
        clauses.append("no_cidadao LIKE ? COLLATE NOCASE")
        params.append(f"%{nome}%")
    if data_inicio:
        clauses.append("dt_obito >= ?")
        params.append(data_inicio.isoformat())
    if data_fim:
        clauses.append("dt_obito <= ?")
        params.append(data_fim.isoformat())
    if unidade:
        clauses.append("nu_cnes = ?")
        params.append(unidade)
    where = " AND ".join(clauses)
    total = _escalar(f"SELECT COUNT(*) FROM snapshot_cidadao WHERE {where}", params)
    total_pages = (total + limit - 1) // limit if total else 1
    if page > total_pages:
        page = total_pages
    offset = (page - 1) * limit
    with _connect() as conn:
        rows = conn.execute(
            f"""
            SELECT
                co_seq_cidadao,
                no_cidadao,
                nu_cpf,
                nu_cns,
                dt_nascimento,
                dt_obito,
                COALESCE(NULLIF(TRIM(no_unidade_saude), ''), 'Sem unidade') AS no_unidade_saude
            FROM snapshot_cidadao
            WHERE {where}
            ORDER BY dt_obito DESC, no_cidadao ASC
            LIMIT ? OFFSET ?
            """,
            [*params, limit, offset],
        ).fetchall()
    obitos = []
    for row in rows:
        item = dict(row)
        item["dt_nascimento"] = _como_data(item.get("dt_nascimento"))
        item["dt_obito"] = _como_data(item.get("dt_obito"))
        obitos.append(item)
    return {
        "obitos": obitos,
        "total_registros": total,
        "total_pages": total_pages,
        "page": page,
    }


def _agenda_loop() -> None:
    while True:
        time.sleep(20)
        try:
            _checar_agenda()
        except Exception:
            log.exception("falha ao verificar o horário da extração")


def _checar_agenda() -> None:
    agora = datetime.now()
    if agora.strftime("%H:%M") != horario():
        return
    hoje = agora.date().isoformat()
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT 1 FROM snapshot_execucao
            WHERE origem = 'agenda'
            AND substr(iniciado_em, 1, 10) = ?
            LIMIT 1
            """,
            (hoje,),
        ).fetchone()
    if row is not None:
        return
    iniciar("agenda")


def _executar(origem: str) -> None:
    global _rodando
    exec_id = _abrir_execucao(origem)
    try:
        quantidade = _extrair()
    except Exception as exc:
        log.exception("extração do e-SUS falhou")
        _fechar_execucao(exec_id, "erro", None, _mensagem_erro(exc))
    else:
        _fechar_execucao(exec_id, "ok", quantidade, None)
    finally:
        with _lock:
            _rodando = False


def _extrair() -> int:
    sql = _sql_postgres()
    _criar_tabela_nova()
    total = 0
    engine = get_engine()
    colunas_sql = ", ".join(COLUNAS)
    placeholders = ", ".join("?" for _ in COLUNAS)
    insert = f"INSERT INTO snapshot_cidadao_nova ({colunas_sql}) VALUES ({placeholders})"
    with engine.connect() as pg:
        result = pg.execution_options(stream_results=True).execute(text(sql))
        with _connect() as conn:
            while True:
                lote = result.fetchmany(500)
                if not lote:
                    break
                conn.executemany(insert, [_linha(row) for row in lote])
                conn.commit()
                total += len(lote)
    _trocar_tabela()
    return total


def _sql_postgres() -> str:
    flags = ", ".join(f"f.{nome}" for nome in FLAGS)
    return f"""
        SELECT DISTINCT ON (c.co_seq_cidadao)
            c.co_seq_cidadao,
            c.no_cidadao,
            c.no_sexo,
            c.dt_nascimento,
            c.nu_cpf,
            c.nu_cns,
            c.st_ativo,
            c.st_faleceu,
            dus.nu_cnes,
            COALESCE(us.no_unidade_saude, dus.no_unidade_saude) AS no_unidade_saude,
            f.nu_micro_area,
            COALESCE(us.no_bairro, dus.no_bairro) AS no_bairro,
            f.dt_obito,
            t.dt_registro,
            tsc.ds_tipo_saida_cadastro AS ds_tipo_saida,
            {flags}
        FROM tb_cidadao c
        INNER JOIN tb_fat_cidadao_pec fc
            ON fc.co_cidadao = c.co_seq_cidadao
        INNER JOIN tb_fat_cad_individual f
            ON f.co_fat_cidadao_pec = fc.co_seq_fat_cidadao_pec
        LEFT JOIN tb_dim_unidade_saude dus
            ON dus.co_seq_dim_unidade_saude = f.co_dim_unidade_saude
        LEFT JOIN tb_unidade_saude us
            ON us.nu_cnes = dus.nu_cnes
        LEFT JOIN tb_dim_tipo_saida_cadastro tsc
            ON tsc.co_seq_dim_tipo_saida_cadastro = f.co_dim_tipo_saida_cadastro
        LEFT JOIN tb_dim_tempo t
            ON t.co_seq_dim_tempo = f.co_dim_tempo
        WHERE c.st_unificado = 0
        AND f.st_ficha_inativa = 0
        AND f.co_seq_fat_cad_individual = (
            SELECT MAX(f2.co_seq_fat_cad_individual)
            FROM tb_fat_cad_individual f2
            WHERE f2.co_fat_cidadao_pec = f.co_fat_cidadao_pec
                AND f2.st_ficha_inativa = 0
        )
        ORDER BY c.co_seq_cidadao, f.co_seq_fat_cad_individual DESC
    """


def _ddl(nome: str) -> str:
    tipos = ["co_seq_cidadao INTEGER PRIMARY KEY"]
    for coluna in COLUNAS[1:]:
        tipos.append(f"{coluna} {'INTEGER' if coluna in FLAG_SET or coluna in ('st_ativo', 'st_faleceu') else 'TEXT'}")
    return f"CREATE TABLE {nome} ({', '.join(tipos)})"


def _criar_tabela_nova() -> None:
    with _connect() as conn:
        conn.execute("DROP TABLE IF EXISTS snapshot_cidadao_nova")
        conn.execute(_ddl("snapshot_cidadao_nova"))
        conn.commit()


def _trocar_tabela() -> None:
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if _tabela_existe(conn, "snapshot_cidadao"):
            conn.execute("DROP TABLE IF EXISTS snapshot_cidadao_antiga")
            conn.execute("ALTER TABLE snapshot_cidadao RENAME TO snapshot_cidadao_antiga")
        conn.execute("ALTER TABLE snapshot_cidadao_nova RENAME TO snapshot_cidadao")
        conn.execute("DROP TABLE IF EXISTS snapshot_cidadao_antiga")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_snap_cnes ON snapshot_cidadao (nu_cnes)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_snap_obito ON snapshot_cidadao (dt_obito)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_snap_bairro ON snapshot_cidadao (no_bairro)")
        conn.commit()


def _linha(row) -> tuple:
    mapping = row._mapping if hasattr(row, "_mapping") else row
    valores = []
    for coluna in COLUNAS:
        valores.append(_normalizar(coluna, mapping[coluna]))
    return tuple(valores)


def _normalizar(coluna: str, valor):
    if valor is None:
        return None
    if isinstance(valor, datetime):
        return valor.date().isoformat()
    if isinstance(valor, date):
        return valor.isoformat()
    if coluna in FLAG_SET or coluna in ("st_ativo", "st_faleceu", "co_seq_cidadao"):
        return int(valor)
    if coluna == "nu_micro_area":
        return str(valor).strip()
    if isinstance(valor, str):
        return valor
    return str(valor)


def _where(
    filtros: dict,
    predicados: list[str] | None = None,
    *,
    ativo_fixo: bool = False,
) -> tuple[str, list]:
    partes: list[str] = []
    params: list = []
    pesquisa = "ativo" if ativo_fixo else (filtros.get("pesquisa") or "ativo")
    if pesquisa == "ativo":
        partes.append("AND st_ativo = 1 AND (st_faleceu = 0 OR st_faleceu IS NULL)")
    elif pesquisa == "mudou_se":
        partes.append("AND LOWER(COALESCE(ds_tipo_saida, '')) LIKE '%mud%'")

    if filtros.get("unidade"):
        partes.append("AND nu_cnes = ?")
        params.append(filtros["unidade"])
    if filtros.get("micro_area"):
        partes.append("AND nu_micro_area = ?")
        params.append(str(filtros["micro_area"]))
    if filtros.get("idade_min") is not None:
        partes.append(f"AND {_IDADE} >= ?")
        params.append(int(filtros["idade_min"]))
    if filtros.get("idade_max") is not None:
        partes.append(f"AND {_IDADE} <= ?")
        params.append(int(filtros["idade_max"]))
    if filtros.get("data_nascimento"):
        nasc = filtros["data_nascimento"]
        partes.append("AND dt_nascimento = ?")
        params.append(nasc.isoformat() if isinstance(nasc, date) else str(nasc))
    if filtros.get("area"):
        partes.append("AND no_bairro = ?")
        params.append(filtros["area"])
    if filtros.get("data_inicio"):
        inicio = filtros["data_inicio"]
        partes.append("AND dt_registro >= ?")
        params.append(inicio.isoformat() if isinstance(inicio, date) else str(inicio))
    for predicado in predicados or []:
        partes.append(f"AND {_coluna_predicado(predicado)} = 1")
    return "\n".join(partes), params


def _coluna_predicado(predicado: str) -> str:
    match = _PRED_RE.match((predicado or "").strip())
    if not match or match.group(1) not in FLAG_SET:
        raise ValueError("Condição inválida na extração.")
    return match.group(1)


def _select_counts() -> str:
    partes = [
        "COUNT(*) AS total_base",
        "COUNT(*) AS total_cadastros_unicos",
        "SUM(CASE WHEN no_sexo = 'MASCULINO' THEN 1 ELSE 0 END) AS sexo_masculino",
        "SUM(CASE WHEN no_sexo = 'FEMININO' THEN 1 ELSE 0 END) AS sexo_feminino",
        f"SUM(CASE WHEN {_IDADE} < 18 THEN 1 ELSE 0 END) AS menores_18",
        f"SUM(CASE WHEN {_IDADE} >= 18 AND {_IDADE} <= 59 THEN 1 ELSE 0 END) AS adultos",
        f"SUM(CASE WHEN {_IDADE} >= 60 THEN 1 ELSE 0 END) AS idosos",
        f"SUM(CASE WHEN {_CPF_OK} THEN 1 ELSE 0 END) AS cadastros_com_cpf",
        f"SUM(CASE WHEN NOT {_CPF_OK} THEN 1 ELSE 0 END) AS cadastros_sem_cpf",
        f"SUM(CASE WHEN {_CNS_OK} THEN 1 ELSE 0 END) AS cadastros_com_cns",
        f"SUM(CASE WHEN NOT {_CPF_OK} OR NOT {_CNS_OK} THEN 1 ELSE 0 END) AS sem_cpf_e_cns",
    ]
    for alias, coluna in EQ1:
        partes.append(f"SUM(CASE WHEN {coluna} = 1 THEN 1 ELSE 0 END) AS {alias}")
    for alias, coluna in ISNULL:
        partes.append(f"SUM(CASE WHEN {coluna} IS NULL THEN 1 ELSE 0 END) AS {alias}")
    return ", ".join(partes)


def _contar(where: str, params: list) -> dict:
    with _connect() as conn:
        row = conn.execute(
            f"SELECT {_select_counts()} FROM snapshot_cidadao WHERE 1 = 1 {where}",
            params,
        ).fetchone()
    return dict(row) if row else {}


def _por_unidade(where: str, params: list) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            f"""
            SELECT
                COALESCE(NULLIF(TRIM(no_unidade_saude), ''), 'Sem unidade') AS no_unidade_saude,
                nu_cnes,
                COUNT(*) AS total_cadastros
            FROM snapshot_cidadao
            WHERE 1 = 1
            {where}
            GROUP BY 1, 2
            ORDER BY total_cadastros DESC
            """,
            params,
        ).fetchall()
    return [
        {
            "no_unidade_saude": r["no_unidade_saude"],
            "nu_cnes": r["nu_cnes"],
            "total_cadastros": int(r["total_cadastros"] or 0),
        }
        for r in rows
    ]


def _escalar(sql: str, params: list) -> int:
    with _connect() as conn:
        row = conn.execute(sql, params).fetchone()
    if row is None or row[0] is None:
        return 0
    return int(row[0])


def _resumo_vazio(unidade) -> dict:
    return {
        "resumo_cidadao": {k: 0 for k in DEMO_KEYS},
        "condicoes": {k: 0 for k in COND_KEYS},
        "cadastros_por_unidade": [],
        "total_geral_unidades": 0,
        "unidade_ativa": unidade,
        "nome_unidade": None,
        "obitos_30_dias": 0,
    }


def _ultima_ok() -> dict | None:
    init_snapshot()
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT finalizado_em
            FROM snapshot_execucao
            WHERE status = 'ok'
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
    return dict(row) if row else None


def _abrir_execucao(origem: str) -> int:
    init_snapshot()
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO snapshot_execucao (iniciado_em, status, origem)
            VALUES (?, 'executando', ?)
            """,
            (_agora(), origem),
        )
        conn.commit()
        return int(cur.lastrowid)


def _fechar_execucao(exec_id: int, status: str, quantidade: int | None, mensagem: str | None) -> None:
    with _connect() as conn:
        conn.execute(
            """
            UPDATE snapshot_execucao
            SET status = ?, finalizado_em = ?, quantidade = ?, mensagem = ?
            WHERE id = ?
            """,
            (status, _agora(), quantidade, mensagem, exec_id),
        )
        conn.commit()
        if status == "erro":
            conn.execute("DROP TABLE IF EXISTS snapshot_cidadao_nova")
            conn.commit()


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _formatar(valor: str | None) -> str | None:
    if not valor:
        return None
    try:
        momento = datetime.fromisoformat(valor)
    except ValueError:
        return valor
    return momento.strftime("%d/%m/%Y %H:%M")


def _como_data(valor: str | None) -> date | None:
    if not valor:
        return None
    try:
        return date.fromisoformat(str(valor)[:10])
    except ValueError:
        return None


def _mensagem_erro(exc: BaseException) -> str:
    origem = getattr(exc, "orig", None)
    texto = str(origem or exc).strip() or exc.__class__.__name__
    linha = texto.splitlines()[0].strip()
    return linha[:300]
