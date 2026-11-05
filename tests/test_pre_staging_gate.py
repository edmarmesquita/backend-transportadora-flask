import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
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
        from models.comprovantes import ArquivoComprovanteViagem, ComprovanteEntrega
        from models.historicos import HistoricoRastreamento, HistoricoViagem
        from models.localizacoes import LocalizacaoViagem
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
        cls.ComprovanteEntrega = ComprovanteEntrega
        cls.HistoricoRastreamento = HistoricoRastreamento
        cls.HistoricoViagem = HistoricoViagem
        cls.LocalizacaoViagem = LocalizacaoViagem
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

    def test_maquina_de_estados_operacional_canonica(self):
        from utils.constantes import (
            TRANSICOES_CARGA,
            TRANSICOES_VIAGEM,
            SEQUENCIA_OPERACIONAL,
        )

        for atual, proximo in zip(SEQUENCIA_OPERACIONAL, SEQUENCIA_OPERACIONAL[1:]):
            self.assertIn(proximo, TRANSICOES_CARGA[atual])
            self.assertIn(proximo, TRANSICOES_VIAGEM[atual])

        for atual, salto in (
            ("Em preparação", "Carregando"),
            ("Em coleta", "Em trânsito"),
            ("Carregando", "Saiu para entrega"),
            ("Em trânsito", "Entregue"),
        ):
            self.assertNotIn(salto, TRANSICOES_CARGA[atual])
            self.assertNotIn(salto, TRANSICOES_VIAGEM[atual])

        self.assertIn("Em trânsito", TRANSICOES_VIAGEM["Parada operacional"])
        self.assertIn("Saiu para entrega", TRANSICOES_VIAGEM["Parada operacional"])
        self.assertIn("Em preparação", TRANSICOES_CARGA["Pendente"])
        self.assertIn("Em preparação", TRANSICOES_CARGA["Programada"])
        self.assertIn("Em trânsito", TRANSICOES_VIAGEM["Planejada"])

    def test_iniciar_viagem_registra_execucao_e_preserva_planejamento(self):
        from datetime import timezone

        planejada_saida = datetime(2026, 11, 4, 8, 0)
        planejada_entrega = datetime(2026, 11, 4, 14, 30)
        partida_utc = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)
        entrega_existente = datetime(2026, 11, 5, 19, 45)
        partida_existente = datetime(2026, 11, 4, 10, 15)

        with self.app.app_context():
            cliente = self.Cliente(razao_social="Cliente inicio de viagem")
            self.db.session.add(cliente)
            self.db.session.flush()

            carga_nova = self.Rastreamento(
                codigo="GATE-INICIAR-NOVO",
                cliente=cliente.razao_social,
                cliente_id=cliente.id,
                status="Planejada",
                local_atual="Sao Paulo/SP",
                destino="Campinas/SP",
                data_prevista_saida=planejada_saida,
                previsao_entrega=planejada_entrega,
            )
            carga_existente = self.Rastreamento(
                codigo="GATE-INICIAR-PREENCHIDO",
                cliente=cliente.razao_social,
                cliente_id=cliente.id,
                status="Planejada",
                local_atual="Sao Paulo/SP",
                destino="Santos/SP",
                data_prevista_saida=datetime(2026, 11, 4, 7, 0),
                previsao_entrega=datetime(2026, 11, 6, 9, 0),
            )
            self.db.session.add_all([carga_nova, carga_existente])
            self.db.session.flush()

            viagem_nova = self.Viagem(
                rastreamento_id=carga_nova.id,
                origem="Sao Paulo/SP",
                destino="Campinas/SP",
                status="Planejada",
                data_saida=None,
                previsao_entrega=None,
            )
            viagem_existente = self.Viagem(
                rastreamento_id=carga_existente.id,
                origem="Sao Paulo/SP",
                destino="Santos/SP",
                status="Planejada",
                data_saida=partida_existente,
                previsao_entrega=entrega_existente,
            )
            self.db.session.add_all([viagem_nova, viagem_existente])
            self.db.session.commit()
            ids = (viagem_nova.id, viagem_existente.id)

        with patch(
            "services.inicio_viagem.instante_atual_utc",
            return_value=partida_utc,
        ):
            for viagem_id in ids:
                response = self.client.post(
                    f"/api/admin/viagens/{viagem_id}/status",
                    json={"status": "Em tr\u00e2nsito"},
                    headers=self.auth(),
                )
                self.assert_status(response, 200)

        detalhe = self.client.get(
            f"/api/admin/viagens/{ids[0]}",
            headers=self.auth(),
        )
        self.assert_status(detalhe, 200)
        self.assertEqual(detalhe.get_json()["data_saida_iso"], "2026-11-04T12:00:00Z")
        self.assertEqual(detalhe.get_json()["data_saida"], "04/11/2026 09:00")
        self.assertEqual(detalhe.get_json()["previsao_entrega"], "04/11/2026 14:30")
        self.assertEqual(detalhe.get_json()["previsao_entrega_local"], "2026-11-04T14:30")

        with self.app.app_context():
            primeira = self.db.session.get(self.Viagem, ids[0])
            primeira_carga = self.db.session.get(
                self.Rastreamento, primeira.rastreamento_id
            )
            segunda = self.db.session.get(self.Viagem, ids[1])
            self.assertEqual(primeira.status, "Em tr\u00e2nsito")
            self.assertEqual(primeira_carga.status, "Em tr\u00e2nsito")
            self.assertEqual(primeira.data_saida, datetime(2026, 11, 4, 12, 0))
            self.assertEqual(primeira.previsao_entrega, planejada_entrega)
            self.assertNotEqual(primeira.data_saida, planejada_saida)
            self.assertEqual(segunda.data_saida, partida_existente)
            self.assertEqual(segunda.previsao_entrega, entrega_existente)

    def test_inicio_viagem_pelo_motorista_grava_datas_reais_sem_sobrescrever(self):
        from datetime import timezone

        partida_utc = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)
        entrega_planejada = datetime(2026, 11, 4, 14, 30)
        partida_existente = datetime(2026, 11, 4, 10, 15)
        entrega_existente = datetime(2026, 11, 5, 19, 45)

        with self.app.app_context():
            usuarios = [
                self.UsuarioSistema(
                    nome=f"Motorista Inicio {indice}",
                    usuario=f"motorista-inicio-{indice}",
                    email=f"motorista-inicio-{indice}@example.invalid",
                    senha="hash-motorista",
                    perfil="motorista",
                    ativo=True,
                )
                for indice in range(2)
            ]
            self.db.session.add_all(usuarios)
            self.db.session.flush()
            motoristas = [
                self.Motorista(
                    nome=usuario.nome,
                    usuario_sistema_id=usuario.id,
                    status="Ativo",
                )
                for usuario in usuarios
            ]
            self.db.session.add_all(motoristas)
            self.db.session.flush()
            cargas = [
                self.Rastreamento(
                    codigo=f"GATE-MOTORISTA-INICIO-{indice}",
                    cliente="Cliente início motorista",
                    status="Planejada",
                    local_atual="São Paulo/SP",
                    destino="Campinas/SP",
                    data_prevista_saida=datetime(2026, 11, 4, 8, 0),
                    previsao_entrega=entrega_planejada,
                )
                for indice in range(2)
            ]
            self.db.session.add_all(cargas)
            self.db.session.flush()
            viagens = [
                self.Viagem(
                    rastreamento_id=cargas[0].id,
                    motorista_id=motoristas[0].id,
                    origem="São Paulo/SP",
                    destino="Campinas/SP",
                    status="Planejada",
                ),
                self.Viagem(
                    rastreamento_id=cargas[1].id,
                    motorista_id=motoristas[1].id,
                    origem="São Paulo/SP",
                    destino="Campinas/SP",
                    status="Planejada",
                    data_saida=partida_existente,
                    previsao_entrega=entrega_existente,
                ),
            ]
            self.db.session.add_all(viagens)
            self.db.session.commit()
            ids = [viagem.id for viagem in viagens]
            tokens = [
                type(self).create_access_token(identity=str(usuario.id))
                for usuario in usuarios
            ]

        with patch(
            "services.inicio_viagem.instante_atual_utc",
            return_value=partida_utc,
        ):
            for viagem_id, token in zip(ids, tokens):
                response = self.client.post(
                    f"/api/motorista/minhas-viagens/{viagem_id}/status",
                    json={"status": "Em trânsito"},
                    headers=self.auth(token),
                )
                self.assert_status(response, 200)

        with self.app.app_context():
            primeira = self.db.session.get(self.Viagem, ids[0])
            primeira_carga = self.db.session.get(
                self.Rastreamento, primeira.rastreamento_id
            )
            segunda = self.db.session.get(self.Viagem, ids[1])
            self.assertEqual(primeira.data_saida, datetime(2026, 11, 4, 12, 0))
            self.assertNotEqual(
                primeira.data_saida,
                datetime(2026, 11, 4, 8, 0),
            )
            self.assertEqual(primeira.previsao_entrega, entrega_planejada)
            self.assertEqual(primeira_carga.status, "Em trânsito")
            self.assertEqual(segunda.data_saida, partida_existente)
            self.assertEqual(segunda.previsao_entrega, entrega_existente)

    def test_detalhe_motorista_serializa_datas_e_bloqueia_idor(self):
        with self.app.app_context():
            usuarios = [
                self.UsuarioSistema(
                    nome=f"Motorista Detalhe {indice}",
                    usuario=f"motorista-detalhe-{indice}",
                    email=f"motorista-detalhe-{indice}@example.invalid",
                    senha="hash-motorista",
                    perfil="motorista",
                    ativo=True,
                )
                for indice in range(2)
            ]
            self.db.session.add_all(usuarios)
            self.db.session.flush()
            motoristas = [
                self.Motorista(
                    nome=usuario.nome,
                    usuario_sistema_id=usuario.id,
                    status="Ativo",
                )
                for usuario in usuarios
            ]
            self.db.session.add_all(motoristas)
            self.db.session.flush()
            carga = self.Rastreamento(
                codigo="GATE-DETALHE-MOTORISTA-DATAS",
                cliente="Cliente detalhe motorista",
                status="Em trânsito",
                local_atual="São Paulo/SP",
                destino="Campinas/SP",
                previsao_entrega=datetime(2026, 11, 4, 14, 30),
            )
            self.db.session.add(carga)
            self.db.session.flush()
            viagem = self.Viagem(
                rastreamento_id=carga.id,
                motorista_id=motoristas[0].id,
                origem="São Paulo/SP",
                destino="Campinas/SP",
                status="Em trânsito",
                data_saida=datetime(2026, 11, 4, 12, 0),
                previsao_entrega=carga.previsao_entrega,
                data_criacao=datetime(2026, 11, 5, 15, 8, 58, 511542),
            )
            viagem_sem_datas = self.Viagem(
                rastreamento_id=carga.id,
                motorista_id=motoristas[0].id,
                origem="São Paulo/SP",
                destino="Campinas/SP",
                status="Em trânsito",
                data_criacao=None,
            )
            self.db.session.add_all([viagem, viagem_sem_datas])
            self.db.session.flush()
            viagem_sem_datas.data_criacao = None
            self.db.session.commit()
            viagem_id = viagem.id
            viagem_sem_datas_id = viagem_sem_datas.id
            tokens = [
                type(self).create_access_token(identity=str(usuario.id))
                for usuario in usuarios
            ]

        detalhe = self.client.get(
            f"/api/motorista/minhas-viagens/{viagem_id}",
            headers=self.auth(tokens[0]),
        )
        self.assert_status(detalhe, 200)
        self.assertEqual(
            detalhe.get_json()["data_saida"],
            "04/11/2026 09:00",
        )
        self.assertEqual(
            detalhe.get_json()["previsao_entrega"],
            "04/11/2026 14:30",
        )
        self.assertEqual(detalhe.get_json()["data_criacao"], "05/11/2026 12:08")
        self.assertEqual(
            detalhe.get_json()["data_criacao_iso"],
            "2026-11-05T15:08:58.511542Z",
        )
        sem_datas = self.client.get(
            f"/api/motorista/minhas-viagens/{viagem_sem_datas_id}",
            headers=self.auth(tokens[0]),
        )
        self.assert_status(sem_datas, 200)
        self.assertEqual(sem_datas.get_json()["data_saida"], "")
        self.assertEqual(sem_datas.get_json()["previsao_entrega"], "")
        self.assertEqual(sem_datas.get_json()["data_criacao"], "")
        self.assertIsNone(sem_datas.get_json()["data_criacao_iso"])

        historico = self.client.get(
            f"/api/motorista/minhas-viagens/{viagem_id}/historico",
            headers=self.auth(tokens[0]),
        )
        self.assert_status(historico, 200)
        self.assertEqual(historico.get_json(), [])

        outro_motorista = self.client.get(
            f"/api/motorista/minhas-viagens/{viagem_id}",
            headers=self.auth(tokens[1]),
        )
        self.assert_status(outro_motorista, 404)

    def test_serializacao_temporal_dos_endpoints_prioritarios(self):
        instante_usuario = datetime(2026, 11, 1, 21, 8)
        instante_carga = datetime(2026, 11, 1, 23, 8)
        instante_viagem = datetime(2026, 10, 31, 11, 56)

        with self.app.app_context():
            cliente = self.Cliente(razao_social="Cliente Datas API")
            usuario_cliente = self.UsuarioSistema(
                nome="Cliente Datas API",
                usuario="cliente-datas-api",
                email="cliente-datas-api@example.invalid",
                senha="hash-cliente",
                perfil="cliente",
                ativo=True,
            )
            usuario_alvo = self.UsuarioSistema(
                nome="Usuario Datas API",
                usuario="usuario-datas-api",
                email="usuario-datas-api@example.invalid",
                senha="hash-usuario",
                perfil="operador",
                ativo=True,
                data_criacao=instante_usuario,
            )
            self.db.session.add_all([cliente, usuario_cliente, usuario_alvo])
            self.db.session.flush()
            self.db.session.add(self.ClienteUsuario(
                cliente_id=cliente.id,
                usuario_sistema_id=usuario_cliente.id,
                nome=usuario_cliente.nome,
                empresa=cliente.razao_social,
                email=usuario_cliente.email,
                senha="hash-cliente",
                ativo=True,
            ))
            carga = self.Rastreamento(
                codigo="GATE-DATAS-API",
                cliente=cliente.razao_social,
                cliente_id=cliente.id,
                status="Em trânsito",
                local_atual="São Paulo/SP",
                destino="Campinas/SP",
                ultima_atualizacao=instante_carga,
            )
            carga.data_prevista_saida = datetime(2026, 11, 5, 17, 30)
            carga.previsao_entrega = datetime(2026, 11, 6, 9, 15)
            self.db.session.add(carga)
            self.db.session.flush()
            viagem = self.Viagem(
                rastreamento_id=carga.id,
                origem="São Paulo/SP",
                destino="Campinas/SP",
                status="Em trânsito",
                data_criacao=instante_viagem,
            )
            self.db.session.add(viagem)
            self.db.session.flush()
            self.db.session.add(self.HistoricoRastreamento(
                rastreamento_id=carga.id,
                status="Em trânsito",
                local="São Paulo/SP",
                observacao="Evento com instante igual à criação da viagem.",
                data_evento=instante_viagem,
            ))
            self.db.session.add(self.HistoricoViagem(
                viagem_id=viagem.id,
                status="DESPACHO",
                observacao="Evento com instante igual à criação da viagem.",
                data_evento=instante_viagem,
            ))
            self.db.session.commit()
            carga_id = carga.id
            viagem_id = viagem.id
            token_cliente = type(self).create_access_token(
                identity=str(usuario_cliente.id)
            )

        usuarios = self.client.get(
            "/api/admin/usuarios",
            headers=self.auth(),
        )
        self.assert_status(usuarios, 200)
        usuario_json = next(
            item for item in usuarios.get_json()
            if item["usuario"] == "usuario-datas-api"
        )
        self.assertEqual(usuario_json["data_criacao"], "01/11/2026 18:08")
        self.assertEqual(usuario_json["data_criacao_iso"], "2026-11-01T21:08:00Z")

        carga_admin = self.client.get(
            f"/api/admin/cargas/{carga_id}",
            headers=self.auth(),
        )
        self.assert_status(carga_admin, 200)
        carga_admin_json = carga_admin.get_json()
        self.assertEqual(carga_admin_json["data_prevista_saida"], "05/11/2026 17:30")
        self.assertEqual(carga_admin_json["previsao_entrega"], "06/11/2026 09:15")
        self.assertEqual(carga_admin_json["ultima_atualizacao"], "01/11/2026 20:08")
        self.assertEqual(
            carga_admin_json["ultima_atualizacao_iso"],
            "2026-11-01T23:08:00Z",
        )

        cargas_cliente = self.client.get(
            "/api/cliente/minhas-cargas",
            headers=self.auth(token_cliente),
        )
        self.assert_status(cargas_cliente, 200)
        carga_cliente_json = next(
            item for item in cargas_cliente.get_json()
            if item["id"] == carga_id
        )
        self.assertEqual(carga_cliente_json["ultima_atualizacao"], "01/11/2026 20:08")
        self.assertEqual(
            carga_cliente_json["ultima_atualizacao_iso"],
            "2026-11-01T23:08:00Z",
        )

        detalhe_cliente = self.client.get(
            f"/api/cliente/minhas-cargas/{carga_id}",
            headers=self.auth(token_cliente),
        )
        self.assert_status(detalhe_cliente, 200)
        detalhe_json = detalhe_cliente.get_json()
        self.assertEqual(detalhe_json["ultima_atualizacao"], "01/11/2026 20:08")
        self.assertEqual(
            detalhe_json["ultima_atualizacao_iso"],
            "2026-11-01T23:08:00Z",
        )
        self.assertEqual(
            detalhe_json["historico"][0]["data_evento"],
            "31/10/2026 08:56",
        )
        self.assertEqual(detalhe_json["descricao_carga"], None)
        self.assertEqual(detalhe_json["peso_kg"], None)
        self.assertEqual(detalhe_json["data_prevista_saida"], "05/11/2026 17:30")
        self.assertEqual(detalhe_json["previsao_entrega"], "06/11/2026 09:15")
        self.assertEqual(detalhe_json["descricao_carga"], None)
        self.assertEqual(detalhe_json["peso_kg"], None)
        self.assertEqual(detalhe_json["data_prevista_saida"], "05/11/2026 17:30")
        self.assertEqual(detalhe_json["previsao_entrega"], "06/11/2026 09:15")

        viagens = self.client.get(
            "/api/admin/viagens",
            headers=self.auth(),
        )
        self.assert_status(viagens, 200)
        viagem_lista = next(
            item for item in viagens.get_json()
            if item["id"] == viagem_id
        )
        self.assertEqual(viagem_lista["data_criacao"], "31/10/2026 08:56")
        self.assertEqual(
            viagem_lista["data_criacao_iso"],
            "2026-10-31T11:56:00Z",
        )

        viagem_detalhe = self.client.get(
            f"/api/admin/viagens/{viagem_id}",
            headers=self.auth(),
        )
        self.assert_status(viagem_detalhe, 200)
        self.assertEqual(
            viagem_detalhe.get_json()["data_criacao"],
            viagem_lista["data_criacao"],
        )
        self.assertEqual(
            viagem_detalhe.get_json()["data_criacao_iso"],
            viagem_lista["data_criacao_iso"],
        )

        historico_viagem = self.client.get(
            f"/api/admin/viagens/{viagem_id}/historico",
            headers=self.auth(),
        )
        self.assert_status(historico_viagem, 200)
        self.assertEqual(
            historico_viagem.get_json()[0]["data_evento"],
            viagem_lista["data_criacao"],
        )

    def test_health_saudavel_e_publico(self):
        response = self.client.get("/health")

        self.assert_status(response, 200)
        self.assertEqual(response.get_json(), {
            "status": "ok",
            "service": "transportadora-backend",
        })

    def test_raiz_publica_identifica_rotanza(self):
        response = self.client.get("/")

        self.assert_status(response, 200)
        self.assertEqual(response.get_json(), {
            "mensagem": "Backend Rotanza ativo.",
            "status": "online",
        })

    def test_configuracao_transportadora_autorizacao_validacao_e_pdf(self):
        from models.configuracao_transportadora import ConfiguracaoTransportadora

        rota = "/api/configuracao/transportadora"
        self.assert_status(self.client.get(rota), 401)
        with self.app.app_context():
            self.db.session.query(ConfiguracaoTransportadora).delete()
            self.db.session.commit()
        self._validar_configuracao_transportadora_existente()

    def test_logo_transportadora_upload_leitura_pdf_substituicao_e_remocao(self):
        from flask_jwt_extended import create_access_token
        from PIL import Image
        from models.configuracao_transportadora import ConfiguracaoTransportadora
        from services.logo_transportadora import logo_existente

        rota = "/api/configuracao/transportadora/logo"

        def imagem_bytes(formato):
            buffer = io.BytesIO()
            Image.new("RGB", (20, 12), "blue").save(buffer, format=formato)
            return buffer.getvalue()

        def enviar(dados, nome, headers=None):
            return self.client.post(
                rota,
                headers=headers or self.auth(),
                data={"arquivo": (io.BytesIO(dados), nome)},
                content_type="multipart/form-data",
            )

        png = imagem_bytes("PNG")
        buffer_dimensoes_excessivas = io.BytesIO()
        Image.new("RGB", (4000, 2100), "white").save(
            buffer_dimensoes_excessivas, format="PNG", optimize=True
        )
        png_dimensoes_excessivas = buffer_dimensoes_excessivas.getvalue()
        for metodo in ("GET", "POST", "DELETE"):
            self.assert_status(self.client.open(rota, method=metodo), 401)
            self.assert_status(self.client.open(
                rota,
                method=metodo,
                headers={"Authorization": "Bearer invalid"},
            ), 401)
        self.assert_status(enviar(png, "logo.png"), 409)

        with self.app.app_context():
            self.db.session.add(ConfiguracaoTransportadora(
                id=1, nome_exibicao="Transportadora Teste",
                razao_social="Transportadora Teste Ltda",
            ))
            operador = self.UsuarioSistema(
                nome="Operador Logo", usuario="operador-logo-gate",
                senha="hash-de-teste", perfil="operador", ativo=True,
            )
            inativo = self.UsuarioSistema(
                nome="Inativo Logo", usuario="inativo-logo-gate",
                senha="hash-de-teste", perfil="administrador", ativo=False,
            )
            self.db.session.add_all((operador, inativo))
            self.db.session.commit()
            token_operador = create_access_token(identity=str(operador.id))
            token_inativo = create_access_token(identity=str(inativo.id))

        self.assert_status(enviar(png, "logo.png", self.auth(token_operador)), 403)
        self.assert_status(enviar(png, "logo.png", self.auth(token_inativo)), 401)
        self.assert_status(self.client.get(rota, headers=self.auth(token_inativo)), 401)
        self.assert_status(self.client.delete(rota, headers=self.auth(token_operador)), 403)
        self.assert_status(self.client.delete(rota, headers=self.auth(token_inativo)), 401)
        self.assert_status(self.client.get(rota, headers=self.auth()), 404)

        for conteudo, nome, esperado in (
            (b"", "vazio.png", 400),
            (b"texto", "falso.png", 400),
            (imagem_bytes("GIF"), "gif-renomeado.png", 400),
            (png_dimensoes_excessivas, "dimensoes-excessivas.png", 400),
            (png, "logo.txt", 400),
            (png, "../logo.png", 400),
            (b"x" * (5 * 1024 * 1024 + 1), "grande.png", 413),
        ):
            self.assert_status(enviar(conteudo, nome), esperado)

        primeiro = enviar(png, "logo.png")
        self.assert_status(primeiro, 201)
        referencia = primeiro.get_json()["logo"]
        self.assertRegex(referencia, r"^[0-9a-f]{32}\.png$")
        with self.app.app_context():
            configuracao = self.db.session.get(ConfiguracaoTransportadora, 1)
            self.assertEqual(configuracao.logo, referencia)
            caminho = logo_existente(str(self.upload_dir), referencia)
            self.assertIsNotNone(caminho)
            log_upload = self.LogAcao.query.filter_by(
                entidade="ConfiguracaoTransportadora",
                acao="Upload de logo da transportadora",
            ).one()
            self.assertEqual(json.loads(log_upload.antes), {"logo": None})
            self.assertEqual(
                json.loads(log_upload.depois), {"logo": referencia}
            )

        resposta = self.client.get(rota, headers=self.auth(token_operador))
        self.assert_status(resposta, 200)
        self.assertEqual(resposta.data, png)
        self.assertEqual(resposta.mimetype, "image/png")
        self.assertEqual(resposta.headers["Cache-Control"], "private, no-store")
        resposta.close()
        self.assert_status(self.client.put(
            "/api/configuracao/transportadora", headers=self.auth(),
            json={"logo": "../outro.png"},
        ), 400)

        for rota_pdf in (
            "/api/admin/relatorios/viagens/pdf",
            "/api/admin/relatorios/financeiro/pdf",
        ):
            resposta_pdf = self.client.get(rota_pdf, headers=self.auth())
            self.assert_status(resposta_pdf, 200)
            self.assertIn(b"/Subtype /Image", resposta_pdf.data)

        with patch("routes.configuracao_transportadora.registrar_log", side_effect=RuntimeError):
            self.assert_status(enviar(imagem_bytes("JPEG"), "falha.jpg"), 500)
        with self.app.app_context():
            self.assertEqual(
                self.db.session.get(ConfiguracaoTransportadora, 1).logo,
                referencia,
            )
            self.assertEqual(
                len(list((self.upload_dir / "logos_transportadora").iterdir())), 1
            )

        with patch("sqlalchemy.orm.Session.commit", side_effect=RuntimeError):
            self.assert_status(enviar(imagem_bytes("JPEG"), "falha-commit.jpg"), 500)
        with self.app.app_context():
            self.assertEqual(
                self.db.session.get(ConfiguracaoTransportadora, 1).logo,
                referencia,
            )
            self.assertEqual(
                len(list((self.upload_dir / "logos_transportadora").iterdir())), 1
            )

        segundo = enviar(imagem_bytes("JPEG"), "novo.jpeg")
        self.assert_status(segundo, 201)
        referencia_nova = segundo.get_json()["logo"]
        self.assertNotEqual(referencia, referencia_nova)
        self.assertTrue(referencia_nova.endswith(".jpg"))
        with self.app.app_context():
            self.assertIsNone(logo_existente(str(self.upload_dir), referencia))
            self.assertIsNotNone(logo_existente(str(self.upload_dir), referencia_nova))

        with patch("routes.configuracao_transportadora.registrar_log", side_effect=RuntimeError):
            self.assert_status(self.client.delete(rota, headers=self.auth()), 500)
        with self.app.app_context():
            self.assertEqual(
                self.db.session.get(ConfiguracaoTransportadora, 1).logo,
                referencia_nova,
            )
            self.assertIsNotNone(
                logo_existente(str(self.upload_dir), referencia_nova)
            )

        self.assert_status(self.client.delete(rota, headers=self.auth()), 200)
        self.assert_status(self.client.get(rota, headers=self.auth()), 404)
        with self.app.app_context():
            self.assertIsNone(self.db.session.get(ConfiguracaoTransportadora, 1).logo)
            self.assertIsNone(logo_existente(str(self.upload_dir), referencia_nova))
            log_remocao = self.LogAcao.query.filter_by(
                entidade="ConfiguracaoTransportadora",
                acao="Remoção de logo da transportadora",
            ).one()
            self.assertEqual(
                json.loads(log_remocao.antes), {"logo": referencia_nova}
            )
            self.assertEqual(json.loads(log_remocao.depois), {"logo": None})
            self.db.session.query(ConfiguracaoTransportadora).delete()
            self.db.session.commit()

    def test_logo_transportadora_pdf_sem_arquivo_e_referencia_invalida(self):
        from models.configuracao_transportadora import ConfiguracaoTransportadora
        from services.logo_transportadora import caminho_logo

        rota_logo = "/api/configuracao/transportadora/logo"
        rotas_pdf = (
            "/api/admin/relatorios/viagens/pdf",
            "/api/admin/relatorios/financeiro/pdf",
        )
        for rota_pdf in rotas_pdf:
            resposta = self.client.get(rota_pdf, headers=self.auth())
            self.assert_status(resposta, 200)
            self.assertNotIn(b"/Subtype /Image", resposta.data)

        with self.app.app_context():
            self.db.session.add(ConfiguracaoTransportadora(
                id=1, nome_exibicao="Transportadora Teste",
                razao_social="Transportadora Teste Ltda",
                logo="../arquivo-fora.png",
            ))
            self.db.session.commit()
        arquivo_fora = self.temp_dir / "arquivo-fora.png"
        arquivo_fora.write_bytes(b"nao-remover")
        self.assert_status(self.client.get(rota_logo, headers=self.auth()), 404)
        for rota_pdf in rotas_pdf:
            self.assert_status(self.client.get(rota_pdf, headers=self.auth()), 200)
        self.assert_status(self.client.delete(rota_logo, headers=self.auth()), 200)
        self.assertEqual(arquivo_fora.read_bytes(), b"nao-remover")

        with self.app.app_context():
            self.db.session.get(ConfiguracaoTransportadora, 1).logo = "a" * 32 + ".png"
            self.db.session.commit()
        for rota_pdf in rotas_pdf:
            resposta = self.client.get(rota_pdf, headers=self.auth())
            self.assert_status(resposta, 200)
            self.assertNotIn(b"/Subtype /Image", resposta.data)
        self.assert_status(self.client.delete(rota_logo, headers=self.auth()), 200)
        with self.app.app_context():
            self.assertIsNone(
                self.db.session.get(ConfiguracaoTransportadora, 1).logo
            )
            self.db.session.get(ConfiguracaoTransportadora, 1).logo = (
                "a" * 32 + ".png"
            )
            self.db.session.commit()
        caminho_corrompido = caminho_logo(str(self.upload_dir), "a" * 32 + ".png")
        Path(caminho_corrompido).parent.mkdir(parents=True, exist_ok=True)
        Path(caminho_corrompido).write_bytes(b"nao-e-imagem")
        for rota_pdf in rotas_pdf:
            resposta = self.client.get(rota_pdf, headers=self.auth())
            self.assert_status(resposta, 200)
            self.assertNotIn(b"/Subtype /Image", resposta.data)
        Path(caminho_corrompido).unlink()
        with self.app.app_context():
            self.db.session.query(ConfiguracaoTransportadora).delete()
            self.LogAcao.query.filter_by(
                entidade="ConfiguracaoTransportadora",
                acao="Remoção de logo da transportadora",
            ).delete()
            self.db.session.commit()

    def _validar_configuracao_transportadora_existente(self):
        from sqlalchemy.exc import IntegrityError
        from flask_jwt_extended import create_access_token
        from models.configuracao_transportadora import ConfiguracaoTransportadora
        from routes.admin_relatorios import nome_transportadora_relatorio

        rota = "/api/configuracao/transportadora"
        with self.app.app_context():
            self.assertEqual(nome_transportadora_relatorio(), "TRANSPORTADORA")

        vazio = self.client.get(rota, headers=self.auth())
        self.assert_status(vazio, 200)
        self.assertIsNone(vazio.get_json()["nome_exibicao"])
        self.assert_status(
            self.client.put(rota, headers=self.auth(), json={"nome_exibicao": ""}),
            400,
        )
        self.assert_status(
            self.client.put(rota, headers=self.auth(), json={
                "nome_exibicao": "Transportadora Gate",
                "razao_social": "Gate Logística Ltda",
                "campo_inesperado": "valor",
            }), 400,
        )
        for campo, valor in (
            ("telefone", "---"), ("telefone", "123"),
            ("whatsapp", "( )"), ("whatsapp", "123"),
        ):
            self.assert_status(
                self.client.put(rota, headers=self.auth(), json={
                    "nome_exibicao": "Transportadora Gate",
                    "razao_social": "Gate Logística Ltda",
                    campo: valor,
                }), 400,
            )
        self.assert_status(
            self.client.put(rota, headers=self.auth(), json={
                "nome_exibicao": "Transportadora Gate",
                "razao_social": "Gate Logística Ltda",
                "cnpj": "00000000000000",
            }), 400,
        )
        self.assert_status(
            self.client.put(rota, headers=self.auth(), json={
                "nome_exibicao": "Transportadora Gate",
                "razao_social": "Gate Logística Ltda",
                "logo": "https://example.invalid/logo.png",
            }), 400,
        )

        dados = {
            "nome_exibicao": "Transportadora Gate",
            "razao_social": "Gate Logística Ltda",
            "cnpj": "11.444.777/0001-61",
            "telefone": "(11) 3333-4444",
            "whatsapp": "11999999999",
            "email": "contato@example.invalid",
            "endereco": "Rua de Teste, 123",
        }
        resposta = self.client.put(rota, headers=self.auth(), json=dados)
        self.assert_status(resposta, 200)
        self.assertEqual(resposta.get_json()["cnpj"], "11444777000161")
        self.assertIsNone(resposta.get_json()["logo"])
        self.assert_status(self.client.get(rota, headers=self.auth()), 200)

        with self.app.app_context():
            self.assertEqual(ConfiguracaoTransportadora.query.count(), 1)
            self.assertEqual(nome_transportadora_relatorio(), "Transportadora Gate")
            self.db.session.add(ConfiguracaoTransportadora(
                id=2, nome_exibicao="Outra", razao_social="Outra Ltda"
            ))
            with self.assertRaises(IntegrityError):
                self.db.session.commit()
            self.db.session.rollback()

        self.assert_status(self.client.get(
            "/api/admin/relatorios/viagens/pdf", headers=self.auth()
        ), 200)
        self.assert_status(self.client.get(
            "/api/admin/relatorios/financeiro/pdf", headers=self.auth()
        ), 200)

        with self.app.app_context():
            operador = self.UsuarioSistema(
                nome="Operador Gate", usuario="operador-config-gate",
                senha="hash-de-teste", perfil="operador", ativo=True,
            )
            self.db.session.add(operador)
            self.db.session.commit()
            operador_token = create_access_token(identity=str(operador.id))

        cabecalho_operador = self.auth(operador_token)
        self.assert_status(self.client.get(rota, headers=cabecalho_operador), 200)
        self.assert_status(self.client.put(
            rota, headers=cabecalho_operador, json=dados
        ), 403)
        with self.app.app_context():
            self.db.session.get(self.UsuarioSistema, operador.id).ativo = False
            self.db.session.commit()
        self.assert_status(self.client.get(rota, headers=cabecalho_operador), 401)
        self.assert_status(self.client.put(
            rota, headers=cabecalho_operador, json=dados
        ), 401)
        self.assert_status(self.client.put(
            rota, headers=self.auth(), json={"nome_exibicao": "Nova Gate"}
        ), 200)
        with self.app.app_context():
            self.assertEqual(ConfiguracaoTransportadora.query.count(), 1)
            self.db.session.query(ConfiguracaoTransportadora).delete()
            self.db.session.commit()

    def test_health_nao_expoe_informacoes_sensiveis(self):
        response = self.client.get("/health")
        corpo = response.get_data(as_text=True).lower()

        self.assert_status(response, 200)
        for termo_sensivel in (
            "database_url",
            "redis_url",
            "jwt",
            "secret",
            "traceback",
            "sqlite://",
            str(BACKEND_DIR).lower(),
        ):
            with self.subTest(termo=termo_sensivel):
                self.assertNotIn(termo_sensivel, corpo)

    def test_health_aplica_headers_de_seguranca(self):
        response = self.client.get("/health")

        self.assert_status(response, 200)
        self.assertEqual(
            response.headers.get("X-Content-Type-Options"),
            "nosniff",
        )
        self.assertEqual(response.headers.get("X-Frame-Options"), "DENY")
        self.assertEqual(
            response.headers.get("Referrer-Policy"),
            "no-referrer",
        )
        self.assertEqual(
            response.headers.get("Permissions-Policy"),
            "camera=(), microphone=(), geolocation=()",
        )

    def test_health_degradado_quando_banco_indisponivel(self):
        import app as app_module
        from sqlalchemy.exc import SQLAlchemyError

        detalhe_interno = "database.internal:5432 senha=nao-expor"
        with patch.object(
            app_module,
            "verificar_conexao_banco",
            side_effect=SQLAlchemyError(detalhe_interno),
        ), patch.object(app_module.app.logger, "exception"):
            response = self.client.get("/health")

        self.assert_status(response, 503)
        self.assertEqual(response.get_json(), {
            "status": "degraded",
            "service": "transportadora-backend",
        })
        corpo = response.get_data(as_text=True)
        self.assertNotIn(detalhe_interno, corpo)
        self.assertNotIn("traceback", corpo.lower())

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

    def test_admin_usuario_redefine_senha_cliente_com_email_legado_duplicado(self):
        from utils.senhas import gerar_hash_senha, verificar_senha

        email = "cliente-edicao-legado@example.invalid"

        with self.app.app_context():
            cliente = self.Cliente(
                razao_social="Cliente Edicao Legado",
                ativo=True,
            )
            usuario = self.UsuarioSistema(
                nome="Cliente Edicao",
                usuario="cliente-edicao-gate",
                email=email,
                senha=gerar_hash_senha("senha-anterior-cliente"),
                perfil="cliente",
                ativo=True,
            )
            usuario_duplicado = self.UsuarioSistema(
                nome="Cliente Duplicado Legado",
                usuario="cliente-duplicado-legado-gate",
                email=email,
                senha=gerar_hash_senha("senha-duplicado-cliente"),
                perfil="cliente",
                ativo=True,
            )
            self.db.session.add_all([
                cliente,
                usuario,
                usuario_duplicado,
            ])
            self.db.session.flush()
            cliente_usuario = self.ClienteUsuario(
                cliente_id=cliente.id,
                usuario_sistema_id=usuario.id,
                nome=usuario.nome,
                empresa=cliente.razao_social,
                email=email,
                senha=usuario.senha,
                ativo=True,
            )
            self.db.session.add(cliente_usuario)
            self.db.session.commit()
            usuario_id = usuario.id
            cliente_id = cliente.id
            cliente_usuario_id = cliente_usuario.id
            senha_duplicado = usuario_duplicado.senha

        response = self.client.put(
            f"/api/admin/usuarios/{usuario_id}",
            json={
                "nome": "Cliente Edicao",
                "usuario": "cliente-edicao-gate",
                "email": "  CLIENTE-EDICAO-LEGADO@EXAMPLE.INVALID  ",
                "perfil": "cliente",
                "ativo": True,
                "cliente_id": cliente_id,
                "redefinir_senha": True,
                "nova_senha": "nova-senha-cliente",
            },
            headers=self.auth(),
        )

        self.assert_status(response, 200)
        with self.app.app_context():
            usuario = self.db.session.get(self.UsuarioSistema, usuario_id)
            cliente_usuario = self.db.session.get(
                self.ClienteUsuario,
                cliente_usuario_id,
            )
            usuario_duplicado = self.UsuarioSistema.query.filter_by(
                usuario="cliente-duplicado-legado-gate"
            ).first()
            self.assertTrue(verificar_senha(
                usuario.senha,
                "nova-senha-cliente",
            ))
            self.assertEqual(cliente_usuario.senha, usuario.senha)
            self.assertEqual(usuario.email, email)
            self.assertEqual(usuario_duplicado.senha, senha_duplicado)

    def test_admin_usuario_redefine_senha_cliente_sem_recriar_vinculo(self):
        from utils.senhas import gerar_hash_senha, verificar_senha

        email = "cliente-sem-vinculo@example.invalid"

        with self.app.app_context():
            usuario = self.UsuarioSistema(
                nome="Cliente Sem Vinculo",
                usuario="cliente-sem-vinculo-gate",
                email=email,
                senha=gerar_hash_senha("senha-anterior-sem-vinculo"),
                perfil="cliente",
                ativo=True,
            )
            usuario_duplicado = self.UsuarioSistema(
                nome="Duplicado Sem Vinculo",
                usuario="duplicado-sem-vinculo-gate",
                email=email,
                senha=gerar_hash_senha("senha-duplicado-sem-vinculo"),
                perfil="cliente",
                ativo=True,
            )
            self.db.session.add_all([usuario, usuario_duplicado])
            self.db.session.commit()
            usuario_id = usuario.id

        response = self.client.put(
            f"/api/admin/usuarios/{usuario_id}",
            json={
                "redefinir_senha": True,
                "nova_senha": "nova-senha-sem-vinculo",
            },
            headers=self.auth(),
        )

        self.assert_status(response, 200)
        with self.app.app_context():
            usuario = self.db.session.get(self.UsuarioSistema, usuario_id)
            cliente_usuario = self.ClienteUsuario.query.filter_by(
                usuario_sistema_id=usuario_id
            ).first()
            self.assertTrue(verificar_senha(
                usuario.senha,
                "nova-senha-sem-vinculo",
            ))
            self.assertIsNone(cliente_usuario)

    def test_admin_usuario_redefine_senha_motorista_com_email_legado_duplicado(self):
        from utils.senhas import gerar_hash_senha, verificar_senha

        email = "motorista-edicao-legado@example.invalid"

        with self.app.app_context():
            usuario = self.UsuarioSistema(
                nome="Motorista Edicao",
                usuario="motorista-edicao-gate",
                email=email,
                senha=gerar_hash_senha("senha-anterior-motorista"),
                perfil="motorista",
                ativo=True,
            )
            usuario_duplicado = self.UsuarioSistema(
                nome="Motorista Duplicado Legado",
                usuario="motorista-duplicado-legado-gate",
                email=email,
                senha=gerar_hash_senha("senha-duplicado-motorista"),
                perfil="motorista",
                ativo=True,
            )
            self.db.session.add_all([usuario, usuario_duplicado])
            self.db.session.flush()
            motorista = self.Motorista(
                nome=usuario.nome,
                usuario=usuario.usuario,
                email=email,
                senha=usuario.senha,
                usuario_sistema_id=usuario.id,
                status="Ativo",
            )
            self.db.session.add(motorista)
            self.db.session.commit()
            usuario_id = usuario.id
            motorista_id = motorista.id

        response = self.client.put(
            f"/api/admin/usuarios/{usuario_id}",
            json={
                "redefinir_senha": True,
                "nova_senha": "nova-senha-motorista",
            },
            headers=self.auth(),
        )

        self.assert_status(response, 200)
        with self.app.app_context():
            usuario = self.db.session.get(self.UsuarioSistema, usuario_id)
            motorista = self.db.session.get(self.Motorista, motorista_id)
            self.assertTrue(verificar_senha(
                usuario.senha,
                "nova-senha-motorista",
            ))
            self.assertEqual(motorista.senha, usuario.senha)

    def test_admin_usuario_mantem_conflitos_reais_de_email_e_usuario(self):
        from utils.senhas import gerar_hash_senha

        with self.app.app_context():
            usuario = self.UsuarioSistema(
                nome="Usuario Conflitos",
                usuario="usuario-conflitos-gate",
                email="usuario-conflitos@example.invalid",
                senha=gerar_hash_senha("senha-conflitos"),
                perfil="operador",
                ativo=True,
            )
            existente = self.UsuarioSistema(
                nome="Usuario Existente",
                usuario="usuario-existente-gate",
                email="usuario-existente@example.invalid",
                senha=gerar_hash_senha("senha-existente"),
                perfil="operador",
                ativo=True,
            )
            self.db.session.add_all([usuario, existente])
            self.db.session.commit()
            usuario_id = usuario.id

        email_response = self.client.put(
            f"/api/admin/usuarios/{usuario_id}",
            json={"email": "  USUARIO-EXISTENTE@EXAMPLE.INVALID  "},
            headers=self.auth(),
        )
        self.assert_status(email_response, 409)
        self.assertEqual(
            email_response.get_json()["erro"],
            "Este e-mail já está cadastrado no sistema.",
        )

        usuario_response = self.client.put(
            f"/api/admin/usuarios/{usuario_id}",
            json={"usuario": "usuario-existente-gate"},
            headers=self.auth(),
        )
        self.assert_status(usuario_response, 409)
        self.assertEqual(
            usuario_response.get_json()["erro"],
            "Este nome de usuário já está cadastrado.",
        )

        with self.app.app_context():
            usuario = self.db.session.get(self.UsuarioSistema, usuario_id)
            self.assertEqual(usuario.usuario, "usuario-conflitos-gate")
            self.assertEqual(
                usuario.email,
                "usuario-conflitos@example.invalid",
            )

    def test_admin_usuario_preserva_validacoes_e_normaliza_email(self):
        from utils.senhas import gerar_hash_senha

        with self.app.app_context():
            usuario = self.UsuarioSistema(
                nome="Usuario Validacoes",
                usuario="usuario-validacoes-gate",
                email="usuario-validacoes@example.invalid",
                senha=gerar_hash_senha("senha-validacoes"),
                perfil="operador",
                ativo=True,
            )
            cliente_atual = self.Cliente(
                razao_social="Cliente Atual Validacoes",
                ativo=True,
            )
            cliente_inativo = self.Cliente(
                razao_social="Cliente Inativo Validacoes",
                ativo=False,
            )
            usuario_cliente = self.UsuarioSistema(
                nome="Cliente Validacoes",
                usuario="cliente-validacoes-gate",
                email="cliente-validacoes@example.invalid",
                senha=gerar_hash_senha("senha-cliente-validacoes"),
                perfil="cliente",
                ativo=True,
            )
            self.db.session.add_all([
                usuario,
                cliente_atual,
                cliente_inativo,
                usuario_cliente,
            ])
            self.db.session.flush()
            self.db.session.add(self.ClienteUsuario(
                cliente_id=cliente_atual.id,
                usuario_sistema_id=usuario_cliente.id,
                nome=usuario_cliente.nome,
                empresa=cliente_atual.razao_social,
                email=usuario_cliente.email,
                senha=usuario_cliente.senha,
                ativo=True,
            ))
            self.db.session.commit()
            usuario_id = usuario.id
            usuario_cliente_id = usuario_cliente.id
            cliente_atual_id = cliente_atual.id
            cliente_inativo_id = cliente_inativo.id

        senha_curta = self.client.put(
            f"/api/admin/usuarios/{usuario_id}",
            json={
                "redefinir_senha": True,
                "nova_senha": "curta",
            },
            headers=self.auth(),
        )
        self.assert_status(senha_curta, 400)

        cliente_inativo = self.client.put(
            f"/api/admin/usuarios/{usuario_cliente_id}",
            json={
                "cliente_id": cliente_inativo_id,
                "redefinir_senha": True,
                "nova_senha": "nova-senha-validacoes",
            },
            headers=self.auth(),
        )
        self.assert_status(cliente_inativo, 400)

        email_normalizado = self.client.put(
            f"/api/admin/usuarios/{usuario_id}",
            json={"email": "  NOVO-EMAIL-VALIDACOES@EXAMPLE.INVALID  "},
            headers=self.auth(),
        )
        self.assert_status(email_normalizado, 200)

        with self.app.app_context():
            usuario = self.db.session.get(self.UsuarioSistema, usuario_id)
            usuario_cliente = self.db.session.get(
                self.UsuarioSistema,
                usuario_cliente_id,
            )
            self.assertEqual(
                usuario.email,
                "novo-email-validacoes@example.invalid",
            )
            self.assertEqual(
                self.ClienteUsuario.query.filter_by(
                    usuario_sistema_id=usuario_cliente_id
                ).first().cliente_id,
                cliente_atual_id,
            )
            self.assertEqual(usuario_cliente.perfil, "cliente")

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

    def test_motorista_localizacao_atualiza_rastreamento_e_timeline_cliente(self):
        with self.app.app_context():
            cliente = self.Cliente(razao_social="Cliente Localizacao Gate")
            usuario_cliente = self.UsuarioSistema(
                nome="Cliente Localizacao Gate",
                usuario="cliente-localizacao-gate",
                email="cliente-localizacao-gate@example.invalid",
                senha="hash-cliente",
                perfil="cliente",
                ativo=True,
            )
            usuario_motorista = self.UsuarioSistema(
                nome="Motorista Localizacao Gate",
                usuario="motorista-localizacao-gate",
                email="motorista-localizacao-gate@example.invalid",
                senha="hash-motorista",
                perfil="motorista",
                ativo=True,
            )
            usuario_outro_motorista = self.UsuarioSistema(
                nome="Outro Motorista Gate",
                usuario="outro-motorista-localizacao-gate",
                email="outro-motorista-localizacao-gate@example.invalid",
                senha="hash-outro",
                perfil="motorista",
                ativo=True,
            )
            self.db.session.add_all([
                cliente,
                usuario_cliente,
                usuario_motorista,
                usuario_outro_motorista,
            ])
            self.db.session.flush()
            self.db.session.add(self.ClienteUsuario(
                cliente_id=cliente.id,
                usuario_sistema_id=usuario_cliente.id,
                nome=usuario_cliente.nome,
                empresa=cliente.razao_social,
                email=usuario_cliente.email,
                senha="hash-cliente",
                ativo=True,
            ))
            motorista = self.Motorista(
                nome=usuario_motorista.nome,
                usuario_sistema_id=usuario_motorista.id,
                status="Ativo",
            )
            outro_motorista = self.Motorista(
                nome=usuario_outro_motorista.nome,
                usuario_sistema_id=usuario_outro_motorista.id,
                status="Ativo",
            )
            self.db.session.add_all([motorista, outro_motorista])
            self.db.session.flush()
            carga = self.Rastreamento(
                codigo="GATE-LOCALIZACAO",
                cliente=cliente.razao_social,
                cliente_id=cliente.id,
                status="Em trânsito",
                local_atual="São Paulo/SP - Centro de Distribuição",
                destino="Campinas/SP",
            )
            self.db.session.add(carga)
            self.db.session.flush()
            viagem = self.Viagem(
                rastreamento_id=carga.id,
                motorista_id=motorista.id,
                origem="São Paulo/SP - Centro de Distribuição",
                destino="Campinas/SP",
                status="Em andamento",
            )
            self.db.session.add(viagem)
            self.db.session.flush()
            carga.ultima_atualizacao = datetime.utcnow() - timedelta(days=1)
            self.db.session.commit()

            viagem_id = viagem.id
            carga_id = carga.id
            token_motorista = type(self).create_access_token(
                identity=str(usuario_motorista.id)
            )
            token_outro_motorista = type(self).create_access_token(
                identity=str(usuario_outro_motorista.id)
            )
            token_cliente = type(self).create_access_token(
                identity=str(usuario_cliente.id)
            )
            timestamp_anterior = carga.ultima_atualizacao

        payload = {
            "localizacao": "Jundiaí/SP",
            "observacao": "Viagem seguindo normalmente em direção a Campinas/SP.",
            # O endpoint deve ignorar qualquer tentativa do cliente de escolher carga.
            "rastreamento_id": -999,
        }
        response = self.client.post(
            f"/api/motorista/minhas-viagens/{viagem_id}/localizacoes",
            json=payload,
            headers=self.auth(token_motorista),
        )
        self.assert_status(response, 201)

        with self.app.app_context():
            carga = self.db.session.get(self.Rastreamento, carga_id)
            self.assertEqual(carga.local_atual, "Jundiaí/SP")
            self.assertEqual(carga.status, "Em trânsito")
            self.assertGreater(carga.ultima_atualizacao, timestamp_anterior)
            self.assertEqual(
                self.LocalizacaoViagem.query.filter_by(
                    viagem_id=viagem_id
                ).count(),
                1,
            )
            self.assertEqual(
                self.HistoricoViagem.query.filter_by(
                    viagem_id=viagem_id
                ).count(),
                1,
            )
            evento = self.HistoricoRastreamento.query.filter_by(
                rastreamento_id=carga_id
            ).one()
            self.assertEqual(evento.status, "Em trânsito")
            self.assertEqual(evento.local, "Jundiaí/SP")
            self.assertEqual(
                evento.observacao,
                "Viagem seguindo normalmente em direção a Campinas/SP.",
            )

        detalhe_cliente = self.client.get(
            f"/api/cliente/minhas-cargas/{carga_id}",
            headers=self.auth(token_cliente),
        )
        self.assert_status(detalhe_cliente, 200)
        dados_cliente = detalhe_cliente.get_json()
        self.assertEqual(dados_cliente["local_atual"], "Jundiaí/SP")
        self.assertEqual(dados_cliente["historico"][-1]["local"], "Jundiaí/SP")
        self.assertEqual(
            dados_cliente["historico"][-1]["observacao"],
            "Viagem seguindo normalmente em direção a Campinas/SP.",
        )

        timestamp_da_primeira_localizacao = dados_cliente["ultima_atualizacao"]
        response_repetido = self.client.post(
            f"/api/motorista/minhas-viagens/{viagem_id}/localizacoes",
            json=payload,
            headers=self.auth(token_motorista),
        )
        self.assert_status(response_repetido, 201)
        with self.app.app_context():
            self.assertEqual(
                self.LocalizacaoViagem.query.filter_by(
                    viagem_id=viagem_id
                ).count(),
                2,
            )
            self.assertEqual(
                self.HistoricoViagem.query.filter_by(
                    viagem_id=viagem_id
                ).count(),
                2,
            )
            self.assertEqual(
                self.HistoricoRastreamento.query.filter_by(
                    rastreamento_id=carga_id
                ).count(),
                1,
            )
            self.assertGreater(
                self.db.session.get(self.Rastreamento, carga_id).ultima_atualizacao,
                timestamp_anterior,
            )

        antes = self.client.get(
            f"/api/cliente/minhas-cargas/{carga_id}",
            headers=self.auth(token_cliente),
        ).get_json()
        with self.app.app_context():
            localizacoes_antes_nao_autorizada = self.LocalizacaoViagem.query.filter_by(
                viagem_id=viagem_id
            ).count()
            historicos_viagem_antes_nao_autorizada = self.HistoricoViagem.query.filter_by(
                viagem_id=viagem_id
            ).count()
        response_nao_autorizada = self.client.post(
            f"/api/motorista/minhas-viagens/{viagem_id}/localizacoes",
            json={"localizacao": "Sorocaba/SP", "observacao": "Não autorizado."},
            headers=self.auth(token_outro_motorista),
        )
        self.assert_status(response_nao_autorizada, 404)
        depois = self.client.get(
            f"/api/cliente/minhas-cargas/{carga_id}",
            headers=self.auth(token_cliente),
        ).get_json()
        self.assertEqual(depois["local_atual"], antes["local_atual"])
        self.assertEqual(depois["historico"], antes["historico"])
        self.assertEqual(
            depois["ultima_atualizacao"],
            timestamp_da_primeira_localizacao,
        )
        with self.app.app_context():
            self.assertEqual(
                self.LocalizacaoViagem.query.filter_by(
                    viagem_id=viagem_id
                ).count(),
                localizacoes_antes_nao_autorizada,
            )
            self.assertEqual(
                self.HistoricoViagem.query.filter_by(
                    viagem_id=viagem_id
                ).count(),
                historicos_viagem_antes_nao_autorizada,
            )

    def test_portal_motorista_formata_data_upload_utc_e_preserva_isolamento(self):
        instante_upload_utc_naive = datetime(2026, 11, 1, 14, 3)
        with self.app.app_context():
            usuario_motorista = self.UsuarioSistema(
                nome="Motorista Comprovante UTC",
                usuario="motorista-comprovante-utc",
                email="motorista-comprovante-utc@example.invalid",
                senha="hash-motorista",
                perfil="motorista",
                ativo=True,
            )
            usuario_outro = self.UsuarioSistema(
                nome="Outro Motorista Comprovante UTC",
                usuario="outro-motorista-comprovante-utc",
                email="outro-motorista-comprovante-utc@example.invalid",
                senha="hash-outro",
                perfil="motorista",
                ativo=True,
            )
            self.db.session.add_all([usuario_motorista, usuario_outro])
            self.db.session.flush()
            motorista = self.Motorista(
                nome=usuario_motorista.nome,
                usuario_sistema_id=usuario_motorista.id,
                status="Ativo",
            )
            outro_motorista = self.Motorista(
                nome=usuario_outro.nome,
                usuario_sistema_id=usuario_outro.id,
                status="Ativo",
            )
            self.db.session.add_all([motorista, outro_motorista])
            self.db.session.flush()
            carga = self.Rastreamento(
                codigo="GATE-COMPROVANTE-UTC",
                cliente="Cliente Comprovante UTC",
                status="Em trânsito",
                local_atual="São Paulo/SP",
                destino="Campinas/SP",
            )
            self.db.session.add(carga)
            self.db.session.flush()
            viagem = self.Viagem(
                rastreamento_id=carga.id,
                motorista_id=motorista.id,
                origem="São Paulo/SP",
                destino="Campinas/SP",
                status="Em trânsito",
            )
            self.db.session.add(viagem)
            self.db.session.flush()
            arquivo = self.ArquivoComprovanteViagem(
                viagem_id=viagem.id,
                nome_arquivo="comprovante.pdf",
                data_upload=instante_upload_utc_naive,
            )
            arquivo_sem_data = self.ArquivoComprovanteViagem(
                viagem_id=viagem.id,
                nome_arquivo="comprovante-sem-data.pdf",
            )
            self.db.session.add_all([arquivo, arquivo_sem_data])
            self.db.session.flush()
            arquivo_sem_data.data_upload = None
            comprovante_entrega = self.ComprovanteEntrega(
                viagem_id=viagem.id,
                recebedor="Roberto Almeida",
                observacao="Mercadoria recebida em perfeito estado, sem avarias ou ressalvas.",
                data_entrega=datetime(2026, 11, 1, 14, 7),
            )
            self.db.session.add(comprovante_entrega)
            self.db.session.commit()
            viagem_id = viagem.id
            token_motorista = type(self).create_access_token(
                identity=str(usuario_motorista.id)
            )
            token_outro = type(self).create_access_token(
                identity=str(usuario_outro.id)
            )

        resposta = self.client.get(
            f"/api/motorista/minhas-viagens/{viagem_id}/comprovantes/arquivos",
            headers=self.auth(token_motorista),
        )
        self.assert_status(resposta, 200)
        arquivos = {item["nome_arquivo"]: item for item in resposta.get_json()}
        self.assertEqual(
            arquivos["comprovante.pdf"]["data_upload"],
            "01/11/2026 11:03",
        )
        self.assertEqual(arquivos["comprovante-sem-data.pdf"]["data_upload"], "")
        self.assertEqual(
            arquivos["comprovante.pdf"]["download_endpoint"],
            f"/api/comprovantes/arquivos/{arquivos['comprovante.pdf']['id']}/download",
        )

        resposta_comprovante = self.client.get(
            f"/api/motorista/minhas-viagens/{viagem_id}/comprovante",
            headers=self.auth(token_motorista),
        )
        self.assert_status(resposta_comprovante, 200)
        dados_comprovante = resposta_comprovante.get_json()
        self.assertEqual(dados_comprovante["recebedor"], "Roberto Almeida")
        self.assertEqual(
            dados_comprovante["observacao"],
            "Mercadoria recebida em perfeito estado, sem avarias ou ressalvas.",
        )
        self.assertEqual(dados_comprovante["data_entrega"], "01/11/2026 11:07")

        resposta_outro_motorista = self.client.get(
            f"/api/motorista/minhas-viagens/{viagem_id}/comprovantes/arquivos",
            headers=self.auth(token_outro),
        )
        self.assert_status(resposta_outro_motorista, 404)
        resposta_comprovante_nao_autorizada = self.client.get(
            f"/api/motorista/minhas-viagens/{viagem_id}/comprovante",
            headers=self.auth(token_outro),
        )
        self.assert_status(resposta_comprovante_nao_autorizada, 404)

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

    def test_campos_planejados_de_carga_e_validacao_de_peso(self):
        created = self.client.post(
            "/api/admin/cargas",
            json={
                "cliente": "Cliente Planejamento",
                "status": "Pendente",
                "local_atual": "Origem",
                "destino": "Destino",
                "descricao_carga": "Alimentos embalados",
                "peso_kg": 125.5,
                "data_prevista_saida": "2026-11-05T17:30",
                "previsao_entrega": "2026-11-06T09:15",
            },
            headers=self.auth(),
        )
        self.assert_status(created, 201)
        carga_id = created.get_json()["id"]
        detail = self.client.get(f"/api/admin/cargas/{carga_id}", headers=self.auth())
        self.assert_status(detail, 200)
        data = detail.get_json()
        listing = self.client.get("/api/admin/cargas", headers=self.auth())
        self.assert_status(listing, 200)
        listed = next(row for row in listing.get_json() if row["id"] == carga_id)
        self.assertEqual(listed["peso_kg"], 125.5)
        self.assertEqual(listed["data_prevista_saida"], "05/11/2026 17:30")
        self.assertEqual(data["descricao_carga"], "Alimentos embalados")
        self.assertEqual(data["peso_kg"], 125.5)
        self.assertEqual(data["data_prevista_saida"], "05/11/2026 17:30")
        self.assertEqual(data["data_prevista_saida_local"], "2026-11-05T17:30")
        self.assertEqual(data["previsao_entrega"], "06/11/2026 09:15")
        with self.app.app_context():
            carga = self.db.session.get(self.Rastreamento, carga_id)
            self.assertEqual(carga.data_prevista_saida, datetime(2026, 11, 5, 17, 30))
            self.assertEqual(carga.previsao_entrega, datetime(2026, 11, 6, 9, 15))

        updated = self.client.put(
            f"/api/admin/cargas/{carga_id}",
            json={"cliente": "Cliente Planejamento", "local_atual": "Origem", "destino": "Destino", "descricao_carga": "Carga atualizada", "peso_kg": "125.75", "data_prevista_saida": "2026-11-05T18:00", "previsao_entrega": "2026-11-06T10:00"},
            headers=self.auth(),
        )
        self.assert_status(updated, 200)
        detail = self.client.get(f"/api/admin/cargas/{carga_id}", headers=self.auth())
        self.assertEqual(detail.get_json()["peso_kg"], 125.75)
        self.assertEqual(detail.get_json()["data_prevista_saida"], "05/11/2026 18:00")

        negative = self.client.post(
            "/api/admin/cargas",
            json={"cliente": "Cliente Peso", "status": "Pendente", "local_atual": "A", "destino": "B", "peso_kg": -1},
            headers=self.auth(),
        )
        self.assert_status(negative, 400)

        old_payload = self.client.post(
            "/api/admin/cargas",
            json={"cliente": "Cliente Legado", "status": "Pendente", "local_atual": "A", "destino": "B"},
            headers=self.auth(),
        )
        self.assert_status(old_payload, 201)
        old_detail = self.client.get(f"/api/admin/cargas/{old_payload.get_json()['id']}", headers=self.auth())
        self.assertIsNone(old_detail.get_json()["peso_kg"])
        self.assertEqual(old_detail.get_json()["previsao_entrega"], "")

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
