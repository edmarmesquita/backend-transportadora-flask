from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from extensions import db
from models.clientes import Cliente
from models.operacao import Rastreamento
from models.usuarios import UsuarioSistema
from services.auditoria import registrar_log, snapshot_objeto


admin_clientes_bp = Blueprint(
    "admin_clientes",
    __name__
)


@admin_clientes_bp.route("/api/admin/clientes", methods=["GET"])
@jwt_required()
def api_admin_clientes():
    usuario_id = int(get_jwt_identity())

    usuario = db.session.get(
        UsuarioSistema,
        usuario_id
    )

    if not usuario or not usuario.ativo:
        return jsonify({
            "erro": "Usuário não autorizado."
        }), 401

    if str(usuario.perfil).strip().lower() not in [
        "administrador",
        "operador"
    ]:
        return jsonify({
            "erro": "Você não possui permissão para acessar clientes."
        }), 403

    clientes = Cliente.query.order_by(
        Cliente.data_criacao.desc()
    ).all()

    lista = []

    for cliente in clientes:
        lista.append({
            "id": cliente.id,
            "razao_social": cliente.razao_social,
            "nome_fantasia": cliente.nome_fantasia,
            "documento": cliente.documento,
            "responsavel": cliente.responsavel,
            "email": cliente.email,
            "telefone": cliente.telefone,
            "cidade": cliente.cidade,
            "estado": cliente.estado,
            "ativo": cliente.ativo
        })

    return jsonify(lista), 200


@admin_clientes_bp.route("/api/admin/clientes", methods=["POST"])
@jwt_required()
def api_criar_cliente():
    usuario_id = int(get_jwt_identity())

    usuario = db.session.get(
        UsuarioSistema,
        usuario_id
    )

    if not usuario or not usuario.ativo:
        return jsonify({
            "erro": "Usuário não autorizado."
        }), 401

    if str(usuario.perfil).strip().lower() not in [
        "administrador",
        "operador"
    ]:
        return jsonify({
            "erro": "Você não possui permissão para criar clientes."
        }), 403

    dados = request.get_json()

    novo_cliente = Cliente(
        razao_social=dados.get("razao_social"),
        nome_fantasia=dados.get("nome_fantasia"),
        documento=dados.get("documento"),
        responsavel=dados.get("responsavel"),
        email=dados.get("email"),
        telefone=dados.get("telefone"),
        cidade=dados.get("cidade"),
        estado=dados.get("estado"),
        ativo=True
    )

    db.session.add(novo_cliente)
    db.session.flush()
    registrar_log(
        acao="Criação de cliente",
        detalhes=f"Cliente {novo_cliente.razao_social} criado.",
        modulo="Clientes",
        entidade="Cliente",
        entidade_id=novo_cliente.id,
        depois=snapshot_objeto(novo_cliente, [
            "razao_social", "nome_fantasia", "documento", "responsavel",
            "email", "telefone", "cidade", "estado", "ativo"
        ]),
        usuario_id=usuario.id,
        usuario_nome=usuario.nome,
        perfil=usuario.perfil
    )
    db.session.commit()

    return {
        "mensagem": "Cliente criado com sucesso!"
    }, 201


@admin_clientes_bp.route("/api/admin/clientes/top-cargas", methods=["GET"])
@jwt_required()
def api_top_clientes_cargas():
    usuario_id = int(get_jwt_identity())

    usuario = db.session.get(
        UsuarioSistema,
        usuario_id
    )

    if not usuario or not usuario.ativo:
        return jsonify({
            "erro": "Usuário não autorizado."
        }), 401

    if str(usuario.perfil).strip().lower() not in [
        "administrador",
        "operador"
    ]:
        return jsonify({
            "erro": "Você não possui permissão para acessar indicadores de clientes."
        }), 403

    resultados = db.session.query(
        Rastreamento.cliente,
        db.func.count(Rastreamento.id)
    ).group_by(
        Rastreamento.cliente
    ).order_by(
        db.func.count(Rastreamento.id).desc()
    ).limit(5).all()

    lista = []

    for cliente, total in resultados:
        lista.append({
            "cliente": cliente,
            "total": total
        })

    return lista  


