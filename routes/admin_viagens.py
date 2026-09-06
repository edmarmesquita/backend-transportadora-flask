from datetime import datetime

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from extensions import db
from models.comprovantes import (
    ArquivoComprovanteViagem,
    ComprovanteEntrega,
)
from models.historicos import HistoricoRastreamento, HistoricoViagem
from models.localizacoes import LocalizacaoViagem
from models.ocorrencias import OcorrenciaViagem
from models.operacao import Rastreamento, Viagem
from models.recursos import Motorista, Veiculo
from models.usuarios import UsuarioSistema
from services.historicos import registrar_historico
from services.recursos import (
    recalcular_disponibilidade_motorista,
    recalcular_status_veiculo,
    veiculo_possui_status_especial,
)
from utils.arquivos import (
    ErroValidacaoArquivo,
    remover_arquivo_criado,
    salvar_arquivo_upload,
)
from utils.constantes import STATUS_VIAGEM_ATIVOS_RECURSOS
from utils.datas import formatar_data_brasilia


admin_viagens_bp = Blueprint(
    "admin_viagens",
    __name__
)


@admin_viagens_bp.route("/api/admin/viagens", methods=["GET"])
@jwt_required()
def api_admin_viagens():
    usuario_id = int(get_jwt_identity())
    usuario = db.session.get(UsuarioSistema, usuario_id)

    if not usuario or not usuario.ativo:
        return jsonify({"erro": "Usuário não autorizado."}), 401

    if str(usuario.perfil).strip().lower() not in [
        "administrador", "operador"
    ]:
        return jsonify({
            "erro": "Você não possui permissão para acessar viagens."
        }), 403

    viagens = Viagem.query.order_by(
        Viagem.data_criacao.desc()
    ).all()

    lista = []

    for viagem in viagens:
        lista.append({
            "id": viagem.id,
            "codigo_carga": viagem.carga.codigo if viagem.carga else "",
            "cliente": viagem.carga.cliente if viagem.carga else "",
            "motorista": viagem.motorista.nome if viagem.motorista else "",
            "veiculo": viagem.veiculo.placa if viagem.veiculo else "",
            "origem": viagem.origem,
            "destino": viagem.destino,
            "status": viagem.status,
            "data_criacao": formatar_data_brasilia(viagem.data_criacao),
            "data_criacao_iso": viagem.data_criacao.isoformat() if viagem.data_criacao else None,
        })

    return jsonify(lista), 200


@admin_viagens_bp.route("/api/admin/viagens", methods=["POST"])
@jwt_required()
def api_criar_viagem():
    # Endpoint legado mantido por compatibilidade.
    usuario_id = int(get_jwt_identity())
    usuario = db.session.get(UsuarioSistema, usuario_id)

    if not usuario or not usuario.ativo:
        return jsonify({"erro": "Usuário não autorizado."}), 401

    if str(usuario.perfil).strip().lower() not in [
        "administrador", "operador"
    ]:
        return jsonify({
            "erro": "Você não possui permissão para criar viagens."
        }), 403

    dados = request.get_json(silent=True) or {}

    rastreamento_id = dados.get("rastreamento_id")
    motorista_id = dados.get("motorista_id")
    veiculo_id = dados.get("veiculo_id")

    carga = Rastreamento.query.get(rastreamento_id)

    if not carga:
        return {"erro": "Carga não encontrada."}, 404

    nova_viagem = Viagem(
        rastreamento_id=int(rastreamento_id),
        motorista_id=int(motorista_id) if motorista_id else None,
        veiculo_id=int(veiculo_id) if veiculo_id else None,
        origem=carga.local_atual,
        destino=carga.destino,
        status="Planejada"
    )

    db.session.add(nova_viagem)
    db.session.flush()

    historico = HistoricoViagem(
    viagem_id=nova_viagem.id,
    status="Planejada",
    observacao="Viagem criada pelo painel administrativo"
)

    db.session.add(historico)
    db.session.commit()

    return {"mensagem": "Viagem criada com sucesso!"}, 201


