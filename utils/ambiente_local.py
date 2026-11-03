import os
from pathlib import Path


def carregar_dotenv_local(caminho=None):
    """Carrega .env apenas para desenvolvimento local, sem sobrescrever env.

    O arquivo não é lido quando Railway está identificado ou APP_ENV indica
    qualquer ambiente diferente de development (incluindo test/staging/prod).
    """
    if os.environ.get("RAILWAY_ENVIRONMENT_NAME", "").strip():
        return False

    app_env_externo = os.environ.get("APP_ENV", "").strip().lower()
    if app_env_externo not in {"", "development"}:
        return False

    from dotenv import load_dotenv

    arquivo_env = (
        Path(caminho)
        if caminho is not None
        else Path(__file__).resolve().parents[1] / ".env"
    )
    return load_dotenv(dotenv_path=arquivo_env, override=False)
