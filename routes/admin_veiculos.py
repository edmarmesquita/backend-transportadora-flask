from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from extensions import db
from services.recursos import (
    veiculo_possui_outra_carga_ativa,
    veiculo_possui_outra_viagem_ativa,
)
from models.recursos import Veiculo
from models.usuarios import UsuarioSistema
from services.auditoria import registrar_log, snapshot_objeto


admin_veiculos_bp = Blueprint(
    "admin_veiculos",
    __name__
)


@admin_veiculos_bp.route("/api/admin/veiculos", methods=["GET"])
@jwt_required()
def api_admin_veiculos():
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
            "erro": "Você não possui permissão para acessar veículos."
        }), 403

    veiculos = Veiculo.query.order_by(
        Veiculo.data_criacao.desc()
    ).all()

    lista = []

    for veiculo in veiculos:
        lista.append({
            "id": veiculo.id,
            "placa": veiculo.placa,
            "modelo": veiculo.modelo,
            "marca": veiculo.marca,
            "tipo": veiculo.tipo,
            "ano": veiculo.ano,
            "capacidade": veiculo.capacidade,
            "status": veiculo.status
        })

    return jsonify(lista), 200


@admin_veiculos_bp.route("/api/admin/veiculos", methods=["POST"])
@jwt_required()
def api_criar_veiculo():
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
            "erro": "Você não possui permissão para criar veículos."
        }), 403

    dados = request.get_json(silent=True) or {}

    placa = str(dados.get("placa", "")).strip().upper()

    if not placa:
        return {"erro": "Informe a placa."}, 400

    status = str(dados.get("status", "Disponível")).strip()

    if (
        perfil_usuario == "operador"
        and status.lower() == "inativo"
    ):
        return jsonify({
            "erro": "Você não possui permissão para inativar veículos."
        }), 403

    veiculo = Veiculo(
        placa=placa,
        modelo=str(dados.get("modelo", "")).strip(),
        marca=str(dados.get("marca", "")).strip(),
        tipo=str(dados.get("tipo", "")).strip(),
        ano=str(dados.get("ano", "")).strip(),
        capacidade=str(dados.get("capacidade", "")).strip(),
        status=status
    )

    db.session.add(veiculo)
    db.session.flush()
    registrar_log(
        acao="Criação de veículo",
        detalhes=f"Veículo {veiculo.placa} criado.",
        modulo="Veículos",
        entidade="Veiculo",
        entidade_id=veiculo.id,
        depois=snapshot_objeto(veiculo, [
            "placa", "modelo", "marca", "tipo", "ano", "capacidade", "status"
        ]),
        usuario_id=usuario.id,
        usuario_nome=usuario.nome,
        perfil=usuario.perfil
    )
    db.session.commit()

    return {"mensagem": "Veículo cadastrado com sucesso!"}, 201


@admin_veiculos_bp.route("/api/admin/veiculos/<int:id>/inativar", methods=["PUT"])
@jwt_required()
def api_inativar_veiculo(id):
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
            "erro": "Somente administradores podem inativar veículos."
        }), 403

    veiculo = Veiculo.query.get_or_404(id)

    if (
        veiculo_possui_outra_viagem_ativa(veiculo.id)
        or veiculo_possui_outra_carga_ativa(veiculo.id)
    ):
        return jsonify({
            "erro": (
                "Não é possível inativar este veículo enquanto "
                "houver viagem ou carga ativa."
            )
        }), 409

    antes = {"status": veiculo.status}
    veiculo.status = "Inativo"

    registrar_log(
        acao="Inativação de veículo",
        detalhes=f"Veículo {veiculo.placa} inativado.",
        modulo="Veículos",
        entidade="Veiculo",
        entidade_id=veiculo.id,
        antes=antes,
        depois={"status": veiculo.status},
        usuario_id=usuario.id,
        usuario_nome=usuario.nome,
        perfil=usuario.perfil
    )

    db.session.commit()

    return {"mensagem": "Veículo inativado com sucesso!"}


@admin_veiculos_bp.route("/api/admin/veiculos/<int:id>", methods=["GET"])
@jwt_required()
def api_detalhe_veiculo(id):
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
            "erro": "Você não possui permissão para consultar veículos."
        }), 403

    veiculo = Veiculo.query.get_or_404(id)

    return {
        "id": veiculo.id,
        "placa": veiculo.placa,
        "modelo": veiculo.modelo,
        "marca": veiculo.marca,
        "tipo": veiculo.tipo,
        "ano": veiculo.ano,
        "capacidade": veiculo.capacidade,
        "status": veiculo.status
    }


@admin_veiculos_bp.route("/api/admin/veiculos/<int:id>", methods=["PUT"])
@jwt_required()
def api_editar_veiculo(id):
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
            "erro": "Você não possui permissão para editar veículos."
        }), 403

    veiculo = Veiculo.query.get_or_404(id)
    antes = snapshot_objeto(veiculo, [
        "placa", "modelo", "marca", "tipo", "ano", "capacidade", "status"
    ])
    dados = request.get_json()

    status_atual = str(veiculo.status or "").strip()
    novo_status = str(
        dados.get("status", veiculo.status) or ""
    ).strip()

    if (
        perfil_usuario == "operador"
        and novo_status.lower() != status_atual.lower()
        and (
            novo_status.lower() == "inativo"
            or status_atual.lower() == "inativo"
        )
    ):
        return jsonify({
            "erro": (
                "Você não possui permissão para ativar "
                "ou inativar veículos."
            )
        }), 403


    if novo_status.lower() == "inativo" and (
        veiculo_possui_outra_viagem_ativa(veiculo.id)
        or veiculo_possui_outra_carga_ativa(veiculo.id)
    ):
        return jsonify({
            "erro": (
                "Não é possível inativar este veículo enquanto "
                "houver viagem ou carga ativa."
            )
        }), 409

    veiculo.placa = dados.get("placa", veiculo.placa)
    veiculo.modelo = dados.get("modelo", veiculo.modelo)
    veiculo.marca = dados.get("marca", veiculo.marca)
    veiculo.tipo = dados.get("tipo", veiculo.tipo)
    veiculo.ano = dados.get("ano", veiculo.ano)
    veiculo.capacidade = dados.get("capacidade", veiculo.capacidade)
    veiculo.status = novo_status

    registrar_log(
        acao="Edição de veículo",
        detalhes=f"Veículo {veiculo.placa} atualizado.",
        modulo="Veículos",
        entidade="Veiculo",
        entidade_id=veiculo.id,
        antes=antes,
        depois=snapshot_objeto(veiculo, [
            "placa", "modelo", "marca", "tipo", "ano", "capacidade", "status"
        ]),
        usuario_id=usuario.id,
        usuario_nome=usuario.nome,
        perfil=usuario.perfil
    )

    db.session.commit()

    return {"mensagem": "Veículo atualizado com sucesso!"}