@admin_viagens_bp.route("/api/admin/viagens/<int:id>/historico", methods=["GET"])
@jwt_required()
def api_historico_viagem(id):
    usuario_id = int(get_jwt_identity())
    usuario = db.session.get(UsuarioSistema, usuario_id)

    if not usuario or not usuario.ativo:
        return jsonify({"erro": "Usuário não autorizado."}), 401

    if str(usuario.perfil).strip().lower() not in [
        "administrador", "operador"
    ]:
        return jsonify({
            "erro": "Você não possui permissão para consultar históricos de viagens."
        }), 403

    historicos = HistoricoViagem.query.filter_by(
        viagem_id=id
    ).order_by(
        HistoricoViagem.data_evento.desc()
    ).all()

    lista = []

    for item in historicos:
        lista.append({
            "id": item.id,
            "status": item.status,
            "observacao": item.observacao,
            "data_evento": formatar_data_brasilia(item.data_evento)
        })

    return jsonify(lista), 200


@admin_viagens_bp.route(
    "/api/admin/viagens/<int:id>/status",
    methods=["POST"]
)
@jwt_required()
def api_atualizar_status_viagem(id):
    usuario_id = int(get_jwt_identity())
    usuario = db.session.get(UsuarioSistema, usuario_id)

    if not usuario or not usuario.ativo:
        return jsonify({"erro": "Usuário não autorizado."}), 401

    if str(usuario.perfil).strip().lower() not in [
        "administrador", "operador"
    ]:
        return jsonify({
            "erro": "Você não possui permissão para alterar viagens."
        }), 403

    viagem = Viagem.query.get_or_404(id)

    status_atual = str(viagem.status).strip().lower()

    if status_atual == "cancelada":
        return jsonify({
            "erro": "Não é possível alterar o status de uma viagem cancelada."
        }), 409

    if status_atual == "entregue":
        return jsonify({
            "erro": "Não é possível alterar o status de uma viagem já entregue."
        }), 409

    dados = request.get_json() or {}

    novo_status = str(
        dados.get("status", "")
    ).strip()

    status_permitidos = [
        "Em coleta",
        "Carregando",
        "Em trânsito",
        "Parada operacional",
        "Saiu para entrega",
        "Cancelada"
    ]

    if novo_status not in status_permitidos:
        return jsonify({
            "erro": "Status inválido."
        }), 400

    motorista = db.session.get(
        Motorista,
        viagem.motorista_id
    )

    veiculo = db.session.get(
        Veiculo,
        viagem.veiculo_id
    )

    carga = db.session.get(
        Rastreamento,
        viagem.rastreamento_id
    )

    if (
        novo_status in STATUS_VIAGEM_ATIVOS_RECURSOS
        and veiculo
        and veiculo_possui_status_especial(veiculo)
    ):
        return jsonify({
            "erro": (
                "Não é possível iniciar uma operação com veículo "
                "inativo ou em manutenção."
            )
        }), 409

    try:
        viagem.status = novo_status

        # Mantém carga e viagem sincronizadas.
        if carga:
            carga.status = novo_status

            if hasattr(carga, "ultima_atualizacao"):
                carga.ultima_atualizacao = datetime.utcnow()

        # ------------------------------------------------
        # CANCELAMENTO
        # ------------------------------------------------
        if novo_status == "Cancelada":

            recalcular_disponibilidade_motorista(
                motorista,
                excluir_viagem_id=viagem.id,
                excluir_carga_id=(carga.id if carga else None)
            )

            recalcular_status_veiculo(
                veiculo,
                excluir_viagem_id=viagem.id,
                excluir_carga_id=(carga.id if carga else None)
            )

        # ------------------------------------------------
        # VIAGEM OPERACIONAL
        # ------------------------------------------------
        else:

            if motorista:
                motorista.disponibilidade = "Em viagem"

            if veiculo:
                veiculo.status = "Em viagem"

        historico = HistoricoViagem(
            viagem_id=viagem.id,
            status="STATUS",
            observacao=(
                f"Status alterado para {novo_status}."
            )
        )

        db.session.add(historico)

        if carga:
            historico_rastreamento = HistoricoRastreamento(
                rastreamento_id=carga.id,
                status=novo_status,
                local=carga.local_atual,
                observacao=(
                    f"Status da viagem alterado para {novo_status}."
                )
            )

            db.session.add(historico_rastreamento)

        db.session.commit()

        return jsonify({
            "mensagem": "Status atualizado com sucesso!",
            "status": viagem.status,
            "disponibilidade_motorista": (
                motorista.disponibilidade
                if motorista
                else None
            )
        }), 200

    except Exception as erro:
        db.session.rollback()

        print(
            "ERRO AO ATUALIZAR STATUS DA VIAGEM:",
            erro
        )

        return jsonify({
            "erro": "Não foi possível atualizar o status."
        }), 500


