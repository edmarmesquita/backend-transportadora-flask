from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from extensions import db
from models.clientes import Cliente
from models.comprovantes import ArquivoComprovanteViagem, ComprovanteEntrega
from models.historicos import HistoricoRastreamento
from models.ocorrencias import OcorrenciaEntrega
from models.operacao import Rastreamento, Viagem
from models.usuarios import UsuarioSistema
from services.autorizacao_comprovantes import obter_cliente_usuario
from services.auditoria import registrar_log
from utils.datas import formatar_data_brasilia


portal_cliente_bp = Blueprint(
    "portal_cliente",
    __name__
)


@portal_cliente_bp.route(
    "/api/cliente/minhas-cargas",
    methods=["GET"]
)
@jwt_required()
def api_cliente_minhas_cargas():
    usuario_id = int(get_jwt_identity())

    usuario_sistema = db.session.get(
        UsuarioSistema,
        usuario_id
    )

    if not usuario_sistema or not usuario_sistema.ativo:
        return jsonify({
            "erro": "Usuário não autorizado."
        }), 401

    if str(usuario_sistema.perfil).strip().lower() != "cliente":
        return jsonify({
            "erro": "Acesso permitido somente para clientes."
        }), 403

    cliente_usuario = obter_cliente_usuario(usuario_sistema)

    if not cliente_usuario:
        return jsonify({
            "erro": "O usuário não está vinculado a um cliente."
        }), 404

    if cliente_usuario.cliente_id:
        cargas = (
            Rastreamento.query
            .filter_by(
                cliente_id=cliente_usuario.cliente_id
            )
            .order_by(
                Rastreamento.ultima_atualizacao.desc()
            )
            .all()
        )
    else:
        cargas = (
            Rastreamento.query
            .filter_by(
                cliente=cliente_usuario.empresa
            )
            .order_by(
                Rastreamento.ultima_atualizacao.desc()
            )
            .all()
        )

    lista = []

    for carga in cargas:
        lista.append({
            "id": carga.id,
            "codigo": carga.codigo,
            "cliente": carga.cliente,
            "status": carga.status,
            "origem": getattr(
                carga,
                "origem",
                carga.local_atual or ""
            ),
            "local_atual": carga.local_atual or "",
            "destino": carga.destino or "",
            "previsao_entrega": (
                carga.previsao_entrega.strftime(
                    "%d/%m/%Y %H:%M"
                )
                if getattr(carga, "previsao_entrega", None)
                else ""
            ),
            "ultima_atualizacao": (
                carga.ultima_atualizacao.strftime(
                    "%d/%m/%Y %H:%M"
                )
                if carga.ultima_atualizacao
                else ""
            )
        })

    return jsonify(lista), 200


@portal_cliente_bp.route("/api/cliente/minhas-cargas/<int:carga_id>", methods=["GET"])
@jwt_required()
def api_detalhe_carga_cliente_logado(carga_id):
    usuario_id = int(get_jwt_identity())

    usuario_sistema = db.session.get(
        UsuarioSistema,
        usuario_id
    )

    if not usuario_sistema or not usuario_sistema.ativo:
        return jsonify({
            "erro": "Usuário não autorizado."
        }), 401

    if usuario_sistema.perfil.lower() != "cliente":
        return {
            "erro": "Acesso permitido somente para clientes."
        }, 403

    cliente_usuario = obter_cliente_usuario(usuario_sistema)

    if not cliente_usuario:
        return {
            "erro": "O usuário não está vinculado a um cliente."
        }, 404

    consulta = Rastreamento.query.filter_by(id=carga_id)

    if cliente_usuario.cliente_id:
        consulta = consulta.filter_by(
            cliente_id=cliente_usuario.cliente_id
        )
    else:
        consulta = consulta.filter_by(
            cliente=cliente_usuario.empresa
        )

    carga = consulta.first()

    if not carga:
        return {
            "erro": "Carga não encontrada ou não pertence a este cliente."
        }, 404


    historico = HistoricoRastreamento.query.filter_by(
        rastreamento_id=carga.id
        ).order_by(
            HistoricoRastreamento.data_evento.asc()
        ).all()

    return jsonify({
    "id": carga.id,
    "codigo": carga.codigo,
    "cliente": carga.cliente,
    "status": carga.status,
    "local_atual": carga.local_atual,
    "destino": carga.destino,
    "ultima_atualizacao": formatar_data_brasilia(
        carga.ultima_atualizacao
    ),
    "historico": [
        {
            "id": evento.id,
            "status": evento.status,
            "local": evento.local,
            "observacao": evento.observacao or "",
            "data_evento": formatar_data_brasilia(
                evento.data_evento
            )
        }
        for evento in historico
    ]
 }), 200


