from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from extensions import db
from utils.constantes import (
    STATUS_CARGA_ATIVOS_RECURSOS,
    STATUS_VIAGEM_ATIVOS_RECURSOS,
)
from models.operacao import Rastreamento, Viagem
from models.recursos import Motorista
from models.usuarios import UsuarioSistema
from services.auditoria import registrar_log, snapshot_objeto
from utils.senhas import gerar_hash_senha


admin_motoristas_bp = Blueprint(
    "admin_motoristas",
    __name__
)


@admin_motoristas_bp.route("/api/admin/motoristas", methods=["GET"])
@jwt_required()
def api_admin_motoristas():
    usuario_id = int(get_jwt_identity())

    usuario = UsuarioSistema.query.get(usuario_id)

    if not usuario or not usuario.ativo:
        return jsonify({
            "erro": "Usuário não autorizado."
        }), 401

    if str(usuario.perfil).strip().lower() not in [
        "administrador",
        "operador"
    ]:
        return jsonify({
            "erro": (
                "Você não possui permissão "
                "para acessar motoristas."
            )
        }), 403

    motoristas = Motorista.query.order_by(
        Motorista.data_criacao.desc()
    ).all()

    return jsonify([
        {
            "id": motorista.id,
            "nome": motorista.nome,
            "cpf": motorista.cpf or "",
            "cnh": motorista.cnh or "",
            "categoria_cnh": (
                motorista.categoria_cnh or ""
            ),
            "validade_cnh": (
                motorista.validade_cnh or ""
            ),
            "telefone": motorista.telefone or "",
            "email": motorista.email or "",
            "status": motorista.status or "Ativo",
            "disponibilidade": (
                motorista.disponibilidade
                or "Disponível"
            )
        }
        for motorista in motoristas
    ]), 200


@admin_motoristas_bp.route("/api/admin/motoristas", methods=["POST"])
@jwt_required()
def api_criar_motorista():
    usuario_id = int(get_jwt_identity())

    usuario_autenticado = db.session.get(
        UsuarioSistema,
        usuario_id
    )

    if not usuario_autenticado or not usuario_autenticado.ativo:
        return jsonify({
            "erro": "Usuário não autorizado."
        }), 401

    perfil_usuario = str(
        usuario_autenticado.perfil
    ).strip().lower()

    if perfil_usuario not in [
        "administrador",
        "operador"
    ]:
        return jsonify({
            "erro": "Você não possui permissão para criar motoristas."
        }), 403

    dados = request.get_json(silent=True) or {}

    nome = str(dados.get("nome", "")).strip()
    usuario = str(dados.get("usuario", "")).strip()
    email = str(dados.get("email", "")).strip()
    senha = str(dados.get("senha", "")).strip()

    if not nome:
        return {"erro": "Informe o nome do motorista."}, 400

    if not usuario:
        return {"erro": "Informe o usuário do motorista."}, 400

    if UsuarioSistema.query.filter_by(usuario=usuario).first():
        return {
            "erro": "Já existe um usuário com este nome de acesso."
        }, 409

    status_inicial = str(
        dados.get("status", "Ativo")
    ).strip()

    if perfil_usuario == "operador":
        status_inicial = "Ativo"

    senha_hash = gerar_hash_senha(senha)

    motorista = Motorista(
        nome=nome,
        cpf=str(dados.get("cpf", "")).strip(),
        cnh=str(dados.get("cnh", "")).strip(),
        categoria_cnh=str(
            dados.get("categoria_cnh", "")
        ).strip(),
        validade_cnh=str(
            dados.get("validade_cnh", "")
        ).strip(),
        telefone=str(dados.get("telefone", "")).strip(),
        email=email,
        usuario=usuario,
        senha=senha_hash,
        status=status_inicial,
        disponibilidade="Disponível",
        observacoes=str(
            dados.get("observacoes", "")
        ).strip()
    )

    usuario_sistema = UsuarioSistema(
        nome=nome,
        usuario=usuario,
        email=email,
        senha=senha_hash,
        perfil="motorista",
        ativo=True
    )

    try:
        motorista.usuario_sistema = usuario_sistema

        db.session.add(motorista)
        db.session.add(usuario_sistema)
        db.session.flush()
        registrar_log(
            acao="Criação de motorista",
            detalhes=f"Motorista {motorista.nome} criado.",
            modulo="Motoristas",
            entidade="Motorista",
            entidade_id=motorista.id,
            depois=snapshot_objeto(motorista, [
                "nome", "cpf", "cnh", "categoria_cnh", "validade_cnh",
                "telefone", "email", "usuario", "status",
                "disponibilidade", "observacoes"
            ]),
            usuario_id=usuario_autenticado.id,
            usuario_nome=usuario_autenticado.nome,
            perfil=usuario_autenticado.perfil
        )
        db.session.commit()

        return {
            "mensagem": "Motorista cadastrado com sucesso!"
        }, 201

    except Exception as erro:
        db.session.rollback()

        print("ERRO AO CADASTRAR MOTORISTA:", erro)

        return {
            "erro": "Não foi possível cadastrar o motorista."
        }, 500