@admin_viagens_bp.route("/api/admin/viagens/<int:id>", methods=["GET"])
@jwt_required()
def api_detalhe_viagem(id):
    usuario_id = int(get_jwt_identity())
    usuario = db.session.get(UsuarioSistema, usuario_id)

    if not usuario or not usuario.ativo:
        return jsonify({"erro": "Usuário não autorizado."}), 401

    if str(usuario.perfil).strip().lower() not in [
        "administrador", "operador"
    ]:
        return jsonify({
            "erro": "Você não possui permissão para consultar viagens."
        }), 403

    viagem = Viagem.query.get_or_404(id)

    return {
        "id": viagem.id,
        "codigo_carga": viagem.carga.codigo if viagem.carga else "",
        "cliente": viagem.carga.cliente if viagem.carga else "",
        "motorista": viagem.motorista.nome if viagem.motorista else "",
        "veiculo": viagem.veiculo.placa if viagem.veiculo else "",
        "origem": viagem.origem,
        "destino": viagem.destino,
        "status": viagem.status,
        "data_criacao": formatar_data_brasilia(
    viagem.data_criacao
),
        "data_criacao_iso": viagem.data_criacao.isoformat() if viagem.data_criacao else None
    }


@admin_viagens_bp.route(
    "/api/admin/viagens/<int:id>/ocorrencias",
    methods=["GET"]
)
@jwt_required()
def api_ocorrencias_viagem(id):
    usuario_id = int(get_jwt_identity())
    usuario = db.session.get(UsuarioSistema, usuario_id)

    if not usuario or not usuario.ativo:
        return jsonify({"erro": "Usuário não autorizado."}), 401

    if str(usuario.perfil).strip().lower() not in [
        "administrador", "operador"
    ]:
        return jsonify({
            "erro": "Você não possui permissão para consultar ocorrências."
        }), 403

    ocorrencias = OcorrenciaViagem.query.filter_by(
        viagem_id=id
    ).order_by(
        OcorrenciaViagem.data_criacao.desc()
    ).all()

    lista = []

    for item in ocorrencias:
        lista.append({
            "id": item.id,
            "descricao": item.descricao,
            "data": formatar_data_brasilia(item.data_criacao),
            "data_iso": item.data_criacao.isoformat() if item.data_criacao else None
        })

    return lista


@admin_viagens_bp.route(
    "/api/admin/viagens/<int:id>/ocorrencias",
    methods=["POST"]
)
@jwt_required()
def api_criar_ocorrencia(id):
    usuario_id = int(get_jwt_identity())
    usuario = db.session.get(UsuarioSistema, usuario_id)

    if not usuario or not usuario.ativo:
        return jsonify({"erro": "Usuário não autorizado."}), 401

    if str(usuario.perfil).strip().lower() not in [
        "administrador", "operador"
    ]:
        return jsonify({
            "erro": "Você não possui permissão para registrar ocorrências."
        }), 403

    dados = request.get_json(silent=True) or {}

    ocorrencia = OcorrenciaViagem(
        viagem_id=id,
        descricao=str(dados.get("descricao", "")).strip()
    )

    db.session.add(ocorrencia)

    historico = HistoricoViagem(
        viagem_id=id,
        status="Ocorrência",
        observacao=str(dados.get("descricao", "")).strip()
    )

    db.session.add(historico)

    db.session.commit()

    return {
        "mensagem": "Ocorrência registrada!"
    }