@portal_cliente_bp.route(
    "/api/cliente/minhas-cargas/<int:carga_id>/ocorrencias",
    methods=["GET"]
)
@jwt_required()
def api_listar_ocorrencias_cliente(carga_id):
    usuario_id = int(get_jwt_identity())

    usuario_sistema = db.session.get(
        UsuarioSistema,
        usuario_id
    )

    if not usuario_sistema or not usuario_sistema.ativo:
        return jsonify({
            "erro": "Usuário não autorizado."
        }), 401

    if usuario_sistema.perfil.lower() != "cliente":
        return {
            "erro": "Acesso permitido somente para clientes."
        }, 403

    cliente_usuario = obter_cliente_usuario(usuario_sistema)

    if not cliente_usuario:
        return {
            "erro": "O usuário não está vinculado a um cliente."
        }, 404

    consulta = Rastreamento.query.filter_by(id=carga_id)

    if cliente_usuario.cliente_id:
        consulta = consulta.filter_by(
            cliente_id=cliente_usuario.cliente_id
        )
    else:
        consulta = consulta.filter_by(
            cliente=cliente_usuario.empresa
        )

    carga = consulta.first()

    if not carga:
        return {
            "erro": "Carga não encontrada ou não pertence a este cliente."
        }, 404

    ocorrencias = OcorrenciaEntrega.query.filter_by(
        rastreamento_id=carga.id
    ).order_by(
        OcorrenciaEntrega.data_ocorrencia.desc()
    ).all()

    return jsonify([
        {
            "id": ocorrencia.id,
            "titulo": ocorrencia.titulo,
            "descricao": ocorrencia.descricao,
            "data_ocorrencia": (
                formatar_data_brasilia(ocorrencia.data_ocorrencia)
                if ocorrencia.data_ocorrencia
                else ""
            )
        }
        for ocorrencia in ocorrencias
    ]), 200


@portal_cliente_bp.route(
    "/api/cliente/minhas-cargas/<int:carga_id>/ocorrencias",
    methods=["POST"]
)
@jwt_required()
def api_criar_ocorrencia_cliente(carga_id):
    usuario_id = int(get_jwt_identity())

    usuario_sistema = db.session.get(
        UsuarioSistema,
        usuario_id
    )

    if not usuario_sistema or not usuario_sistema.ativo:
        return jsonify({
            "erro": "Usuário não autorizado."
        }), 401

    if usuario_sistema.perfil.lower() != "cliente":
        return {
            "erro": "Acesso permitido somente para clientes."
        }, 403

    cliente_usuario = obter_cliente_usuario(usuario_sistema)

    if not cliente_usuario:
        return {
            "erro": "O usuário não está vinculado a um cliente."
        }, 404

    consulta = Rastreamento.query.filter_by(id=carga_id)

    if cliente_usuario.cliente_id:
        consulta = consulta.filter_by(
            cliente_id=cliente_usuario.cliente_id
        )
    else:
        consulta = consulta.filter_by(
            cliente=cliente_usuario.empresa
        )

    carga = consulta.first()

    if not carga:
        return {
            "erro": "Carga não encontrada ou não pertence a este cliente."
        }, 404

    dados = request.get_json() or {}

    titulo = dados.get("titulo", "").strip()
    descricao = dados.get("descricao", "").strip()

    if not titulo or not descricao:
        return {
            "erro": "Informe o título e a descrição da ocorrência."
        }, 400

    ocorrencia = OcorrenciaEntrega(
        rastreamento_id=carga.id,
        titulo=titulo,
        descricao=descricao
    )

    db.session.add(ocorrencia)
    registrar_log(
        acao="Criação de ocorrência pelo cliente",
        detalhes=f"Cliente {usuario_sistema.nome} registrou ocorrência na carga {carga.id}.",
        modulo="Ocorrências",
        entidade="OcorrenciaEntrega",
        entidade_id=carga.id,
        depois={"titulo": titulo, "descricao": descricao},
        usuario_id=usuario_sistema.id,
        usuario_nome=usuario_sistema.nome,
        perfil=usuario_sistema.perfil
    )
    db.session.commit()

    return jsonify({
        "mensagem": "Ocorrência registrada com sucesso!",
        "ocorrencia": {
            "id": ocorrencia.id,
            "titulo": ocorrencia.titulo,
            "descricao": ocorrencia.descricao,
            "data_ocorrencia": formatar_data_brasilia(
    ocorrencia.data_ocorrencia
)
        }
    }), 201


