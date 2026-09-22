
from flask import Flask, jsonify, request
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.exceptions import HTTPException
from datetime import datetime
import os
import json
from config import (
    ADMIN_BOOTSTRAP_EMAIL,
    ADMIN_BOOTSTRAP_NOME,
    ADMIN_BOOTSTRAP_SENHA,
    ADMIN_BOOTSTRAP_USUARIO,
    ALLOWED_EXTENSIONS,
    APP_HOST,
    APP_PORT,
    CORS_ALLOW_HEADERS,
    CORS_METHODS,
    CORS_RESOURCES,
    FLASK_DEBUG,
    APP_ENV,
    TRUSTED_PROXY_HOPS,
    JWT_ACCESS_TOKEN_EXPIRES,
    JWT_SECRET_KEY,
    MAX_CONTENT_LENGTH,
    REDIS_RATE_LIMIT_OBRIGATORIO,
    REDIS_URL,
    SQLALCHEMY_DATABASE_URI,
    SQLALCHEMY_TRACK_MODIFICATIONS,
    USAR_COMPATIBILIDADE_SCHEMA_SQLITE,
    UPLOAD_FOLDER as upload_folder,
    UPLOAD_MAX_FILE_SIZE
)
from extensions import cors, db, jwt
from services.rate_limit import MENSAGEM_RATE_LIMIT, configurar_limiter
from utils.senhas import gerar_hash_senha

app = Flask(
    __name__,
    static_folder=None
)

app.config["JWT_SECRET_KEY"] = JWT_SECRET_KEY
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = JWT_ACCESS_TOKEN_EXPIRES
app.config["UPLOAD_FOLDER"] = upload_folder
app.config["ALLOWED_EXTENSIONS"] = ALLOWED_EXTENSIONS
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH
app.config["UPLOAD_MAX_FILE_SIZE"] = UPLOAD_MAX_FILE_SIZE
app.config["SQLALCHEMY_DATABASE_URI"] = SQLALCHEMY_DATABASE_URI
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = SQLALCHEMY_TRACK_MODIFICATIONS

configurar_limiter(
    redis_url=REDIS_URL,
    redis_obrigatorio=REDIS_RATE_LIMIT_OBRIGATORIO,
)

if TRUSTED_PROXY_HOPS:
    app.wsgi_app = ProxyFix(
        app.wsgi_app,
        x_for=TRUSTED_PROXY_HOPS,
        x_proto=TRUSTED_PROXY_HOPS,
        x_host=TRUSTED_PROXY_HOPS,
        x_port=TRUSTED_PROXY_HOPS,
        x_prefix=TRUSTED_PROXY_HOPS
    )

try:
    os.makedirs(upload_folder, exist_ok=True)
except OSError as erro:
    raise RuntimeError(
        "Não foi possível criar ou acessar UPLOAD_FOLDER."
    ) from erro

db.init_app(app)
jwt.init_app(app)
cors.init_app(
    app,
    resources=CORS_RESOURCES,
    allow_headers=CORS_ALLOW_HEADERS,
    methods=CORS_METHODS
)


@app.after_request
def adicionar_headers_seguranca(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = (
        "camera=(), microphone=(), geolocation=()"
    )

    if APP_ENV in {"staging", "production"}:
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000"
        )

    return response


def verificar_conexao_banco():
    with db.engine.connect() as conexao:
        return conexao.execute(text("SELECT 1")).scalar_one() == 1


@app.get("/health")
def health():
    try:
        banco_disponivel = verificar_conexao_banco()
    except SQLAlchemyError:
        app.logger.exception(
            "Health check detectou indisponibilidade do banco."
        )
        banco_disponivel = False

    if not banco_disponivel:
        return jsonify({
            "status": "degraded",
            "service": "transportadora-backend",
        }), 503

    return jsonify({
        "status": "ok",
        "service": "transportadora-backend",
    }), 200


MENSAGEM_JWT_INVALIDO = "Autenticação inválida."


@jwt.unauthorized_loader
def jwt_sem_token(_erro):
    return jsonify({"erro": MENSAGEM_JWT_INVALIDO}), 401


@jwt.invalid_token_loader
def jwt_invalido(_erro):
    return jsonify({"erro": MENSAGEM_JWT_INVALIDO}), 401


@jwt.expired_token_loader
def jwt_expirado(_cabecalho, _payload):
    return jsonify({"erro": MENSAGEM_JWT_INVALIDO}), 401


@jwt.revoked_token_loader
def jwt_revogado(_cabecalho, _payload):
    return jsonify({"erro": MENSAGEM_JWT_INVALIDO}), 401


@jwt.needs_fresh_token_loader
def jwt_fresco_necessario(_cabecalho, _payload):
    return jsonify({"erro": MENSAGEM_JWT_INVALIDO}), 401


@app.errorhandler(Exception)
def erro_interno_api(erro):
    if isinstance(erro, HTTPException):
        return erro

    if request.path.startswith("/api/"):
        current_app_logger = app.logger
        current_app_logger.exception("Erro interno em endpoint da API.")
        return jsonify({
            "erro": "Erro interno do servidor."
        }), 500

    raise erro