@admin_clientes_bp.route("/api/admin/clientes/<int:id>/inativar", methods=["PUT"])
@jwt_required()
def api_inativar_cliente(id):
    usuario_id = int(get_jwt_identity())

    usuario = db.session.get(
        UsuarioSistema,
        usuario_id
    )

    if not usuario or not usuario.ativo:
        return jsonify({
            "erro": "Usuário não autorizado."
        }), 401

    if str(usuario.perfil).strip().lower() != "administrador":
        return jsonify({
            "erro": "Somente administradores podem inativar clientes."
        }), 403

    cliente = Cliente.query.get_or_404(id)
    antes = {"ativo": cliente.ativo}

    cliente.ativo = False

    registrar_log(
        acao="Inativação de cliente",
        detalhes=f"Cliente {cliente.razao_social} inativado.",
        modulo="Clientes",
        entidade="Cliente",
        entidade_id=cliente.id,
        antes=antes,
        depois={"ativo": cliente.ativo},
        usuario_id=usuario.id,
        usuario_nome=usuario.nome,
        perfil=usuario.perfil
    )
    db.session.commit()

    return {"mensagem": "Cliente inativado com sucesso!"}


@admin_clientes_bp.route("/api/admin/clientes/<int:id>", methods=["GET"])
@jwt_required()
def api_detalhe_cliente(id):
    usuario_id = int(get_jwt_identity())

    usuario = db.session.get(
        UsuarioSistema,
        usuario_id
    )

    if not usuario or not usuario.ativo:
        return jsonify({
            "erro": "Usuário não autorizado."
        }), 401

    if str(usuario.perfil).strip().lower() not in [
        "administrador",
        "operador"
    ]:
        return jsonify({
            "erro": "Você não possui permissão para consultar clientes."
        }), 403

    cliente = Cliente.query.get_or_404(id)

    return {
        "id": cliente.id,
        "razao_social": cliente.razao_social,
        "nome_fantasia": cliente.nome_fantasia,
        "documento": cliente.documento,
        "responsavel": cliente.responsavel,
         "email": cliente.email,
        "telefone": cliente.telefone,
        "cidade": cliente.cidade,
        "estado": cliente.estado,
        "ativo": cliente.ativo,
    }


@admin_clientes_bp.route("/api/admin/clientes/<int:id>", methods=["PUT"])
@jwt_required()
def api_editar_cliente(id):
    usuario_id = int(get_jwt_identity())

    usuario = db.session.get(
        UsuarioSistema,
        usuario_id
    )

    if not usuario or not usuario.ativo:
        return jsonify({
            "erro": "Usuário não autorizado."
        }), 401

    perfil_usuario = str(usuario.perfil).strip().lower()

    if perfil_usuario not in [
        "administrador",
        "operador"
    ]:
        return jsonify({
            "erro": "Você não possui permissão para editar clientes."
        }), 403

    cliente = Cliente.query.get_or_404(id)
    antes = snapshot_objeto(cliente, [
        "razao_social", "nome_fantasia", "documento", "responsavel",
        "email", "telefone", "cidade", "estado", "ativo"
    ])
    dados = request.get_json()

    cliente.razao_social = dados.get("razao_social", cliente.razao_social)
    cliente.nome_fantasia = dados.get("nome_fantasia", cliente.nome_fantasia)
    cliente.documento = dados.get("documento", cliente.documento)
    cliente.responsavel = dados.get("responsavel", cliente.responsavel)
    cliente.email = dados.get("email", cliente.email)
    cliente.telefone = dados.get("telefone", cliente.telefone)
    cliente.cidade = dados.get("cidade", cliente.cidade)
    cliente.estado = dados.get("estado", cliente.estado)

    if perfil_usuario == "administrador":
        cliente.ativo = dados.get("ativo", cliente.ativo)

    registrar_log(
        acao="Edição de cliente",
        detalhes=f"Cliente {cliente.razao_social} atualizado.",
        modulo="Clientes",
        entidade="Cliente",
        entidade_id=cliente.id,
        antes=antes,
        depois=snapshot_objeto(cliente, [
            "razao_social", "nome_fantasia", "documento", "responsavel",
            "email", "telefone", "cidade", "estado", "ativo"
        ]),
        usuario_id=usuario.id,
        usuario_nome=usuario.nome,
        perfil=usuario.perfil
    )
    db.session.commit()

    return {"mensagem": "Cliente atualizado com sucesso!"}