@portal_cliente_bp.route(
    "/api/cliente/minhas-cargas/<int:carga_id>/comprovantes",
    methods=["GET"]
)
@jwt_required()
def api_comprovantes_carga_cliente(carga_id):
    usuario_id = int(get_jwt_identity())

    usuario_sistema = db.session.get(
        UsuarioSistema,
        usuario_id
    )

    if not usuario_sistema or not usuario_sistema.ativo:
        return jsonify({
            "erro": "Usuário não autorizado."
        }), 401

    if str(usuario_sistema.perfil).strip().lower() != "cliente":
        return {
            "erro": "Acesso permitido somente para clientes."
        }, 403

    cliente_usuario = obter_cliente_usuario(usuario_sistema)

    if not cliente_usuario:
        return {
            "erro": "O usuário não está vinculado a um cliente."
        }, 404

    consulta = Rastreamento.query.filter_by(id=carga_id)

    if cliente_usuario.cliente_id:
        consulta = consulta.filter_by(
            cliente_id=cliente_usuario.cliente_id
        )
    else:
        consulta = consulta.filter_by(
            cliente=cliente_usuario.empresa
        )

    carga = consulta.first()

    if not carga:
        return {
            "erro": "Carga não encontrada ou não pertence a este cliente."
        }, 404

    viagem = Viagem.query.filter_by(
        rastreamento_id=carga.id
    ).first()

    if not viagem:
        return jsonify({
            "comprovantes": [],
            "arquivos": []
        }), 200

    comprovantes = ComprovanteEntrega.query.filter_by(
        viagem_id=viagem.id
    ).order_by(
        ComprovanteEntrega.data_entrega.desc()
    ).all()

    arquivos = ArquivoComprovanteViagem.query.filter_by(
        viagem_id=viagem.id
    ).order_by(
        ArquivoComprovanteViagem.data_upload.desc()
    ).all()

    return jsonify({
        "comprovantes": [
            {
                "id": comprovante.id,
                "viagem_id": comprovante.viagem_id,
                "recebedor": comprovante.recebedor,
                "observacao": comprovante.observacao or "",
                "data_entrega": (
                    formatar_data_brasilia(comprovante.data_entrega)
                    if comprovante.data_entrega
                    else ""
                )
            }
            for comprovante in comprovantes
        ],
        "arquivos": [
            {
                "id": arquivo.id,
                "nome_arquivo": arquivo.nome_arquivo,
                "data_upload": formatar_data_brasilia(
                    arquivo.data_upload
                ),
                "download_endpoint": (
                    f"/api/comprovantes/arquivos/{arquivo.id}/download"
                )
            }
            for arquivo in arquivos
        ]
    }), 200


@portal_cliente_bp.route(
    "/api/cliente/perfil",
    methods=["GET"]
)
@jwt_required()
def api_perfil_cliente():
    usuario_id = int(get_jwt_identity())

    usuario_sistema = db.session.get(
        UsuarioSistema,
        usuario_id
    )

    if not usuario_sistema or not usuario_sistema.ativo:
        return jsonify({
            "erro": "Usuário não autorizado."
        }), 401

    if str(usuario_sistema.perfil).strip().lower() != "cliente":
        return jsonify({
            "erro": "Acesso permitido somente para clientes."
        }), 403

    cliente_usuario = obter_cliente_usuario(usuario_sistema)

    if not cliente_usuario:
        return jsonify({
            "erro": "Cliente não vinculado ao usuário."
        }), 404

    cliente = None

    if cliente_usuario.cliente_id:
        cliente = db.session.get(
            Cliente,
            cliente_usuario.cliente_id
        )

    return jsonify({
        "nome": cliente_usuario.nome or usuario_sistema.nome,
        "empresa": (
            cliente.razao_social
            if cliente
            else cliente_usuario.empresa
        ),
        "nome_fantasia": (
            cliente.nome_fantasia
            if cliente
            else ""
        ),
        "responsavel": (
            cliente.responsavel
            if cliente
            else cliente_usuario.nome
        ),
        "email": (
            cliente.email
            if cliente and cliente.email
            else cliente_usuario.email
        ),
        "telefone": (
            cliente.telefone
            if cliente
            else ""
        ),
        "documento": (
            cliente.documento
            if cliente
            else ""
        ),
        "endereco": (
            cliente.endereco
            if cliente
            else ""
        ),
        "cidade": (
            cliente.cidade
            if cliente
            else ""
        ),
        "estado": (
            cliente.estado
            if cliente
            else ""
        )
    }), 200