@admin_motoristas_bp.route(
    "/api/admin/motoristas/<int:motorista_id>/ativar",
    methods=["PUT"]
)
@jwt_required()
def api_ativar_motorista(motorista_id):
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
            "erro": "Somente administradores podem ativar motoristas."
        }), 403

    motorista = db.session.get(
        Motorista,
        motorista_id
    )

    if not motorista:
        return jsonify({
            "erro": "Motorista não encontrado."
        }), 404

    antes = {"status": motorista.status}
    motorista.status = "Ativo"

    registrar_log(
        acao="Ativação de motorista",
        detalhes=f"Motorista {motorista.nome} ativado.",
        modulo="Motoristas",
        entidade="Motorista",
        entidade_id=motorista.id,
        antes=antes,
        depois={"status": motorista.status},
        usuario_id=usuario.id,
        usuario_nome=usuario.nome,
        perfil=usuario.perfil
    )

    db.session.commit()

    return jsonify({
        "mensagem": "Motorista ativado com sucesso!",
        "motorista": {
            "id": motorista.id,
            "nome": motorista.nome,
            "status": motorista.status
        }
    }), 200


@admin_motoristas_bp.route(
    "/api/admin/motoristas/<int:motorista_id>/inativar",
    methods=["PUT"]
)
@jwt_required()
def api_inativar_motorista(motorista_id):
    usuario_id = int(get_jwt_identity())

    usuario = UsuarioSistema.query.get(usuario_id)

    if not usuario or not usuario.ativo:
        return jsonify({
            "erro": "Usuário não autorizado."
        }), 401

    if str(usuario.perfil).strip().lower() != "administrador":
        return jsonify({
            "erro": "Somente administradores podem inativar motoristas."
        }), 403

    motorista = Motorista.query.get(motorista_id)

    if not motorista:
        return jsonify({
            "erro": "Motorista não encontrado."
        }), 404

    status_viagem_ativos = STATUS_VIAGEM_ATIVOS_RECURSOS
    status_carga_ativos = STATUS_CARGA_ATIVOS_RECURSOS

    viagem_ativa = Viagem.query.filter(
        Viagem.motorista_id == motorista.id,
        Viagem.status.in_(status_viagem_ativos)
    ).first()

    carga_ativa = Rastreamento.query.filter(
        Rastreamento.motorista_id == motorista.id,
        Rastreamento.status.in_(status_carga_ativos)
    ).first()

    motorista_em_viagem = (
        str(motorista.disponibilidade).strip().lower()
        == "em viagem"
    )

    if viagem_ativa or carga_ativa or motorista_em_viagem:
        return jsonify({
            "erro": (
                "Não é possível inativar este motorista enquanto "
                "houver viagem ou carga ativa."
            )
        }), 409

    antes = {
        "status": motorista.status,
        "usuario_ativo": (
            motorista.usuario_sistema.ativo
            if motorista.usuario_sistema else None
        )
    }
    motorista.status = "Inativo"

    if (
        motorista.usuario_sistema_id is not None
        and motorista.usuario_sistema is not None
    ):
        motorista.usuario_sistema.ativo = False

    registrar_log(
        acao="Inativação de motorista",
        detalhes=f"Motorista {motorista.nome} inativado.",
        modulo="Motoristas",
        entidade="Motorista",
        entidade_id=motorista.id,
        antes=antes,
        depois={
            "status": motorista.status,
            "usuario_ativo": (
                motorista.usuario_sistema.ativo
                if motorista.usuario_sistema else None
            )
        },
        usuario_id=usuario.id,
        usuario_nome=usuario.nome,
        perfil=usuario.perfil
    )

    db.session.commit()

    return jsonify({
        "mensagem": "Motorista inativado com sucesso!"
    }), 200


