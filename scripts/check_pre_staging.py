import os
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT.parent / "React_Transportadora"


def check(condition, message):
    if not condition:
        raise SystemExit(f"FAIL: {message}")
    print(f"OK: {message}")


def main():
    check((ROOT / "wsgi.py").is_file(), "wsgi.py existe")
    check((ROOT / "requirements.txt").is_file(), "requirements.txt existe")
    check((FRONTEND / "vercel.json").is_file(), "vercel.json existe")

    with tempfile.TemporaryDirectory(prefix="pre-staging-check-") as temp_dir:
        temp_path = Path(temp_dir)
        required = {
            "DATABASE_URL": f"sqlite:///{temp_path / 'database.db'}",
            "JWT_SECRET_KEY": "pre-staging-check-secret-0123456789",
            "FLASK_DEBUG": "false",
            "TRUSTED_PROXY_HOPS": "0",
            "UPLOAD_FOLDER": str(temp_path / "uploads"),
            "CORS_ORIGINS": "https://staging.example.invalid",
        }
        environment = os.environ.copy()
        environment.update(required)
        environment.setdefault("ADMIN_BOOTSTRAP_NOME", "Gate")
        environment.setdefault("ADMIN_BOOTSTRAP_USUARIO", "gate")
        environment.setdefault("ADMIN_BOOTSTRAP_EMAIL", "gate@example.invalid")
        environment.setdefault("ADMIN_BOOTSTRAP_SENHA", "gate-password")

        result = subprocess.run(
            [sys.executable, "-c", "import app; import wsgi"],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
        )
        check(result.returncode == 0, "import app e wsgi")

    pip_check = subprocess.run(
        [sys.executable, "-m", "pip", "check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    check(pip_check.returncode == 0, "pip check")
    print(pip_check.stdout.strip())

    waiter_check = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import waitress; "
                "print(getattr(waitress, '__version__', 'WAITRESS_OK'))"
            ),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    check(waiter_check.returncode == 0, "Waitress importavel")
    print(waiter_check.stdout.strip())

    frontend_api = FRONTEND / "src" / "services" / "api.ts"
    api_text = frontend_api.read_text(encoding="utf-8")
    check("VITE_API_URL" in api_text, "frontend exige VITE_API_URL em producao")
    check("http://127.0.0.1:5000" in api_text, "fallback localhost restrito ao modo DEV")
    frontend_sources = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in (FRONTEND / "src").rglob("*")
        if path.is_file()
    )
    check("/static/uploads" not in frontend_sources, "frontend nao referencia uploads publicos")

    config_text = (ROOT / "config.py").read_text(encoding="utf-8")
    check('FLASK_DEBUG = _obter_booleano_ambiente("FLASK_DEBUG", False)' in config_text, "debug comercial default false")
    check('TRUSTED_PROXY_HOPS' in config_text, "proxy opt-in por hops explicitos")
    print("PRE_STAGING_CONFIG_OK")


if __name__ == "__main__":
    main()