@admin_viagens_bp.route(
    "/api/admin/viagens/<int:id>/comprovante",
    methods=["GET"]
)
@jwt_required()
def api_consultar_comprovante(id):
    usuario_id = int(get_jwt_identity())
    usuario = db.session.get(UsuarioSistema, usuario_id)

    if not usuario or not usuario.ativo:
        return jsonify({"erro": "Usuário não autorizado."}), 401

    if str(usuario.perfil).strip().lower() not in [
        "administrador", "operador"
    ]:
        return jsonify({
            "erro": "Você não possui permissão para consultar comprovantes."
        }), 403


    comprovante = ComprovanteEntrega.query.filter_by(
        viagem_id=id
    ).first()

    if not comprovante:
        return {}

    return {
        "recebedor": comprovante.recebedor,
        "observacao": comprovante.observacao,
        "data_entrega":
            comprovante.data_entrega.strftime(
                "%d/%m/%Y %H:%M"
            )
    }


@admin_viagens_bp.route(
    "/api/admin/viagens/<int:id>/comprovante/arquivo",
    methods=["POST"]
)
@jwt_required()
def api_upload_arquivo_comprovante(id):
    usuario_id = int(get_jwt_identity())
    usuario = db.session.get(UsuarioSistema, usuario_id)

    if not usuario or not usuario.ativo:
        return jsonify({"erro": "Usuário não autorizado."}), 401

    if str(usuario.perfil).strip().lower() not in [
        "administrador", "operador"
    ]:
        return jsonify({
            "erro": "Você não possui permissão para anexar comprovantes."
        }), 403

    viagem = db.session.get(Viagem, id)

    if not viagem:
        return jsonify({"erro": "Viagem não encontrada."}), 404

    carga = db.session.get(
        Rastreamento,
        viagem.rastreamento_id
    )

    if (
        str(viagem.status).strip().lower() == "cancelada"
        or (
            carga
            and str(carga.status).strip().lower() == "cancelada"
        )
    ):
        return jsonify({
            "erro": "Não é possível adicionar comprovante a uma viagem cancelada."
        }), 409

    arquivo = request.files.get("arquivo")

    if not arquivo or not arquivo.filename:
        return {"erro": "Nenhum arquivo enviado."}, 400

    caminho = None

    try:
        nome_seguro, nome_final, caminho = salvar_arquivo_upload(
            arquivo,
            current_app.config["UPLOAD_FOLDER"],
            current_app.config["ALLOWED_EXTENSIONS"],
            current_app.config["UPLOAD_MAX_FILE_SIZE"]
        )

        registro = ArquivoComprovanteViagem(
            viagem_id=id,
            nome_arquivo=nome_final
        )

        historico = HistoricoViagem(
            viagem_id=id,
            status="Comprovante anexado",
            observacao=f"Arquivo anexado: {nome_seguro}"
        )

        db.session.add(registro)
        db.session.add(historico)
        db.session.commit()
    except ErroValidacaoArquivo as erro:
        return {"erro": erro.mensagem}, erro.status_code
    except Exception as erro:
        db.session.rollback()
        remover_arquivo_criado(caminho, current_app.logger)
        current_app.logger.exception(
            "Erro ao persistir comprovante administrativo."
        )
        return {"erro": "Não foi possível enviar o arquivo."}, 500

    return {
        "mensagem": "Arquivo do comprovante enviado com sucesso!"
    }, 201


