from datetime import datetime

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from extensions import db
from models.clientes import Cliente
from models.cotacoes import Carga, Cotacao
from models.operacao import Rastreamento
from models.usuarios import UsuarioSistema
from services.codigos_rastreamento import gerar_codigo_rastreamento


admin_cotacoes_bp = Blueprint(
    "admin_cotacoes",
    __name__
)


@admin_cotacoes_bp.route(
    "/api/admin/cotacoes/<int:id>/aprovar",
    methods=["POST"]
)
@jwt_required()
def aprovar_cotacao(id):
    usuario_id = int(get_jwt_identity())
    usuario = db.session.get(UsuarioSistema, usuario_id)

    if not usuario or not usuario.ativo:
        return jsonify({"erro": "Usuário não autorizado."}), 401

    if str(usuario.perfil).strip().lower() not in [
        "administrador", "operador"
    ]:
        return jsonify({
            "erro": "Você não possui permissão para aprovar cotações."
        }), 403

    cotacao = db.session.get(Cotacao, id)

    if not cotacao:
        return jsonify({
            "erro": "Cotação não encontrada."
        }), 404

    carga_existente = Carga.query.filter_by(
        cotacao_id=cotacao.id
    ).first()

    if carga_existente:
        return jsonify({
            "erro": "Esta cotação já foi aprovada."
        }), 400

    dados = request.get_json(silent=True) or {}
    cliente_id = dados.get("cliente_id")

    if cliente_id is None:
        return jsonify({
            "erro": "Informe o cliente comercial."
        }), 400

    if isinstance(cliente_id, bool) or not isinstance(cliente_id, int):
        return jsonify({
            "erro": "cliente_id deve ser um número inteiro."
        }), 400

    cliente_selecionado = db.session.get(Cliente, cliente_id)

    if not cliente_selecionado:
        return jsonify({
            "erro": "Cliente não encontrado."
        }), 404

    if not cliente_selecionado.ativo:
        return jsonify({
            "erro": "Não é possível aprovar para um cliente inativo."
        }), 409

    cliente_textual = (
        cliente_selecionado.nome_fantasia
        or cliente_selecionado.razao_social
    )

    try:
        carga = Carga(
            cotacao_id=cotacao.id,
            cliente=cliente_textual,
            whatsapp=cotacao.whatsapp,
            origem=cotacao.origem,
            destino=cotacao.destino,
            tipo_carga=cotacao.tipo_carga,
            observacoes=cotacao.observacoes
        )

        db.session.add(carga)
        db.session.flush()

        rastreamento = Rastreamento(
            codigo=gerar_codigo_rastreamento(),
            cliente=cliente_textual,
            cliente_id=cliente_selecionado.id,
            status="Pendente",
            local_atual=cotacao.origem,
            destino=cotacao.destino,
            ultima_atualizacao=datetime.utcnow()
        )

        db.session.add(rastreamento)
        db.session.flush()

        db.session.commit()

        return jsonify({
            "mensagem": (
                "Cotação aprovada e carga criada "
                "com sucesso!"
            ),
            "cotacao_id": cotacao.id,
            "carga_id": carga.id,
            "rastreamento_id": rastreamento.id,
            "codigo_carga": rastreamento.codigo
        }), 201

    except Exception as erro:
        db.session.rollback()

        print(
            "ERRO AO APROVAR COTAÇÃO:",
            erro
        )

        return jsonify({
            "erro": "Não foi possível aprovar a cotação."
        }), 500


@admin_cotacoes_bp.route("/api/admin/cotacoes", methods=["POST"])
@jwt_required()
def api_criar_cotacao_admin():
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
            "erro": "Você não possui permissão para cadastrar cotações."
        }), 403

    dados = request.get_json(silent=True) or {}

    cliente = str(
        dados.get("cliente", "")
    ).strip()

    whatsapp = str(
        dados.get("whatsapp", "")
    ).strip()

    origem = str(
        dados.get("origem", "")
    ).strip()

    destino = str(
        dados.get("destino", "")
    ).strip()

    tipo_carga = str(
        dados.get("tipo_carga", "")
    ).strip()

    observacoes = str(
        dados.get("observacoes", "")
    ).strip()

    if not cliente:
        return jsonify({
            "erro": "Informe o cliente."
        }), 400

    if not whatsapp:
        return jsonify({
            "erro": "Informe o WhatsApp."
        }), 400

    if not origem:
        return jsonify({
            "erro": "Informe a origem."
        }), 400

    if not destino:
        return jsonify({
            "erro": "Informe o destino."
        }), 400

    if not tipo_carga:
        return jsonify({
            "erro": "Informe o tipo da carga."
        }), 400

    try:
        cotacao = Cotacao(
            cliente=cliente,
            whatsapp=whatsapp,
            origem=origem,
            destino=destino,
            tipo_carga=tipo_carga,
            observacoes=observacoes
        )

        db.session.add(cotacao)
        db.session.commit()

        return jsonify({
            "mensagem": "Cotação cadastrada com sucesso!",
            "cotacao": {
                "id": cotacao.id,
                "cliente": cotacao.cliente,
                "whatsapp": cotacao.whatsapp,
                "origem": cotacao.origem,
                "destino": cotacao.destino,
                "tipo_carga": cotacao.tipo_carga,
                "observacoes": cotacao.observacoes
            }
        }), 201

    except Exception as erro:
        db.session.rollback()

        print("ERRO AO CADASTRAR COTAÇÃO:", erro)

        return jsonify({
            "erro": "Não foi possível cadastrar a cotação."
        }), 500


@admin_cotacoes_bp.route(
    "/api/admin/cotacoes",
    methods=["GET"]
)
@jwt_required()
def api_admin_cotacoes():
    usuario_id = int(get_jwt_identity())
    usuario = db.session.get(UsuarioSistema, usuario_id)

    if not usuario or not usuario.ativo:
        return jsonify({"erro": "Usuário não autorizado."}), 401

    if str(usuario.perfil).strip().lower() not in [
        "administrador", "operador"
    ]:
        return jsonify({
            "erro": "Você não possui permissão para consultar cotações."
        }), 403

    cotacoes = (
        Cotacao.query
        .outerjoin(
            Carga,
            Carga.cotacao_id == Cotacao.id
        )
        .filter(
            Carga.id.is_(None)
        )
        .order_by(
            Cotacao.data_criacao.desc()
        )
        .all()
    )

    lista = []

    for cotacao in cotacoes:
        lista.append({
            "id": cotacao.id,
            "cliente": cotacao.cliente,
            "whatsapp": cotacao.whatsapp,
            "origem": cotacao.origem,
            "destino": cotacao.destino,
            "tipo_carga": cotacao.tipo_carga,
            "observacoes": cotacao.observacoes,
            "status": cotacao.status or "Pendente",
            "data_criacao": (
                cotacao.data_criacao.strftime(
                    "%d/%m/%Y %H:%M"
                )
                if cotacao.data_criacao
                else ""
            )
        })

    return jsonify(lista), 200
