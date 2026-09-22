import io
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch


BACKEND_DIR = Path(__file__).resolve().parents[1]


class PreStagingGateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = Path(tempfile.mkdtemp(prefix="transportadora-gate-"))
        cls.db_path = cls.temp_dir / "database.db"
        cls.upload_dir = cls.temp_dir / "uploads"
        os.environ.update({
            "DATABASE_URL": f"sqlite:///{cls.db_path}",
            "JWT_SECRET_KEY": "pre-staging-gate-secret-0123456789012345",
            "ADMIN_BOOTSTRAP_NOME": "Admin Gate",
            "ADMIN_BOOTSTRAP_USUARIO": "admin-gate",
            "ADMIN_BOOTSTRAP_EMAIL": "admin-gate@example.invalid",
            "ADMIN_BOOTSTRAP_SENHA": "senha-admin-gate",
            "UPLOAD_FOLDER": str(cls.upload_dir),
            "TRUSTED_PROXY_HOPS": "0",
            "FLASK_DEBUG": "false",
            "CORS_ORIGINS": "https://staging.example.invalid",
        })

        sys.path.insert(0, str(BACKEND_DIR))
        from app import app
        from extensions import db
        from flask_jwt_extended import create_access_token
        from models.auditoria import LogAcao
        from models.clientes import Cliente, ClienteUsuario
        from models.comprovantes import ArquivoComprovanteViagem
        from models.historicos import HistoricoRastreamento
        from models.operacao import Rastreamento, Viagem
        from models.recursos import Motorista, Veiculo
        from models.usuarios import UsuarioSistema
        from services.rate_limit import limiter

        cls.app = app
        cls.db = db
        cls.create_access_token = create_access_token
        cls.LogAcao = LogAcao
        cls.Cliente = Cliente
        cls.ClienteUsuario = ClienteUsuario
        cls.ArquivoComprovanteViagem = ArquivoComprovanteViagem
        cls.HistoricoRastreamento = HistoricoRastreamento
        cls.Rastreamento = Rastreamento
        cls.Viagem = Viagem
        cls.Motorista = Motorista
        cls.Veiculo = Veiculo
        cls.UsuarioSistema = UsuarioSistema
        cls.limiter = limiter
        cls.client = app.test_client()

        with app.app_context():
            cls.admin = UsuarioSistema.query.filter_by(
                usuario="admin-gate"
            ).first()
            cls.admin_id = cls.admin.id
            cls.admin_token = create_access_token(
                identity=str(cls.admin.id)
            )

    @classmethod
    def tearDownClass(cls):
        with cls.app.app_context():
            cls.db.session.remove()
            cls.db.engine.dispose()
        shutil.rmtree(cls.temp_dir, ignore_errors=True)
        if str(BACKEND_DIR) in sys.path:
            sys.path.remove(str(BACKEND_DIR))

    def setUp(self):
        self.limiter.limpar()

    def auth(self, token=None):
        token = token or self.admin_token
        return {"Authorization": f"Bearer {token}"}

    def assert_status(self, response, status):
        self.assertEqual(
            response.status_code,
            status,
            response.get_json(silent=True),
        )

    def test_bootstrap_and_repeated_initialization_are_safe(self):
        self.assertEqual(self.admin.perfil, "administrador")
        self.assertTrue(self.admin.ativo)
        self.assertNotEqual(self.admin.senha, "senha-admin-gate")
        with self.app.app_context():
            self.assertEqual(
                self.UsuarioSistema.query.filter_by(
                    usuario="admin-gate"
                ).count(),
                1,
            )

        self.assert_status(
            self.client.post(
                "/api/login",
                json={"usuario": "admin-gate", "senha": "senha-admin-gate"},
            ),
            200,
        )

    def test_bootstrap_validation_rejects_unsafe_configuration(self):
        script = (
            "import os; os.environ['JWT_SECRET_KEY']='short'; "
            "import config"
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=BACKEND_DIR,
            capture_output=True,
            text=True,
            env={k: v for k, v in os.environ.items() if k != "JWT_SECRET_KEY"},
        )
        self.assertNotEqual(result.returncode, 0)

    def test_admin_journey_and_audit(self):
        client_data = {
            "razao_social": "Cliente Gate",
            "nome_fantasia": "Gate",
            "documento": "123",
            "responsavel": "Resp",
            "email": "cliente-gate@example.invalid",
            "telefone": "1",
            "cidade": "Sao Paulo",
            "estado": "SP",
        }
        self.assert_status(
            self.client.post(
                "/api/admin/clientes",
                json=client_data,
                headers=self.auth(),
            ),
            201,
        )
        with self.app.app_context():
            client = self.Cliente.query.filter_by(
                razao_social="Cliente Gate"
            ).first()
            client_id = client.id

        driver_data = {
            "nome": "Motorista Gate",
            "usuario": "motorista-gate",
            "email": "motorista-gate@example.invalid",
            "senha": "senha-motorista",
            "cpf": "1",
            "cnh": "2",
            "categoria_cnh": "B",
            "validade_cnh": "2030",
        }
        self.assert_status(
            self.client.post(
                "/api/admin/motoristas",
                json=driver_data,
                headers=self.auth(),
            ),
            201,
        )
        self.assert_status(
            self.client.post(
                "/api/admin/veiculos",
                json={"placa": "GATE-001", "modelo": "M", "status": "Disponível"},
                headers=self.auth(),
            ),
            201,
        )
        with self.app.app_context():
            driver = self.Motorista.query.filter_by(
                usuario="motorista-gate"
            ).first()
            vehicle = self.Veiculo.query.filter_by(placa="GATE-001").first()
            driver_id = driver.id
            vehicle_id = vehicle.id

        response = self.client.post(
            "/api/admin/cargas",
            json={
                "cliente_id": client_id,
                "status": "Pendente",
                "local_atual": "A",
                "destino": "B",
                "valor_frete": "10",
                "status_pagamento": "Pendente",
            },
            headers=self.auth(),
        )
        self.assert_status(response, 201)
        carga_id = response.get_json()["id"]
        self.assert_status(
            self.client.put(
                f"/api/admin/cargas/{carga_id}/atribuir-motorista",
                json={"motorista_id": driver_id},
                headers=self.auth(),
            ),
            200,
        )
        self.assert_status(
            self.client.put(
                f"/api/admin/cargas/{carga_id}/atribuir-veiculo",
                json={"veiculo_id": vehicle_id},
                headers=self.auth(),
            ),
            200,
        )
        self.assert_status(
            self.client.post(
                f"/api/admin/cargas/{carga_id}/criar-viagem",
                headers=self.auth(),
            ),
            201,
        )
        with self.app.app_context():
            viagem = self.Viagem.query.filter_by(
                rastreamento_id=carga_id
            ).first()
            viagem_id = viagem.id
            viagem.status = "Saiu para entrega"
            self.db.session.commit()

        self.assert_status(
            self.client.post(
                f"/api/admin/viagens/{viagem_id}/ocorrencias",
                json={"descricao": "Ocorrencia gate"},
                headers=self.auth(),
            ),
            200,
        )
        upload = {"arquivo": (io.BytesIO(b"%PDF-1.7 gate"), "gate.pdf", "application/pdf")}
        self.assert_status(
            self.client.post(
                f"/api/admin/viagens/{viagem_id}/comprovante/arquivo",
                data=upload,
                content_type="multipart/form-data",
                headers=self.auth(),
            ),
            201,
        )
        self.assert_status(
            self.client.post(
                f"/api/admin/viagens/{viagem_id}/finalizar",
                json={"recebedor": "Recebedor Gate"},
                headers=self.auth(),
            ),
            201,
        )
        with self.app.app_context():
            carga = self.db.session.get(self.Rastreamento, carga_id)
            viagem = self.db.session.get(self.Viagem, viagem_id)
            self.assertEqual(carga.status, "Entregue")
            self.assertEqual(viagem.status, "Entregue")
            actions = [log.acao for log in self.LogAcao.query.all()]
            self.assertTrue(any("Finalização" in action for action in actions))
            serialized = " ".join(
                (log.antes or "") + (log.depois or "")
                for log in self.LogAcao.query.all()
            )
            self.assertNotIn("senha-motorista", serialized)
            self.assertNotIn("JWT", serialized.upper())
            self.assertNotIn("hash", serialized.lower())

    def test_dynamic_idor_and_inactive_user(self):
        with self.app.app_context():
            client_a = self.Cliente(razao_social="A", ativo=True)
            client_b = self.Cliente(razao_social="B", ativo=True)
            user_a = self.UsuarioSistema(
                nome="A", usuario="user-a", email="a@example.invalid",
                senha="hash-a", perfil="cliente", ativo=True,
            )
            user_b = self.UsuarioSistema(
                nome="B", usuario="user-b", email="b@example.invalid",
                senha="hash-b", perfil="cliente", ativo=True,
            )
            self.db.session.add_all([client_a, client_b, user_a, user_b])
            self.db.session.flush()
            self.db.session.add_all([
                self.ClienteUsuario(
                    cliente_id=client_a.id, usuario_sistema_id=user_a.id,
                    nome="A", empresa="A", email="a@example.invalid",
                    senha="hash-a", ativo=True,
                ),
                self.ClienteUsuario(
                    cliente_id=client_b.id, usuario_sistema_id=user_b.id,
                    nome="B", empresa="B", email="b@example.invalid",
                    senha="hash-b", ativo=True,
                ),
            ])
            carga_a = self.Rastreamento(
                codigo="IDOR-A", cliente="A", cliente_id=client_a.id,
                status="Pendente", local_atual="A", destino="B",
            )
            carga_b = self.Rastreamento(
                codigo="IDOR-B", cliente="B", cliente_id=client_b.id,
                status="Pendente", local_atual="A", destino="B",
            )
            self.db.session.add_all([carga_a, carga_b])
            self.db.session.commit()
            token_a = type(self).create_access_token(identity=str(user_a.id))
            token_b = type(self).create_access_token(identity=str(user_b.id))
            user_a_id = user_a.id
            carga_a_id = carga_a.id
            carga_b_id = carga_b.id

        own = self.client.get(
            f"/api/cliente/minhas-cargas/{carga_a_id}",
            headers=self.auth(token_a),
        )
        other = self.client.get(
            f"/api/cliente/minhas-cargas/{carga_b_id}",
            headers=self.auth(token_a),
        )
        self.assertIn(own.status_code, (200, 404))
        self.assertIn(other.status_code, (403, 404))
        self.assertNotEqual(other.status_code, 200)
        self.assert_status(
            self.client.post(
                "/api/admin/clientes",
                json={"razao_social": "blocked"},
                headers=self.auth(token_a),
            ),
            403,
        )
        with self.app.app_context():
            user = self.db.session.get(self.UsuarioSistema, user_a_id)
            user.ativo = False
            self.db.session.commit()
        response = self.client.get(
            f"/api/cliente/minhas-cargas/{carga_a_id}",
            headers=self.auth(token_a),
        )
        self.assertIn(response.status_code, (401, 403))

    def test_exclusao_canonica_de_cargas(self):
        observacao_criacao = "Carga cadastrada no sistema."

        def criar_carga_via_api(status):
            response = self.client.post(
                "/api/admin/cargas",
                json={
                    "cliente": "Cliente Exclusao Canonica",
                    "status": status,
                    "local_atual": "Origem",
                    "destino": "Destino",
                    "valor_frete": "10",
                    "status_pagamento": "Pendente",
                },
                headers=self.auth(),
            )
            self.assert_status(response, 201)
            return response.get_json()["id"]

        def criar_carga_direta(codigo, status):
            with self.app.app_context():
                carga = self.Rastreamento(
                    codigo=codigo,
                    cliente="Cliente Exclusao Canonica",
                    status=status,
                    local_atual="Origem",
                    destino="Destino",
                )
                self.db.session.add(carga)
                self.db.session.flush()
                self.db.session.add(self.HistoricoRastreamento(
                    rastreamento_id=carga.id,
                    status=status,
                    local=carga.local_atual,
                    observacao=observacao_criacao,
                ))
                self.db.session.commit()
                return carga.id

        def confirmar_evento_inicial(carga_id):
            with self.app.app_context():
                eventos = self.HistoricoRastreamento.query.filter_by(
                    rastreamento_id=carga_id
                ).all()
                self.assertEqual(len(eventos), 1)
                self.assertEqual(eventos[0].observacao, observacao_criacao)

        def excluir_e_confirmar_sem_orfaos(carga_id):
            self.assert_status(
                self.client.delete(
                    f"/api/admin/cargas/{carga_id}",
                    headers=self.auth(),
                ),
                200,
            )
            with self.app.app_context():
                self.assertIsNone(
                    self.db.session.get(self.Rastreamento, carga_id)
                )
                self.assertEqual(
                    self.HistoricoRastreamento.query.filter_by(
                        rastreamento_id=carga_id
                    ).count(),
                    0,
                )

        pendente_id = criar_carga_via_api("Pendente")
        confirmar_evento_inicial(pendente_id)
        excluir_e_confirmar_sem_orfaos(pendente_id)

        programada_id = criar_carga_via_api("Programada")
        confirmar_evento_inicial(programada_id)
        excluir_e_confirmar_sem_orfaos(programada_id)

        preparacao_id = criar_carga_direta(
            "EXCLUSAO-PREPARACAO",
            "Em preparação",
        )
        confirmar_evento_inicial(preparacao_id)
        excluir_e_confirmar_sem_orfaos(preparacao_id)

        com_viagem_id = criar_carga_direta(
            "EXCLUSAO-COM-VIAGEM",
            "Pendente",
        )
        with self.app.app_context():
            self.db.session.add(self.Viagem(
                rastreamento_id=com_viagem_id,
                origem="Origem",
                destino="Destino",
                status="Planejada",
            ))
            self.db.session.commit()
        self.assert_status(
            self.client.delete(
                f"/api/admin/cargas/{com_viagem_id}",
                headers=self.auth(),
            ),
            409,
        )

        com_historico_id = criar_carga_direta(
            "EXCLUSAO-COM-HISTORICO",
            "Pendente",
        )
        with self.app.app_context():
            self.db.session.add(self.HistoricoRastreamento(
                rastreamento_id=com_historico_id,
                status="Pendente",
                local="Outro local",
                observacao="Movimentação operacional.",
            ))
            self.db.session.commit()
        self.assert_status(
            self.client.delete(
                f"/api/admin/cargas/{com_historico_id}",
                headers=self.auth(),
            ),
            409,
        )

        for codigo, status in (
            ("EXCLUSAO-EM-TRANSITO", "Em trânsito"),
            ("EXCLUSAO-ENTREGUE", "Entregue"),
        ):
            carga_id = criar_carga_direta(codigo, status)
            self.assert_status(
                self.client.delete(
                    f"/api/admin/cargas/{carga_id}",
                    headers=self.auth(),
                ),
                409,
            )

    def test_jwt_errors_and_rate_limits(self):
        self.assert_status(self.client.get("/api/admin/clientes", headers={}), 401)
        self.assert_status(
            self.client.get(
                "/api/admin/clientes",
                headers={"Authorization": "Bearer invalid"},
            ),
            401,
        )
        malformed = self.client.get(
            "/api/admin/clientes",
            headers={"Authorization": "Bearer eyJhbGciOiJIUzI1NiJ9.invalid"},
        )
        self.assert_status(malformed, 401)
        with self.app.app_context():
            expired_token = type(self).create_access_token(
                identity=str(self.admin_id),
                expires_delta=timedelta(seconds=-1),
            )
            operator = self.UsuarioSistema(
                nome="Operator Gate",
                usuario="operator-gate",
                email="operator-gate@example.invalid",
                senha="operator-hash",
                perfil="operador",
                ativo=True,
            )
            self.db.session.add(operator)
            self.db.session.commit()
            operator_token = type(self).create_access_token(
                identity=str(operator.id)
            )
        expired = self.client.get(
            "/api/admin/clientes",
            headers=self.auth(expired_token),
        )
        self.assert_status(expired, 401)
        self.assert_status(
            self.client.get(
                "/api/admin/clientes",
                headers=self.auth(self.admin_token),
            ),
            200,
        )
        self.assert_status(
            self.client.put(
                "/api/admin/clientes/1/inativar",
                headers=self.auth(operator_token),
            ),
            403,
        )
        ambiente_railway = {
            "APP_ENV": "staging",
            "RAILWAY_ENVIRONMENT_NAME": "staging",
        }
        headers_ip = {"X-Real-IP": "203.0.113.30"}
        with patch.dict(os.environ, ambiente_railway):
            for _ in range(5):
                self.assert_status(
                    self.client.post(
                        "/api/login",
                        json={"usuario": "admin-gate", "senha": "errada"},
                        headers=headers_ip,
                    ),
                    401,
                )
            limited = self.client.post(
                "/api/login",
                json={"usuario": "admin-gate", "senha": "errada"},
                headers=headers_ip,
            )
            self.assert_status(limited, 429)
            self.assertTrue(limited.is_json)
            self.assertGreaterEqual(
                int(limited.headers["Retry-After"]),
                1,
            )

            for _ in range(30):
                self.assert_status(
                    self.client.get(
                        "/api/rastreamento/GATE-RATE-LIMIT",
                        headers=headers_ip,
                    ),
                    404,
                )
            tracking_limited = self.client.get(
                "/api/rastreamento/GATE-RATE-LIMIT",
                headers=headers_ip,
            )
            self.assert_status(tracking_limited, 429)
            self.assertTrue(tracking_limited.is_json)
            self.assertGreaterEqual(
                int(tracking_limited.headers["Retry-After"]),
                1,
            )

        outro_ip = self.client.get(
            "/api/rastreamento/GATE-RATE-LIMIT",
            environ_base={"REMOTE_ADDR": "198.51.100.20"},
        )
        self.assert_status(outro_ip, 404)

    def test_upload_rate_limit_por_identidade_jwt(self):
        with self.app.app_context():
            operador = self.UsuarioSistema(
                nome="Operador Upload Gate",
                usuario="operador-upload-gate",
                email="operador-upload-gate@example.invalid",
                senha="hash-operador-upload",
                perfil="operador",
                ativo=True,
            )
            self.db.session.add(operador)
            self.db.session.commit()
            token_operador = type(self).create_access_token(
                identity=str(operador.id)
            )

        endpoint = (
            "/api/admin/viagens/999999/comprovante/arquivo"
        )

        for _ in range(10):
            self.assert_status(
                self.client.post(
                    endpoint,
                    headers=self.auth(self.admin_token),
                ),
                404,
            )

        limitado = self.client.post(
            endpoint,
            headers=self.auth(self.admin_token),
        )
        self.assert_status(limitado, 429)
        self.assertGreaterEqual(
            int(limitado.headers["Retry-After"]),
            1,
        )

        identidade_diferente = self.client.post(
            endpoint,
            headers=self.auth(token_operador),
        )
        self.assert_status(identidade_diferente, 404)

    def test_missing_api_route_is_generic_json(self):
        response = self.client.get("/api/rota-inexistente")
        self.assert_status(response, 404)
        self.assertEqual(response.mimetype, "application/json")
        self.assertEqual(response.get_json(), {
            "erro": "Recurso não encontrado."
        })

    def test_missing_web_route_preserves_flask_response(self):
        for path in ("/rota-inexistente", "/api", "/api-outra/rota-inexistente"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assert_status(response, 404)
                self.assertEqual(response.mimetype, "text/html")

    def test_api_internal_error_is_json(self):
        def fail():
            raise RuntimeError("database path, secret and token must not leak")

        endpoint = next(
            name
            for name in self.app.view_functions
            if name.endswith("api_admin_clientes")
        )
        original_view = self.app.view_functions[endpoint]
        self.app.view_functions[endpoint] = fail
        try:
            response = self.client.get("/api/admin/clientes")
        finally:
            self.app.view_functions[endpoint] = original_view
        self.assert_status(response, 500)
        self.assertTrue(response.is_json)
        self.assertEqual(response.get_json(), {
            "erro": "Erro interno do servidor."
        })
        self.assertNotIn("Traceback", response.get_data(as_text=True))
        self.assertNotIn("secret", response.get_data(as_text=True).lower())

    def test_tracking_minimal_contract_and_proxy(self):
        with self.app.app_context():
            tracking = self.Rastreamento(
                codigo="GATE-TRACK", cliente="private", status="Pendente",
                local_atual="A", destino="private-destination",
            )
            self.db.session.add(tracking)
            self.db.session.commit()
        response = self.client.get(
            "/api/rastreamento/GATE-TRACK",
            environ_base={
                "REMOTE_ADDR": "127.0.0.1",
                "HTTP_X_FORWARDED_FOR": "198.51.100.20",
            },
        )
        self.assert_status(response, 200)
        self.assertEqual(
            set(response.get_json()),
            {"codigo", "status", "previsao_entrega", "ultima_atualizacao"},
        )

    def test_upload_validation_and_private_download(self):
        with self.app.app_context():
            tracking = self.Rastreamento(
                codigo="UPLOAD-GATE", cliente="private", status="Pendente",
                local_atual="A", destino="B",
            )
            self.db.session.add(tracking)
            self.db.session.flush()
            viagem = self.Viagem(
                rastreamento_id=tracking.id, origem="A", destino="B",
                status="Planejada",
            )
            self.db.session.add(viagem)
            self.db.session.commit()
            viagem_id = viagem.id
        invalid = {"arquivo": (io.BytesIO(b"not-pdf"), "bad.pdf", "application/pdf")}
        self.assert_status(
            self.client.post(
                f"/api/admin/viagens/{viagem_id}/comprovante/arquivo",
                data=invalid,
                content_type="multipart/form-data",
                headers=self.auth(),
            ),
            400,
        )
        self.assert_status(
            self.client.get("/static/uploads/nope.pdf"),
            404,
        )

    def test_cors_and_integrity(self):
        response = self.client.options(
            "/api/login",
            headers={
                "Origin": "https://staging.example.invalid",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Authorization, Content-Type",
            },
        )
        self.assertEqual(
            response.headers.get("Access-Control-Allow-Origin"),
            "https://staging.example.invalid",
        )
        unknown = self.client.options(
            "/api/login",
            headers={
                "Origin": "https://unknown.example.invalid",
                "Access-Control-Request-Method": "POST",
            },
        )
        self.assertIsNone(unknown.headers.get("Access-Control-Allow-Origin"))

    def test_security_headers_by_environment_preserve_cors(self):
        import app as app_module

        for ambiente in ("staging", "production"):
            with patch.object(app_module, "APP_ENV", ambiente):
                response = self.client.get("/")

            self.assertEqual(
                response.headers.get("X-Content-Type-Options"),
                "nosniff",
            )
            self.assertEqual(
                response.headers.get("X-Frame-Options"),
                "DENY",
            )
            self.assertEqual(
                response.headers.get("Referrer-Policy"),
                "no-referrer",
            )
            self.assertEqual(
                response.headers.get("Permissions-Policy"),
                "camera=(), microphone=(), geolocation=()",
            )
            self.assertEqual(
                response.headers.get("Strict-Transport-Security"),
                "max-age=31536000",
            )

        for ambiente in ("development", "test"):
            with patch.object(app_module, "APP_ENV", ambiente):
                response = self.client.get("/")

            self.assertEqual(
                response.headers.get("X-Content-Type-Options"),
                "nosniff",
            )
            self.assertIsNone(
                response.headers.get("Strict-Transport-Security")
            )

        preflight = self.client.options(
            "/api/admin/clientes",
            headers={
                "Origin": "https://staging.example.invalid",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "Authorization, Content-Type",
            },
        )
        self.assertEqual(
            preflight.headers.get("Access-Control-Allow-Origin"),
            "https://staging.example.invalid",
        )

    def test_sqlite_integrity_and_restart_persistence(self):
        with sqlite3.connect(self.db_path) as connection:
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
            self.assertTrue(self.db_path.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