@admin_viagens_bp.route(
    "/api/admin/viagens/<int:id>/comprovantes/arquivos",
    methods=["GET"]
)
@jwt_required()
def api_listar_arquivos_comprovante(id):
    usuario_id = int(get_jwt_identity())
    usuario = db.session.get(UsuarioSistema, usuario_id)

    if not usuario or not usuario.ativo:
        return jsonify({"erro": "Usuário não autorizado."}), 401

    if str(usuario.perfil).strip().lower() not in [
        "administrador", "operador"
    ]:
        return jsonify({
            "erro": "Você não possui permissão para consultar comprovantes."
        }), 403

    arquivos = ArquivoComprovanteViagem.query.filter_by(
        viagem_id=id
    ).order_by(
        ArquivoComprovanteViagem.data_upload.desc()
    ).all()

    lista = []

    for arquivo in arquivos:
        lista.append({
            "id": arquivo.id,
            "nome_arquivo": arquivo.nome_arquivo,
            "data_upload": formatar_data_brasilia(arquivo.data_upload),
            "download_endpoint": (
                f"/api/comprovantes/arquivos/{arquivo.id}/download"
            )
        })

    return lista


@admin_viagens_bp.route("/api/admin/viagens/<int:id>/localizacoes", methods=["GET"])
@jwt_required()
def api_listar_localizacoes_viagem(id):
    usuario_id = int(get_jwt_identity())
    usuario = db.session.get(UsuarioSistema, usuario_id)

    if not usuario or not usuario.ativo:
        return jsonify({"erro": "Usuário não autorizado."}), 401

    if str(usuario.perfil).strip().lower() not in [
        "administrador", "operador"
    ]:
        return jsonify({
            "erro": "Você não possui permissão para consultar localizações."
        }), 403

    localizacoes = LocalizacaoViagem.query.filter_by(
        viagem_id=id
    ).order_by(
        LocalizacaoViagem.data_registro.desc()
    ).all()

    lista = []

    for item in localizacoes:
            lista.append({
            "id": item.id,
            "localizacao": item.localizacao,
            "observacao": item.observacao,
            "data_registro": formatar_data_brasilia(item.data_registro)
        })

    return jsonify(lista), 200


@admin_viagens_bp.route("/api/admin/viagens/<int:id>/localizacoes", methods=["POST"])
@jwt_required()
def api_criar_localizacao_viagem(id):
    usuario_id = int(get_jwt_identity())
    usuario = db.session.get(UsuarioSistema, usuario_id)

    if not usuario or not usuario.ativo:
        return jsonify({"erro": "Usuário não autorizado."}), 401

    if str(usuario.perfil).strip().lower() not in [
        "administrador", "operador"
    ]:
        return jsonify({
            "erro": "Você não possui permissão para registrar localizações."
        }), 403

    dados = request.get_json()

    localizacao = LocalizacaoViagem(
        viagem_id=id,
        localizacao=dados.get("localizacao"),
        observacao=dados.get("observacao")
    )

    db.session.add(localizacao)

    historico = HistoricoViagem(
        viagem_id=id,
        status="Localização atualizada",
        observacao=dados.get("localizacao")
    )

    db.session.add(historico)
    db.session.commit()

    return {
        "mensagem": "Localização registrada com sucesso!"
    }, 201


@admin_viagens_bp.route(
    "/api/admin/viagens/<int:viagem_id>/finalizar",
    methods=["POST"]
)