@app.errorhandler(404)
def recurso_nao_encontrado(erro):
    if request.path.startswith("/api/"):
        return jsonify({"erro": "Recurso não encontrado."}), 404

    return erro


@app.errorhandler(413)
def arquivo_muito_grande(_erro):
    return {
        "erro": "Arquivo excede o limite máximo permitido de 10 MB."
    }, 413


@app.errorhandler(429)
def muitas_tentativas(_erro):
    return {
        "erro": MENSAGEM_RATE_LIMIT
    }, 429, {"Retry-After": "60"}

from models.usuarios import UsuarioSistema
from models.auditoria import LogAcao
from models.recursos import Motorista, Veiculo
from models.rotas import Rota

motorista_id = db.Column(
    db.Integer,
    db.ForeignKey("motorista.id"),
    nullable=True
)

motorista = db.relationship(
    "Motorista",
    backref="cargas"
)

data_criacao = db.Column(
    db.DateTime,
    default=datetime.utcnow
)
    
    

from models.operacao import Rastreamento, Viagem

from models.historicos import (
    HistoricoOperacao,
    HistoricoRastreamento,
    HistoricoViagem
)
from models.ocorrencias import OcorrenciaEntrega, OcorrenciaViagem
from models.comprovantes import ComprovanteEntrega, ArquivoComprovanteViagem
from models.localizacoes import LocalizacaoMotorista, LocalizacaoViagem
from services.compatibilidade_schema import (
    adicionar_colunas_auditoria,
    adicionar_colunas_operacionais
)
from routes.public import public_bp
from routes.auth import auth_bp
from routes.admin_clientes import admin_clientes_bp
from routes.admin_veiculos import admin_veiculos_bp
from routes.admin_motoristas import admin_motoristas_bp
from routes.admin_usuarios import admin_usuarios_bp
from routes.admin_dashboard import admin_dashboard_bp
from routes.admin_relatorios import admin_relatorios_bp
from routes.admin_cotacoes import admin_cotacoes_bp
from routes.portal_cliente import portal_cliente_bp
from routes.portal_motorista import portal_motorista_bp
from routes.admin_cargas import admin_cargas_bp
from routes.admin_viagens import admin_viagens_bp
from routes.comprovantes import comprovantes_bp

app.register_blueprint(public_bp)
app.register_blueprint(auth_bp)
app.register_blueprint(admin_clientes_bp)
app.register_blueprint(admin_veiculos_bp)
app.register_blueprint(admin_motoristas_bp)
app.register_blueprint(admin_usuarios_bp)
app.register_blueprint(admin_dashboard_bp)
app.register_blueprint(admin_relatorios_bp)
app.register_blueprint(admin_cotacoes_bp)
app.register_blueprint(portal_cliente_bp)
app.register_blueprint(portal_motorista_bp)
app.register_blueprint(admin_cargas_bp)
app.register_blueprint(admin_viagens_bp)
app.register_blueprint(comprovantes_bp)

with app.app_context():
    db.create_all()

    if USAR_COMPATIBILIDADE_SCHEMA_SQLITE:
        adicionar_colunas_operacionais()
        adicionar_colunas_auditoria()

    admin_padrao = UsuarioSistema.query.filter_by(
        perfil="administrador",
        ativo=True
    ).first()

    if not admin_padrao:
        configuracao_admin = {
            "ADMIN_BOOTSTRAP_NOME": ADMIN_BOOTSTRAP_NOME,
            "ADMIN_BOOTSTRAP_USUARIO": ADMIN_BOOTSTRAP_USUARIO,
            "ADMIN_BOOTSTRAP_EMAIL": ADMIN_BOOTSTRAP_EMAIL,
            "ADMIN_BOOTSTRAP_SENHA": ADMIN_BOOTSTRAP_SENHA,
        }
        variaveis_ausentes = [
            nome
            for nome, valor in configuracao_admin.items()
            if not valor
        ]

        if variaveis_ausentes:
            raise RuntimeError(
                "Banco sem administrador ativo. Configure as "
                "variáveis ADMIN_BOOTSTRAP_* para criar o "
                "administrador inicial."
            )

        if len(ADMIN_BOOTSTRAP_SENHA) < 6:
            raise RuntimeError(
                "ADMIN_BOOTSTRAP_SENHA deve possuir pelo menos "
                "6 caracteres."
            )

        usuario_bootstrap_existente = (
            UsuarioSistema.query.filter_by(
                usuario=ADMIN_BOOTSTRAP_USUARIO
            ).first()
        )

        if usuario_bootstrap_existente:
            raise RuntimeError(
                "ADMIN_BOOTSTRAP_USUARIO já está em uso."
            )

        admin_padrao = UsuarioSistema(
            nome=ADMIN_BOOTSTRAP_NOME,
            usuario=ADMIN_BOOTSTRAP_USUARIO,
            email=ADMIN_BOOTSTRAP_EMAIL,
            senha=gerar_hash_senha(
                ADMIN_BOOTSTRAP_SENHA
            ),
            perfil="administrador",
            ativo=True
        )

        db.session.add(admin_padrao)
        db.session.commit()










    
        
    


    

    














        
    
    
    
    

    
        

    
    
if __name__ == "__main__":
    app.run(
        host=APP_HOST,
        port=APP_PORT,
        debug=FLASK_DEBUG
    )
