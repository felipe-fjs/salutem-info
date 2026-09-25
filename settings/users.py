import hashlib
import secrets
import sqlite3
from pathlib import Path

DB_PATH = Path("data") / "app.db"

PERMISSIONS = ("inicio", "condicoes", "obitos", "configuracoes", "usuarios")
PERMISSION_LABELS = {
    "inicio": "Início",
    "condicoes": "Condições",
    "obitos": "Óbitos",
    "configuracoes": "Configurações",
    "usuarios": "Usuários",
}

TIPO_ADMINISTRADOR = "administrador"
TIPO_USUARIO = "usuario"
TIPOS = (TIPO_ADMINISTRADOR, TIPO_USUARIO)
TIPO_LABELS = {
    TIPO_ADMINISTRADOR: "Administrador",
    TIPO_USUARIO: "Usuário",
}

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin123"
ADMIN_NOME = "Administrador"


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    if salt is None:
        salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 200_000)
    return salt, digest.hex()


def verify_password(password: str, salt: str, password_hash: str) -> bool:
    _, digest = hash_password(password, salt)
    return secrets.compare_digest(digest, password_hash)


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                ativo INTEGER NOT NULL DEFAULT 1,
                nome TEXT,
                tipo TEXT
            )
            """
        )
        _ensure_user_columns(conn)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_permissions (
                user_id INTEGER NOT NULL,
                permission TEXT NOT NULL,
                PRIMARY KEY (user_id, permission),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """
        )
        count = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
        if count == 0:
            salt, password_hash = hash_password(ADMIN_PASSWORD)
            cur = conn.execute(
                "INSERT INTO users (username, password_hash, salt, ativo, nome, tipo) VALUES (?, ?, ?, 1, ?, ?)",
                (ADMIN_USERNAME, password_hash, salt, ADMIN_NOME, TIPO_ADMINISTRADOR),
            )
            for perm in PERMISSIONS:
                conn.execute(
                    "INSERT INTO user_permissions (user_id, permission) VALUES (?, ?)",
                    (cur.lastrowid, perm),
                )
        _backfill_nome_tipo(conn)
        conn.commit()


def _ensure_user_columns(conn: sqlite3.Connection) -> None:
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
    if "nome" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN nome TEXT")
    if "tipo" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN tipo TEXT")


def _backfill_nome_tipo(conn: sqlite3.Connection) -> None:
    admin = conn.execute(
        "SELECT id, nome, tipo FROM users WHERE username = ?",
        (ADMIN_USERNAME,),
    ).fetchone()
    if admin is not None:
        if not (admin["nome"] or "").strip():
            conn.execute(
                "UPDATE users SET nome = ? WHERE id = ?",
                (ADMIN_NOME, admin["id"]),
            )
        if admin["tipo"] not in TIPOS:
            conn.execute(
                "UPDATE users SET tipo = ? WHERE id = ?",
                (TIPO_ADMINISTRADOR, admin["id"]),
            )
    conn.execute(
        "UPDATE users SET nome = username WHERE nome IS NULL OR TRIM(nome) = ''"
    )
    conn.execute(
        "UPDATE users SET tipo = ? WHERE tipo IS NULL OR tipo NOT IN (?, ?)",
        (TIPO_USUARIO, TIPO_ADMINISTRADOR, TIPO_USUARIO),
    )


def tipo_do_usuario(username: str) -> str | None:
    if not username:
        return None
    init_db()
    with _connect() as conn:
        row = conn.execute(
            "SELECT username, tipo FROM users WHERE username = ?",
            (username,),
        ).fetchone()
    if row is None:
        return None
    return _tipo_de(row["tipo"], row["username"])


def _tipo_de(tipo: str | None, username: str) -> str:
    if tipo in TIPOS:
        return tipo
    if username == ADMIN_USERNAME:
        return TIPO_ADMINISTRADOR
    return TIPO_USUARIO


def _permissoes(conn: sqlite3.Connection, user_id: int, username: str, tipo: str | None = None) -> list[str]:
    if tipo is None:
        row = conn.execute("SELECT tipo FROM users WHERE id = ?", (user_id,)).fetchone()
        tipo = row["tipo"] if row else None
    if username == ADMIN_USERNAME or tipo == TIPO_ADMINISTRADOR:
        return list(PERMISSIONS)
    rows = conn.execute(
        "SELECT permission FROM user_permissions WHERE user_id = ? ORDER BY permission",
        (user_id,),
    ).fetchall()
    return [r["permission"] for r in rows if r["permission"] in PERMISSIONS]


def authenticate(username: str, password: str) -> dict | None:
    init_db()
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, username, password_hash, salt, ativo, nome, tipo FROM users WHERE username = ?",
            (username.strip(),),
        ).fetchone()
        if row is None or not row["ativo"]:
            return None
        if not verify_password(password, row["salt"], row["password_hash"]):
            return None
        tipo = _tipo_de(row["tipo"], row["username"])
        return {
            "id": row["id"],
            "username": row["username"],
            "nome": row["nome"] or row["username"],
            "tipo": tipo,
            "permissoes": _permissoes(conn, row["id"], row["username"], tipo),
        }


