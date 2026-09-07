import os
from datetime import timedelta

from sqlalchemy.engine import make_url


def _obter_booleano_ambiente(nome, padrao=False):
    valor = os.environ.get(nome)

    if valor is None or not valor.strip():
        return padrao

    valor_normalizado = valor.strip().lower()

    if valor_normalizado in {"1", "true", "yes", "on"}:
        return True

    if valor_normalizado in {"0", "false", "no", "off"}:
        return False

    raise RuntimeError(
        f"{nome} deve ser true/false, 1/0, yes/no ou on/off."
    )


APP_HOST = os.environ.get("APP_HOST", "127.0.0.1").strip()

if not APP_HOST:
    raise RuntimeError("APP_HOST não pode ser vazio.")

_app_port_ambiente = os.environ.get("APP_PORT", "5000").strip()

try:
    APP_PORT = int(_app_port_ambiente)
except ValueError as erro:
    raise RuntimeError("APP_PORT deve ser um número inteiro.") from erro

if not 1 <= APP_PORT <= 65535:
    raise RuntimeError("APP_PORT deve estar entre 1 e 65535.")

FLASK_DEBUG = _obter_booleano_ambiente("FLASK_DEBUG", False)

_trusted_proxy_hops_ambiente = os.environ.get(
    "TRUSTED_PROXY_HOPS",
    "0"
).strip()

try:
    TRUSTED_PROXY_HOPS = int(_trusted_proxy_hops_ambiente)
except ValueError as erro:
    raise RuntimeError(
        "TRUSTED_PROXY_HOPS deve ser um número inteiro."
    ) from erro

if TRUSTED_PROXY_HOPS < 0:
    raise RuntimeError("TRUSTED_PROXY_HOPS não pode ser negativo.")


JWT_SECRET_KEY = os.environ.get(
    "JWT_SECRET_KEY",
    ""
).strip()

if not JWT_SECRET_KEY:
    raise RuntimeError(
        "JWT_SECRET_KEY não configurada."
    )

if len(JWT_SECRET_KEY) < 32:
    raise RuntimeError(
        "JWT_SECRET_KEY deve possuir pelo menos 32 caracteres."
    )

JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=8)

CORS_ORIGINS_LOCAIS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5174"
]

_cors_origins_ambiente = os.environ.get("CORS_ORIGINS")

if _cors_origins_ambiente is None:
    CORS_ORIGINS = CORS_ORIGINS_LOCAIS
else:
    CORS_ORIGINS = list(dict.fromkeys(
        origem.strip()
        for origem in _cors_origins_ambiente.split(",")
        if origem.strip()
    ))

    if not CORS_ORIGINS:
        raise RuntimeError("CORS_ORIGINS não contém origem válida.")

    if "*" in CORS_ORIGINS:
        raise RuntimeError("CORS_ORIGINS não permite wildcard.")

CORS_RESOURCES = {
    r"/api/*": {
        "origins": CORS_ORIGINS
    }
}
CORS_ALLOW_HEADERS = [
    "Content-Type",
    "Authorization"
]
CORS_METHODS = [
    "GET",
    "POST",
    "PUT",
    "PATCH",
    "DELETE",
    "OPTIONS"
]

ADMIN_BOOTSTRAP_NOME = os.environ.get(
    "ADMIN_BOOTSTRAP_NOME",
    ""
).strip()
ADMIN_BOOTSTRAP_USUARIO = os.environ.get(
    "ADMIN_BOOTSTRAP_USUARIO",
    ""
).strip()
ADMIN_BOOTSTRAP_EMAIL = os.environ.get(
    "ADMIN_BOOTSTRAP_EMAIL",
    ""
).strip()
ADMIN_BOOTSTRAP_SENHA = os.environ.get(
    "ADMIN_BOOTSTRAP_SENHA",
    ""
).strip()

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH_LOCAL = os.path.join(BASE_DIR, "database.db")
_database_url_ambiente = os.environ.get("DATABASE_URL", "").strip()

if _database_url_ambiente:
    try:
        _database_url_analisada = make_url(_database_url_ambiente)
    except Exception as erro:
        raise RuntimeError("DATABASE_URL inválida.") from erro

    SQLALCHEMY_DATABASE_URI = _database_url_ambiente
else:
    _database_url_analisada = make_url("sqlite:///" + DB_PATH_LOCAL)
    SQLALCHEMY_DATABASE_URI = "sqlite:///" + DB_PATH_LOCAL

if (
    _database_url_analisada.get_backend_name() == "sqlite"
    and _database_url_analisada.database
    and _database_url_analisada.database != ":memory:"
):
    DB_PATH = os.path.abspath(_database_url_analisada.database)
    USAR_COMPATIBILIDADE_SCHEMA_SQLITE = True
else:
    DB_PATH = DB_PATH_LOCAL
    USAR_COMPATIBILIDADE_SCHEMA_SQLITE = False

_upload_folder_ambiente = os.environ.get("UPLOAD_FOLDER", "").strip()

if _upload_folder_ambiente:
    UPLOAD_FOLDER = os.path.abspath(
        os.path.expanduser(_upload_folder_ambiente)
    )
else:
    UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "pdf"}
UPLOAD_MAX_FILE_SIZE = 10 * 1024 * 1024
MAX_CONTENT_LENGTH = UPLOAD_MAX_FILE_SIZE + (1024 * 1024)

SQLALCHEMY_TRACK_MODIFICATIONS = False