@admin_motoristas_bp.route("/api/admin/motoristas/<int:id>", methods=["GET"])
@jwt_required()
def api_detalhe_motorista(id):
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
            "erro": "Você não possui permissão para consultar motoristas."
        }), 403

    motorista = Motorista.query.get_or_404(id)

    return {
        "id": motorista.id,
        "nome": motorista.nome,
        "cpf": motorista.cpf,
        "cnh": motorista.cnh,
        "categoria_cnh": getattr(motorista, "categoria_cnh", ""),
        "telefone": motorista.telefone,
        "email": motorista.email,
        "status": motorista.status,
    }


@admin_motoristas_bp.route("/api/admin/motoristas/<int:id>", methods=["PUT"])
@jwt_required()
def api_editar_motorista(id):
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
            "erro": "Você não possui permissão para editar motoristas."
        }), 403

    motorista = Motorista.query.get_or_404(id)
    antes = snapshot_objeto(motorista, [
        "nome", "cpf", "cnh", "categoria_cnh", "validade_cnh",
        "telefone", "email", "usuario", "status", "disponibilidade",
        "observacoes"
    ])

    dados = request.get_json(silent=True) or {}

    novo_status = str(
        dados.get("status", motorista.status)
    ).strip()

    alterando_para_inativo = (
        perfil_usuario == "administrador"
        and novo_status.lower() == "inativo"
        and str(motorista.status).strip().lower() != "inativo"
    )

    if alterando_para_inativo:
        status_viagem_ativos = STATUS_VIAGEM_ATIVOS_RECURSOS
        status_carga_ativos = STATUS_CARGA_ATIVOS_RECURSOS

        viagem_ativa = Viagem.query.filter(
            Viagem.motorista_id == motorista.id,
            Viagem.status.in_(status_viagem_ativos)
        ).first()

        carga_ativa = Rastreamento.query.filter(
            Rastreamento.motorista_id == motorista.id,
            Rastreamento.status.in_(status_carga_ativos)
        ).first()

        motorista_em_viagem = (
            str(motorista.disponibilidade).strip().lower()
            == "em viagem"
        )

        if viagem_ativa or carga_ativa or motorista_em_viagem:
            return jsonify({
                "erro": (
                    "Não é possível inativar este motorista enquanto "
                    "houver viagem ou carga ativa."
                )
            }), 409

    motorista.nome = dados.get("nome", motorista.nome)
    motorista.cpf = dados.get("cpf", motorista.cpf)
    motorista.cnh = dados.get("cnh", motorista.cnh)
    if hasattr(motorista, "categoria_cnh"):
     motorista.categoria_cnh = dados.get("categoria_cnh", motorista.categoria_cnh)
    motorista.telefone = dados.get(
        "telefone",
        motorista.telefone
    )
    motorista.email = dados.get(
        "email",
        motorista.email
    )
    if perfil_usuario == "administrador":
        motorista.status = novo_status

        if (
            alterando_para_inativo
            and motorista.usuario_sistema_id is not None
            and motorista.usuario_sistema is not None
        ):
            motorista.usuario_sistema.ativo = False

    registrar_log(
        acao="Edição de motorista",
        detalhes=f"Motorista {motorista.nome} atualizado.",
        modulo="Motoristas",
        entidade="Motorista",
        entidade_id=motorista.id,
        antes=antes,
        depois=snapshot_objeto(motorista, [
            "nome", "cpf", "cnh", "categoria_cnh", "validade_cnh",
            "telefone", "email", "usuario", "status", "disponibilidade",
            "observacoes"
        ]),
        usuario_id=usuario.id,
        usuario_nome=usuario.nome,
        perfil=usuario.perfil
    )

    db.session.commit()

    return {
        "mensagem": "Motorista atualizado com sucesso!"
    }