def list_users() -> list[dict]:
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, username, ativo, nome, tipo FROM users ORDER BY nome, username"
        ).fetchall()
        users = []
        for row in rows:
            tipo = _tipo_de(row["tipo"], row["username"])
            users.append(
                {
                    "id": row["id"],
                    "username": row["username"],
                    "nome": row["nome"] or row["username"],
                    "tipo": tipo,
                    "tipo_label": TIPO_LABELS[tipo],
                    "ativo": bool(row["ativo"]),
                    "permissoes": _permissoes(conn, row["id"], row["username"], tipo),
                    "is_admin": row["username"] == ADMIN_USERNAME,
                }
            )
        return users


def _permissoes_validas(tipo: str, permissoes: list[str]) -> list[str]:
    if tipo == TIPO_ADMINISTRADOR:
        return list(PERMISSIONS)
    return [p for p in permissoes if p in PERMISSIONS]


def _gravar_permissoes(conn: sqlite3.Connection, user_id: int, permissoes: list[str]) -> None:
    conn.execute("DELETE FROM user_permissions WHERE user_id = ?", (user_id,))
    for perm in permissoes:
        conn.execute(
            "INSERT INTO user_permissions (user_id, permission) VALUES (?, ?)",
            (user_id, perm),
        )


def create_user(username: str, password: str, permissoes: list[str], nome: str, tipo: str) -> str | None:
    init_db()
    username = username.strip()
    nome = nome.strip()
    if not nome:
        return "Informe o nome."
    if not username or not password:
        return "Informe usuário e senha."
    if username == ADMIN_USERNAME:
        return "O usuário admin já existe."
    if tipo not in TIPOS:
        return "Tipo de usuário inválido."
    valid = _permissoes_validas(tipo, permissoes)
    salt, password_hash = hash_password(password)
    try:
        with _connect() as conn:
            cur = conn.execute(
                "INSERT INTO users (username, password_hash, salt, ativo, nome, tipo) VALUES (?, ?, ?, 1, ?, ?)",
                (username, password_hash, salt, nome, tipo),
            )
            _gravar_permissoes(conn, cur.lastrowid, valid)
            conn.commit()
    except sqlite3.IntegrityError:
        return "Já existe um usuário com esse nome."
    return None


def update_user(
    user_id: int,
    permissoes: list[str],
    password: str = "",
    nome: str = "",
    username: str = "",
    tipo: str = "",
) -> str | None:
    init_db()
    nome = nome.strip()
    username = username.strip()
    if not nome:
        return "Informe o nome."
    if not username:
        return "Informe o usuário."
    if tipo not in TIPOS:
        return "Tipo de usuário inválido."
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, username, tipo FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if row is None:
            return "Usuário não encontrado."
        is_seed_admin = row["username"] == ADMIN_USERNAME
        if is_seed_admin:
            username = ADMIN_USERNAME
            tipo = TIPO_ADMINISTRADOR
        elif username == ADMIN_USERNAME:
            return "O usuário admin já existe."
        taken = conn.execute(
            "SELECT id FROM users WHERE username = ? AND id != ?",
            (username, user_id),
        ).fetchone()
        if taken is not None:
            return "Já existe um usuário com esse nome."
        if row["tipo"] == TIPO_ADMINISTRADOR and tipo != TIPO_ADMINISTRADOR:
            admins = conn.execute(
                "SELECT COUNT(*) AS n FROM users WHERE tipo = ?",
                (TIPO_ADMINISTRADOR,),
            ).fetchone()["n"]
            if admins <= 1:
                return "É preciso manter pelo menos um administrador."
        if password.strip():
            salt, password_hash = hash_password(password)
            conn.execute(
                "UPDATE users SET password_hash = ?, salt = ? WHERE id = ?",
                (password_hash, salt, user_id),
            )
        conn.execute(
            "UPDATE users SET nome = ?, username = ?, tipo = ? WHERE id = ?",
            (nome, username, tipo, user_id),
        )
        _gravar_permissoes(conn, user_id, _permissoes_validas(tipo, permissoes))
        conn.commit()
    return None


def delete_user(user_id: int) -> str | None:
    init_db()
    with _connect() as conn:
        row = conn.execute(
            "SELECT username, tipo FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if row is None:
            return "Usuário não encontrado."
        if row["username"] == ADMIN_USERNAME:
            return "O usuário admin não pode ser excluído."
        if row["tipo"] == TIPO_ADMINISTRADOR:
            admins = conn.execute(
                "SELECT COUNT(*) AS n FROM users WHERE tipo = ?",
                (TIPO_ADMINISTRADOR,),
            ).fetchone()["n"]
            if admins <= 1:
                return "É preciso manter pelo menos um administrador."
        conn.execute("DELETE FROM user_permissions WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
    return None