@jwt_required()
def api_finalizar_viagem(viagem_id):
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
            "erro": "Você não possui permissão para finalizar entregas."
        }), 403

    viagem = db.session.get(
        Viagem,
        viagem_id
    )

    if not viagem:
        return jsonify({
            "erro": "Viagem não encontrada."
        }), 404

    status_atual = str(viagem.status).strip().lower()

    if status_atual == "entregue":
        return jsonify({
            "erro": "Esta viagem já foi finalizada."
        }), 409

    if status_atual == "cancelada":
        return jsonify({
            "erro": "Não é possível finalizar uma viagem cancelada."
        }), 409

    dados = request.get_json() or {}

    recebedor = str(
        dados.get("recebedor", "")
    ).strip()

    observacao = str(
        dados.get("observacao", "")
    ).strip()

    if not recebedor:
        return jsonify({
            "erro": "Informe o nome do recebedor."
        }), 400

    carga = db.session.get(
        Rastreamento,
        viagem.rastreamento_id
    )

    motorista = db.session.get(
        Motorista,
        viagem.motorista_id
    )

    veiculo = db.session.get(
        Veiculo,
        viagem.veiculo_id
    )

    if not carga:
        return jsonify({
            "erro": "A carga vinculada à viagem não foi encontrada."
        }), 404

    if str(carga.status).strip().lower() == "cancelada":
        return jsonify({
            "erro": "Não é possível finalizar uma viagem cancelada."
        }), 409

    try:
        comprovante_existente = (
            ComprovanteEntrega.query
            .filter_by(viagem_id=viagem.id)
            .first()
        )

        if comprovante_existente:
            return jsonify({
                "erro": "Esta viagem já possui um comprovante de entrega."
            }), 409

        comprovante = ComprovanteEntrega(
            viagem_id=viagem.id,
            recebedor=recebedor,
            observacao=observacao,
            data_entrega=datetime.utcnow()
        )

        db.session.add(comprovante)

        viagem.status = "Entregue"
        carga.status = "Entregue"

        if hasattr(carga, "ultima_atualizacao"):
            carga.ultima_atualizacao = datetime.utcnow()

        recalcular_disponibilidade_motorista(
            motorista,
            excluir_viagem_id=viagem.id,
            excluir_carga_id=carga.id
        )

        recalcular_status_veiculo(
            veiculo,
            excluir_viagem_id=viagem.id,
            excluir_carga_id=carga.id
        )

        historico_rastreamento = HistoricoRastreamento(
            rastreamento_id=carga.id,
            status="Entregue",
            local=viagem.destino,
            observacao=(
                f"Entrega finalizada. Recebido por {recebedor}."
                + (
                    f" Observação: {observacao}"
                    if observacao
                    else ""
                )
            )
        )

        db.session.add(historico_rastreamento)

        registrar_historico(
            viagem.id,
            "ENTREGA",
            (
                f"Entrega finalizada. Recebedor: {recebedor}."
                + (
                    f" Observação: {observacao}"
                    if observacao
                    else ""
                )
            )
        )



        db.session.commit()

        return jsonify({
            "mensagem": "Entrega finalizada com sucesso!",
            "comprovante": {
                "id": comprovante.id,
                "viagem_id": viagem.id,
                "recebedor": comprovante.recebedor,
                "observacao": comprovante.observacao or "",
                "data_entrega": formatar_data_brasilia(
                    comprovante.data_entrega
                )
            }
        }), 201

    except Exception as erro:
        db.session.rollback()

        print(
            "ERRO AO FINALIZAR ENTREGA:",
            erro
        )

        return jsonify({
            "erro": "Não foi possível finalizar a entrega."
        }), 500


