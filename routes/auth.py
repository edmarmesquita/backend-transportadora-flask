from flask import Blueprint, request
from flask_jwt_extended import (
    create_access_token,
    get_jwt_identity,
    jwt_required
)

from extensions import db
from models.clientes import ClienteUsuario
from models.recursos import Motorista
from models.usuarios import UsuarioSistema
from services.auditoria import registrar_log
from utils.senhas import (
    gerar_hash_senha,
    verificar_senha,
)


auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/api/login", methods=["POST"])
def api_login():
    dados = request.get_json(silent=True) or {}

    usuario_digitado = str(
        dados.get("usuario", "")
    ).strip()

    senha_digitada = str(
        dados.get("senha", "")
    ).strip()

    if not usuario_digitado or not senha_digitada:
        return {
            "erro": "Informe o usuário e a senha."
        }, 400

    usuario = UsuarioSistema.query.filter_by(
        usuario=usuario_digitado,
        ativo=True
    ).first()

    if not usuario or not verificar_senha(
        usuario.senha,
        senha_digitada,
    ):
        return {
            "erro": "Usuário ou senha inválidos."
        }, 401

    access_token = create_access_token(
        identity=str(usuario.id),
        additional_claims={
            "nome": usuario.nome,
            "perfil": usuario.perfil,
            "usuario": usuario.usuario,
        }
    )

    registrar_log(
        "Login no sistema",
        f"Usuário {usuario.nome} acessou o painel React.",
        usuario_id=usuario.id,
        usuario_nome=usuario.nome,
        perfil=usuario.perfil
    )

    return {
        "access_token": access_token,
        "usuario": {
            "id": usuario.id,
            "nome": usuario.nome,
            "usuario": usuario.usuario,
            "perfil": usuario.perfil,
        }
    }, 200


@auth_bp.route("/api/usuarios/<int:id>/alterar-senha", methods=["POST"])
@jwt_required()
def api_alterar_senha(id):
    usuario_id = int(get_jwt_identity())

    if usuario_id != id:
        return {
            "erro": "Você só pode alterar a sua própria senha."
        }, 403

    usuario = db.session.get(
        UsuarioSistema,
        usuario_id
    )

    if not usuario or not usuario.ativo:
        return {
            "erro": "Usuário não autorizado."
        }, 401

    dados = request.get_json() or {}

    senha_atual = dados.get("senha_atual", "").strip()
    nova_senha = dados.get("nova_senha", "").strip()

    if not senha_atual or not nova_senha:
        return {
            "erro": "Informe a senha atual e a nova senha."
        }, 400

    if not verificar_senha(usuario.senha, senha_atual):
        return {
            "erro": "Senha atual incorreta."
        }, 400

    if len(nova_senha) < 6:
        return {
            "erro": "A nova senha deve ter pelo menos 6 caracteres."
        }, 400

    if verificar_senha(usuario.senha, nova_senha):
        return {
            "erro": "A nova senha deve ser diferente da senha atual."
        }, 400

    nova_senha_hash = gerar_hash_senha(nova_senha)

    usuario.senha = nova_senha_hash

    cliente_usuario = ClienteUsuario.query.filter_by(
        usuario_sistema_id=usuario.id
    ).first()

    if cliente_usuario:
        cliente_usuario.senha = nova_senha_hash

    motorista = Motorista.query.filter_by(
        usuario_sistema_id=usuario.id
    ).first()

    if motorista:
        motorista.senha = nova_senha_hash

    db.session.commit()

    return {
        "mensagem": "Senha alterada com sucesso!"
    }, 200