@admin_viagens_bp.route("/api/admin/viagens/despachar", methods=["POST"])
@jwt_required()
def api_despachar_viagem():
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
            "erro": "Você não possui permissão para despachar viagens."
        }), 403

    dados = request.get_json() or {}

    rastreamento_id = dados.get("rastreamento_id")
    motorista_id = dados.get("motorista_id")
    veiculo_id = dados.get("veiculo_id")

    origem = str(dados.get("origem", "")).strip()
    destino = str(dados.get("destino", "")).strip()

    data_saida_texto = dados.get("data_saida")
    previsao_entrega_texto = dados.get("previsao_entrega")

    if not rastreamento_id:
        return jsonify({
            "erro": "Selecione uma carga."
        }), 400


    if not motorista_id:
        return jsonify({
            "erro": "Selecione um motorista."
        }), 400

    if not veiculo_id:
        return jsonify({
            "erro": "Selecione um veículo."
        }), 400

    if not origem:
        return jsonify({
            "erro": "Informe a origem da viagem."
        }), 400

    if not destino:
        return jsonify({
            "erro": "Informe o destino da viagem."
        }), 400

    carga = db.session.get(
        Rastreamento,
        int(rastreamento_id)
    )

    if not carga:
        return jsonify({
            "erro": "Carga não encontrada."
        }), 404

    motorista = db.session.get(
        Motorista,
        int(motorista_id)
    )

    if not motorista:
        return jsonify({
            "erro": "Motorista não encontrado."
        }), 404

    veiculo = db.session.get(
        Veiculo,
        int(veiculo_id)
    )

    if not veiculo:
        return jsonify({
            "erro": "Veículo não encontrado."
        }), 404

    status_viagem_ativos = [
    "Planejada",
    "Em andamento",
    "Em coleta",
    "Carregando",
    "Em trânsito",
    "Parada operacional",
    "Saiu para entrega"
]

    viagem_aberta_carga = Viagem.query.filter(
        Viagem.rastreamento_id == carga.id,
        Viagem.status.in_(status_viagem_ativos)
    ).first()

    if viagem_aberta_carga:
        return jsonify({
            "erro": "Esta carga já possui uma viagem aberta."
        }), 409

    viagem_aberta_motorista = Viagem.query.filter(
        Viagem.motorista_id == motorista.id,
        Viagem.status.in_(status_viagem_ativos)
    ).first()

    if viagem_aberta_motorista:
        return jsonify({
            "erro": "Este motorista já está vinculado a outra viagem."
        }), 409

    viagem_aberta_veiculo = Viagem.query.filter(
        Viagem.veiculo_id == veiculo.id,
        Viagem.status.in_(status_viagem_ativos)
    ).first()

    if viagem_aberta_veiculo:
        return jsonify({
            "erro": "Este veículo já está vinculado a outra viagem."
        }), 409

    if str(motorista.status).lower() == "inativo":
        return jsonify({
            "erro": "Não é possível selecionar um motorista inativo."
        }), 400

    if str(motorista.disponibilidade).strip().lower() == "em viagem":
        return jsonify({
        "erro": "Este motorista já está em viagem."
    }), 409

    if str(veiculo.status).lower() in [
        "inativo",
        "manutenção",
        "em manutenção"
    ]:
        return jsonify({
            "erro": "Este veículo não está disponível."
        }), 400

    if str(veiculo.status).lower() == "em viagem":
        return jsonify({
            "erro": "Este veículo já está em viagem."
        }), 409

    try:
        data_saida = (
            datetime.fromisoformat(data_saida_texto)
            if data_saida_texto
            else datetime.utcnow()
        )

        previsao_entrega = (
            datetime.fromisoformat(previsao_entrega_texto)
            if previsao_entrega_texto
            else None
        )

    except ValueError:
        return jsonify({
            "erro": "Uma das datas informadas é inválida."
        }), 400

    if previsao_entrega and previsao_entrega < data_saida:
        return jsonify({
            "erro": "A previsão de entrega não pode ser anterior à saída."
        }), 400

    try:
        viagem = Viagem(
            rastreamento_id=carga.id,
            motorista_id=motorista.id,
            veiculo_id=veiculo.id,
            origem=origem,
            destino=destino,
            status="Em andamento",
            data_saida=data_saida,
            previsao_entrega=previsao_entrega
        )

        db.session.add(viagem)

        db.session.flush()

        registrar_historico(
            viagem.id,
            "DESPACHO",
            (
                f"Viagem despachada com o motorista {motorista.nome} "
                f"e o veículo {veiculo.placa}."
            )
        )

        carga.motorista_id = motorista.id
        carga.veiculo_id = veiculo.id
        carga.status = "Em trânsito"
        carga.local_atual = origem
        carga.destino = destino
        carga.previsao_entrega = previsao_entrega
        carga.ultima_atualizacao = datetime.utcnow()

        motorista.disponibilidade = "Em viagem"
        veiculo.status = "Em viagem"

        historico = HistoricoRastreamento(
            rastreamento_id=carga.id,
            status="Em trânsito",
            local=origem,
            observacao=(
                f"Viagem iniciada com o motorista "
                f"{motorista.nome} e o veículo "
                f"{veiculo.placa}."
            )
        )

        db.session.add(historico)
        db.session.commit()

        return jsonify({
            "mensagem": "Viagem despachada com sucesso!",
            "viagem": {
                "id": viagem.id,
                "carga_id": carga.id,
                "codigo_carga": carga.codigo,
                "motorista_id": motorista.id,
                "motorista": motorista.nome,
                "veiculo_id": veiculo.id,
                "veiculo": veiculo.placa,
                "origem": viagem.origem,
                "destino": viagem.destino,
                "status": viagem.status,
                "data_saida": (
                    viagem.data_saida.isoformat()
                    if viagem.data_saida
                    else None
                ),
                "previsao_entrega": (
                    viagem.previsao_entrega.isoformat()
                    if viagem.previsao_entrega
                    else None
                )
            }
        }), 201

    except Exception as erro:
        db.session.rollback()

        print("ERRO AO DESPACHAR VIAGEM:", erro)

        return jsonify({
            "erro": "Não foi possível despachar a viagem."
        }), 500


@admin_viagens_bp.route("/api/admin/viagens/opcoes", methods=["GET"])
@jwt_required()
def api_opcoes_despacho_viagem():
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
            "erro": "Você não possui permissão para acessar viagens."
        }), 403

    status_viagem_ativos = [
        "Planejada",
        "Em andamento",
        "Em coleta",
        "Carregando",
        "Em trânsito",
        "Parada operacional",
        "Saiu para entrega"
    ]

    cargas_ocupadas = db.session.query(
        Viagem.rastreamento_id
    ).filter(
        Viagem.status.in_(status_viagem_ativos)
    )

    motoristas_ocupados = db.session.query(
        Viagem.motorista_id
    ).filter(
        Viagem.status.in_(status_viagem_ativos)
    )

    veiculos_ocupados = db.session.query(
        Viagem.veiculo_id
    ).filter(
        Viagem.status.in_(status_viagem_ativos)
    )

    cargas = Rastreamento.query.filter(
        ~Rastreamento.id.in_(cargas_ocupadas),
        ~Rastreamento.status.in_([
            "Entregue",
            "Cancelada"
        ])
    ).order_by(
        Rastreamento.id.desc()
    ).all()

    motoristas = Motorista.query.filter(
        ~Motorista.id.in_(motoristas_ocupados),
        Motorista.status == "Ativo"
    ).order_by(
        Motorista.nome.asc()
    ).all()

    veiculos = Veiculo.query.filter(
        ~Veiculo.id.in_(veiculos_ocupados),
        ~Veiculo.status.in_([
            "Inativo",
            "Manutenção",
            "Em manutenção",
            "Em viagem"
        ])
    ).order_by(
        Veiculo.placa.asc()
    ).all()

    return jsonify({
        "cargas": [
            {
                "id": carga.id,
                "codigo": carga.codigo,
                "cliente": carga.cliente,
                "local_atual": carga.local_atual,
                "destino": carga.destino
            }
            for carga in cargas
        ],

        "motoristas": [
            {
                "id": motorista.id,
                "nome": motorista.nome,
                "status": motorista.status,
                "disponibilidade": motorista.disponibilidade
            }
            for motorista in motoristas
        ],

        "veiculos": [
            {
                "id": veiculo.id,
                "placa": veiculo.placa,
                "modelo": veiculo.modelo,
                "status": veiculo.status
            }
            for veiculo in veiculos
        ]
    }), 200
