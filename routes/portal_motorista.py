import math
from datetime import datetime, timezone

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from extensions import db
from models.comprovantes import (
    ArquivoComprovanteViagem,
    ComprovanteEntrega,
)
from models.historicos import HistoricoRastreamento, HistoricoViagem
from models.localizacoes import LocalizacaoMotorista, LocalizacaoViagem
from models.ocorrencias import OcorrenciaViagem
from models.operacao import Rastreamento, Viagem
from models.recursos import Motorista, Veiculo
from models.usuarios import UsuarioSistema
from services.historicos import registrar_historico
from services.inicio_viagem import registrar_dados_inicio_execucao
from services.auditoria import registrar_log
from services.rate_limit import verificar_limite
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
from utils.datas import (
    exibir_data_operacional_local,
    formatar_data_brasilia,
    formatar_instante_utc_brasilia,
    serializar_instante_utc,
)
from utils.constantes import (
    TRANSICOES_VIAGEM,
    opcoes_proximo_status,
    transicao_viagem_permitida,
)


portal_motorista_bp = Blueprint(
    "portal_motorista",
    __name__
)


@portal_motorista_bp.route(
    "/api/motorista/minhas-viagens/<int:id>/status",
    methods=["POST"]
)
@jwt_required()
def api_atualizar_status_viagem_motorista(id):
    usuario_id = int(get_jwt_identity())

    usuario_sistema = db.session.get(
        UsuarioSistema,
        usuario_id
    )

    if not usuario_sistema or not usuario_sistema.ativo:
        return jsonify({
            "erro": "Usuário não autorizado."
        }), 401

    if str(usuario_sistema.perfil).strip().lower() != "motorista":
        return jsonify({
            "erro": "Acesso permitido somente para motoristas."
        }), 403

    motorista = Motorista.query.filter_by(
        usuario_sistema_id=usuario_sistema.id
    ).first()

    if not motorista:
        return jsonify({
            "erro": "O usuário não está vinculado a um motorista."
        }), 404

    if str(motorista.status).strip().lower() == "inativo":
        return jsonify({
            "erro": "Este motorista está inativo."
        }), 403

    viagem = Viagem.query.filter_by(
        id=id,
        motorista_id=motorista.id
    ).first()

    if not viagem:
        return jsonify({
            "erro": (
                "Viagem não encontrada ou não pertence "
                "a este motorista."
            )
        }), 404

    status_atual = str(viagem.status).strip().lower()

    if status_atual == "cancelada":
        return jsonify({
            "erro": "Não é possível alterar o status de uma viagem cancelada."
        }), 409

    if status_atual == "entregue":
        return jsonify({
            "erro": "Não é possível alterar o status de uma viagem já entregue."
        }), 409

    dados = request.get_json(silent=True) or {}

    novo_status = str(
        dados.get("status", "")
    ).strip()

    status_permitidos_motorista = opcoes_proximo_status(viagem.status)

    if novo_status not in status_permitidos_motorista:
        return jsonify({
            "erro": (
                "Este status não pode ser definido "
                "pelo motorista."
            )
        }), 400

    if novo_status not in status_permitidos_motorista or not transicao_viagem_permitida(viagem.status, novo_status):
        return jsonify({
            "erro": (
                f"Transição de '{viagem.status}' para "
                f"'{novo_status}' não permitida."
            )
        }), 409

    carga = db.session.get(
        Rastreamento,
        viagem.rastreamento_id
    )

    veiculo = db.session.get(
        Veiculo,
        viagem.veiculo_id
    )

    if veiculo and veiculo_possui_status_especial(veiculo):
        return jsonify({
            "erro": (
                "Não é possível atualizar a operação com veículo "
                "inativo ou em manutenção."
            )
        }), 409

    try:
        iniciou_execucao = (
            str(viagem.status).strip().lower() == "planejada"
            and novo_status == "Em trânsito"
        )
        if iniciou_execucao:
            registrar_dados_inicio_execucao(viagem, carga)

        viagem.status = novo_status

        # Status operacional = motorista em viagem.
        motorista.disponibilidade = "Em viagem"

        if veiculo:
            veiculo.status = "Em viagem"

        # Sincroniza também a carga.
        if carga:
            carga.status = novo_status

            if hasattr(carga, "ultima_atualizacao"):
                carga.ultima_atualizacao = datetime.utcnow()

        historico = HistoricoViagem(
            viagem_id=viagem.id,
            status="STATUS",
            observacao=(
                f"Status alterado para {novo_status} "
                "pelo motorista."
            )
        )

        db.session.add(historico)

        if carga:
            historico_rastreamento = HistoricoRastreamento(
                rastreamento_id=carga.id,
                status=novo_status,
                local=carga.local_atual,
                observacao=(
                    f"Status da viagem alterado para {novo_status} "
                    "pelo motorista."
                )
            )

            db.session.add(historico_rastreamento)

        registrar_log(
            acao="Alteração de status de viagem pelo motorista",
            detalhes=f"Motorista {usuario_sistema.nome} alterou a viagem {viagem.id}.",
            modulo="Viagens",
            entidade="Viagem",
            entidade_id=viagem.id,
            antes={"status": status_atual},
            depois={"status": viagem.status},
            usuario_id=usuario_sistema.id,
            usuario_nome=usuario_sistema.nome,
            perfil=usuario_sistema.perfil
        )
        db.session.commit()

        return jsonify({
            "mensagem": "Status atualizado com sucesso!",
            "status": viagem.status,
            "disponibilidade_motorista": (
                motorista.disponibilidade
            )
        }), 200

    except Exception as erro:
        db.session.rollback()

        print(
            "ERRO AO ATUALIZAR STATUS PELO MOTORISTA:",
            erro
        )

        return jsonify({
            "erro": "Não foi possível atualizar o status."
        }), 500


@portal_motorista_bp.route(
    "/api/motorista/minhas-viagens/<int:id>/ocorrencias",
    methods=["GET"]
)
@jwt_required()
def api_ocorrencias_viagem_motorista(id):
    usuario_id = int(get_jwt_identity())

    usuario_sistema = db.session.get(
        UsuarioSistema,
        usuario_id
    )

    if not usuario_sistema or not usuario_sistema.ativo:
        return jsonify({
            "erro": "Usuário não autorizado."
        }), 401

    if str(usuario_sistema.perfil).strip().lower() != "motorista":
        return jsonify({
            "erro": "Acesso permitido somente para motoristas."
        }), 403

    motorista = Motorista.query.filter_by(
        usuario_sistema_id=usuario_sistema.id
    ).first()

    if not motorista:
        return jsonify({
            "erro": "O usuário não está vinculado a um motorista."
        }), 404

    if str(motorista.status).strip().lower() == "inativo":
        return jsonify({
            "erro": "Este motorista está inativo."
        }), 403

    viagem = Viagem.query.filter_by(
        id=id,
        motorista_id=motorista.id
    ).first()

    if not viagem:
        return jsonify({
            "erro": (
                "Viagem não encontrada ou não pertence "
                "a este motorista."
            )
        }), 404

    ocorrencias = OcorrenciaViagem.query.filter_by(
        viagem_id=viagem.id
    ).order_by(
        OcorrenciaViagem.data_criacao.desc()
    ).all()

    lista = []

    for item in ocorrencias:
        lista.append({
            "id": item.id,
            "descricao": item.descricao,
            "data": (
                item.data_criacao.strftime(
                    "%d/%m/%Y %H:%M"
                )
                if item.data_criacao
                else ""
            ),
            "data_iso": (
                item.data_criacao.isoformat()
                if item.data_criacao
                else None
            )
        })

    return jsonify(lista), 200


@portal_motorista_bp.route(
    "/api/motorista/minhas-viagens/<int:id>/comprovante",
    methods=["GET"]
)
@jwt_required()
def api_consultar_comprovante_motorista(id):
    usuario_id = int(get_jwt_identity())

    usuario_sistema = db.session.get(
        UsuarioSistema,
        usuario_id
    )

    if not usuario_sistema or not usuario_sistema.ativo:
        return jsonify({
            "erro": "Usuário não autorizado."
        }), 401

    if str(usuario_sistema.perfil).strip().lower() != "motorista":
        return jsonify({
            "erro": "Acesso permitido somente para motoristas."
        }), 403

    motorista = Motorista.query.filter_by(
        usuario_sistema_id=usuario_sistema.id
    ).first()

    if not motorista:
        return jsonify({
            "erro": "O usuário não está vinculado a um motorista."
        }), 404

    if str(motorista.status).strip().lower() == "inativo":
        return jsonify({
            "erro": "Este motorista está inativo."
        }), 403

    viagem = Viagem.query.filter_by(
        id=id,
        motorista_id=motorista.id
    ).first()

    if not viagem:
        return jsonify({
            "erro": (
                "Viagem não encontrada ou não pertence "
                "a este motorista."
            )
        }), 404

    comprovante = ComprovanteEntrega.query.filter_by(
        viagem_id=viagem.id
    ).first()

    if not comprovante:
        return jsonify({}), 200

    return jsonify({
        "id": comprovante.id,
        "viagem_id": comprovante.viagem_id,
        "recebedor": comprovante.recebedor,
        "observacao": comprovante.observacao or "",
        "data_entrega": formatar_instante_utc_brasilia(
            comprovante.data_entrega
        )
    }), 200


@portal_motorista_bp.route(
    "/api/motorista/minhas-viagens/<int:id>/comprovante/arquivo",
    methods=["POST"]
)
@jwt_required()
def api_upload_arquivo_comprovante_motorista(id):
    usuario_id = int(get_jwt_identity())
    resposta_limite = verificar_limite([
        (f"upload:usuario:{usuario_id}", 10, 60)
    ])
    if resposta_limite:
        return resposta_limite

    usuario_sistema = db.session.get(
        UsuarioSistema,
        usuario_id
    )

    if not usuario_sistema or not usuario_sistema.ativo:
        return jsonify({
            "erro": "Usuário não autorizado."
        }), 401

    if str(usuario_sistema.perfil).strip().lower() != "motorista":
        return jsonify({
            "erro": "Acesso permitido somente para motoristas."
        }), 403

    motorista = Motorista.query.filter_by(
        usuario_sistema_id=usuario_sistema.id
    ).first()

    if not motorista:
        return jsonify({
            "erro": "O usuário não está vinculado a um motorista."
        }), 404

    if str(motorista.status).strip().lower() == "inativo":
        return jsonify({
            "erro": "Este motorista está inativo."
        }), 403

    viagem = Viagem.query.filter_by(
        id=id,
        motorista_id=motorista.id
    ).first()

    if not viagem:
        return jsonify({
            "erro": (
                "Viagem não encontrada ou não pertence "
                "a este motorista."
            )
        }), 404

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
        return jsonify({
            "erro": "Nenhum arquivo enviado."
        }), 400

    caminho = None

    try:
        nome_seguro, nome_final, caminho = salvar_arquivo_upload(
            arquivo,
            current_app.config["UPLOAD_FOLDER"],
            current_app.config["ALLOWED_EXTENSIONS"],
            current_app.config["UPLOAD_MAX_FILE_SIZE"]
        )

        registro = ArquivoComprovanteViagem(
            viagem_id=viagem.id,
            nome_arquivo=nome_final
        )

        historico = HistoricoViagem(
            viagem_id=viagem.id,
            status="Comprovante anexado",
            observacao=(
                f"Arquivo anexado pelo motorista: "
                f"{nome_seguro}"
            )
        )

        db.session.add(registro)
        db.session.add(historico)
        db.session.flush()
        registrar_log(
            acao="Upload de comprovante pelo motorista",
            detalhes=f"Comprovante anexado à viagem {viagem.id}.",
            modulo="Comprovantes",
            entidade="ArquivoComprovanteViagem",
            entidade_id=registro.id,
            depois={"viagem_id": viagem.id, "arquivo_criado": True},
            usuario_id=usuario_sistema.id,
            usuario_nome=usuario_sistema.nome,
            perfil=usuario_sistema.perfil
        )
        db.session.commit()

        return jsonify({
            "mensagem": (
                "Arquivo do comprovante enviado "
                "com sucesso!"
            )
        }), 201

    except ErroValidacaoArquivo as erro:
        return jsonify({"erro": erro.mensagem}), erro.status_code
    except Exception as erro:
        db.session.rollback()
        remover_arquivo_criado(caminho, current_app.logger)
        current_app.logger.exception(
            "Erro ao persistir comprovante enviado pelo motorista."
        )

        return jsonify({
            "erro": "Não foi possível enviar o arquivo."
        }), 500


@portal_motorista_bp.route(
    "/api/motorista/minhas-viagens/<int:id>/comprovantes/arquivos",
    methods=["GET"]
)
@jwt_required()
def api_listar_arquivos_comprovante_motorista(id):
    usuario_id = int(get_jwt_identity())

    usuario_sistema = db.session.get(
        UsuarioSistema,
        usuario_id
    )

    if not usuario_sistema or not usuario_sistema.ativo:
        return jsonify({
            "erro": "Usuário não autorizado."
        }), 401

    if str(usuario_sistema.perfil).strip().lower() != "motorista":
        return jsonify({
            "erro": "Acesso permitido somente para motoristas."
        }), 403

    motorista = Motorista.query.filter_by(
        usuario_sistema_id=usuario_sistema.id
    ).first()

    if not motorista:
        return jsonify({
            "erro": "O usuário não está vinculado a um motorista."
        }), 404

    if str(motorista.status).strip().lower() == "inativo":
        return jsonify({
            "erro": "Este motorista está inativo."
        }), 403

    viagem = Viagem.query.filter_by(
        id=id,
        motorista_id=motorista.id
    ).first()

    if not viagem:
        return jsonify({
            "erro": (
                "Viagem não encontrada ou não pertence "
                "a este motorista."
            )
        }), 404

    arquivos = ArquivoComprovanteViagem.query.filter_by(
        viagem_id=viagem.id
    ).order_by(
        ArquivoComprovanteViagem.data_upload.desc()
    ).all()

    lista = []

    for arquivo in arquivos:
        lista.append({
            "id": arquivo.id,
            "nome_arquivo": arquivo.nome_arquivo,
            "data_upload": formatar_instante_utc_brasilia(
                arquivo.data_upload
            ),
            "download_endpoint": (
                f"/api/comprovantes/arquivos/{arquivo.id}/download"
            )
        })

    return jsonify(lista), 200


@portal_motorista_bp.route(
    "/api/motorista/minhas-viagens/<int:id>/localizacoes",
    methods=["GET"]
)
@jwt_required()
def api_listar_localizacoes_motorista(id):
    usuario_id = int(get_jwt_identity())

    usuario_sistema = db.session.get(
        UsuarioSistema,
        usuario_id
    )

    if not usuario_sistema or not usuario_sistema.ativo:
        return jsonify({
            "erro": "Usuário não autorizado."
        }), 401

    if str(usuario_sistema.perfil).strip().lower() != "motorista":
        return jsonify({
            "erro": "Acesso permitido somente para motoristas."
        }), 403

    motorista = Motorista.query.filter_by(
        usuario_sistema_id=usuario_sistema.id
    ).first()

    if not motorista:
        return jsonify({
            "erro": "O usuário não está vinculado a um motorista."
        }), 404

    if str(motorista.status).strip().lower() == "inativo":
        return jsonify({
            "erro": "Este motorista está inativo."
        }), 403

    viagem = Viagem.query.filter_by(
        id=id,
        motorista_id=motorista.id
    ).first()

    if not viagem:
        return jsonify({
            "erro": (
                "Viagem não encontrada ou não pertence "
                "a este motorista."
            )
        }), 404

    localizacoes = LocalizacaoViagem.query.filter_by(
        viagem_id=viagem.id
    ).order_by(
        LocalizacaoViagem.data_registro.desc()
    ).all()

    lista = []

    for item in localizacoes:
        lista.append({
            "id": item.id,
            "localizacao": item.localizacao,
            "observacao": item.observacao,
            "data_registro": formatar_data_brasilia(
    item.data_registro
)
        })

    return jsonify(lista), 200


@portal_motorista_bp.route(
    "/api/motorista/minhas-viagens/<int:id>/localizacoes",
    methods=["POST"]
)
@jwt_required()
def api_criar_localizacao_motorista(id):
    usuario_id = int(get_jwt_identity())

    usuario_sistema = db.session.get(
        UsuarioSistema,
        usuario_id
    )

    if not usuario_sistema or not usuario_sistema.ativo:
        return jsonify({
            "erro": "Usuário não autorizado."
        }), 401

    if str(usuario_sistema.perfil).strip().lower() != "motorista":
        return jsonify({
            "erro": "Acesso permitido somente para motoristas."
        }), 403

    motorista = Motorista.query.filter_by(
        usuario_sistema_id=usuario_sistema.id
    ).first()

    if not motorista:
        return jsonify({
            "erro": "O usuário não está vinculado a um motorista."
        }), 404

    if str(motorista.status).strip().lower() == "inativo":
        return jsonify({
            "erro": "Este motorista está inativo."
        }), 403

    viagem = Viagem.query.filter_by(
        id=id,
        motorista_id=motorista.id
    ).first()

    if not viagem:
        return jsonify({
            "erro": (
                "Viagem não encontrada ou não pertence "
                "a este motorista."
            )
        }), 404

    dados = request.get_json(silent=True) or {}

    localizacao_texto = str(
        dados.get("localizacao", "")
    ).strip()

    observacao = str(
        dados.get("observacao", "")
    ).strip()

    if not localizacao_texto:
        return jsonify({
            "erro": "Informe a localização."
        }), 400

    try:
        carga = db.session.get(
            Rastreamento,
            viagem.rastreamento_id
        )
        local_anterior = carga.local_atual if carga else None

        localizacao = LocalizacaoViagem(
            viagem_id=viagem.id,
            localizacao=localizacao_texto,
            observacao=observacao
        )

        db.session.add(localizacao)

        historico = HistoricoViagem(
            viagem_id=viagem.id,
            status="Localização atualizada",
            observacao=localizacao_texto
        )

        db.session.add(historico)

        if carga:
            carga.local_atual = localizacao_texto
            carga.ultima_atualizacao = datetime.utcnow()

            if local_anterior != localizacao_texto:
                historico_rastreamento = HistoricoRastreamento(
                    rastreamento_id=carga.id,
                    status=carga.status,
                    local=localizacao_texto,
                    observacao=observacao
                )
                db.session.add(historico_rastreamento)

        db.session.commit()

        return jsonify({
            "mensagem": "Localização registrada com sucesso!"
        }), 201

    except Exception as erro:
        db.session.rollback()

        print(
            "ERRO AO REGISTRAR LOCALIZAÇÃO DO MOTORISTA:",
            erro
        )

        return jsonify({
            "erro": "Não foi possível registrar a localização."
        }), 500


@portal_motorista_bp.route(
    "/api/motorista/minhas-viagens/<int:id>/localizacoes/gps",
    methods=["POST"]
)
@jwt_required()
def api_registrar_localizacao_gps_motorista(id):
    usuario_id = int(get_jwt_identity())
    usuario_sistema = db.session.get(UsuarioSistema, usuario_id)

    if not usuario_sistema or not usuario_sistema.ativo:
        return jsonify({"erro": "UsuÃ¡rio nÃ£o autorizado."}), 401

    if str(usuario_sistema.perfil).strip().lower() != "motorista":
        return jsonify({
            "erro": "Acesso permitido somente para motoristas."
        }), 403

    motorista = Motorista.query.filter_by(
        usuario_sistema_id=usuario_sistema.id
    ).first()

    if not motorista:
        return jsonify({
            "erro": "O usuÃ¡rio nÃ£o estÃ¡ vinculado a um motorista."
        }), 404

    if str(motorista.status).strip().lower() == "inativo":
        return jsonify({"erro": "Este motorista estÃ¡ inativo."}), 403

    viagem = Viagem.query.filter_by(
        id=id,
        motorista_id=motorista.id
    ).first()

    if not viagem:
        return jsonify({
            "erro": (
                "Viagem nÃ£o encontrada ou nÃ£o pertence "
                "a este motorista."
            )
        }), 404

    dados = request.get_json(silent=True) or {}
    latitude = dados.get("latitude")
    longitude = dados.get("longitude")
    instante_texto = dados.get("captured_at")

    if latitude is None or longitude is None or not instante_texto:
        return jsonify({
            "erro": "Informe latitude, longitude e instante da captura."
        }), 400

    if (
        isinstance(latitude, bool)
        or isinstance(longitude, bool)
        or not isinstance(latitude, (int, float))
        or not isinstance(longitude, (int, float))
    ):
        return jsonify({"erro": "Coordenadas invÃ¡lidas."}), 400

    latitude = float(latitude)
    longitude = float(longitude)
    if (
        not math.isfinite(latitude)
        or not math.isfinite(longitude)
        or not -90 <= latitude <= 90
        or not -180 <= longitude <= 180
    ):
        return jsonify({"erro": "Coordenadas invÃ¡lidas."}), 400

    if not isinstance(instante_texto, str):
        return jsonify({"erro": "Instante da captura invÃ¡lido."}), 400

    try:
        instante = datetime.fromisoformat(
            instante_texto.strip().replace("Z", "+00:00")
        )
    except ValueError:
        return jsonify({"erro": "Instante da captura invÃ¡lido."}), 400

    if instante.tzinfo is None or instante.utcoffset() is None:
        return jsonify({"erro": "Instante da captura deve incluir fuso UTC."}), 400

    instante_utc_naive = instante.astimezone(timezone.utc).replace(tzinfo=None)

    try:
        registro = LocalizacaoMotorista(
            motorista_id=motorista.id,
            rastreamento_id=viagem.rastreamento_id,
            latitude=str(latitude),
            longitude=str(longitude),
            data_registro=instante_utc_naive,
        )
        db.session.add(registro)
        db.session.commit()

        return jsonify({
            "mensagem": "LocalizaÃ§Ã£o atualizada.",
            "id": registro.id,
            "data_registro": serializar_instante_utc(
                registro.data_registro
            ),
        }), 201
    except Exception:
        db.session.rollback()
        current_app.logger.exception(
            "Falha ao registrar localizaÃ§Ã£o GPS do motorista."
        )
        return jsonify({
            "erro": "NÃ£o foi possÃ­vel registrar a localizaÃ§Ã£o."
        }), 500


@portal_motorista_bp.route(
    "/api/motorista/minhas-viagens/<int:id>",
    methods=["GET"]
)
@jwt_required()
def api_detalhe_viagem_motorista(id):
    usuario_id = int(get_jwt_identity())

    usuario_sistema = db.session.get(
        UsuarioSistema,
        usuario_id
    )

    if not usuario_sistema or not usuario_sistema.ativo:
        return jsonify({
            "erro": "Usuário não autorizado."
        }), 401

    if str(usuario_sistema.perfil).strip().lower() != "motorista":
        return jsonify({
            "erro": "Acesso permitido somente para motoristas."
        }), 403

    motorista = Motorista.query.filter_by(
        usuario_sistema_id=usuario_sistema.id
    ).first()

    if not motorista:
        return jsonify({
            "erro": "O usuário não está vinculado a um motorista."
        }), 404

    if str(motorista.status).strip().lower() == "inativo":
        return jsonify({
            "erro": "Este motorista está inativo."
        }), 403

    viagem = Viagem.query.filter_by(
        id=id,
        motorista_id=motorista.id
    ).first()

    if not viagem:
        return jsonify({
            "erro": (
                "Viagem não encontrada ou não pertence "
                "a este motorista."
            )
        }), 404

    return jsonify({
        "id": viagem.id,
        "codigo_carga": (
            viagem.carga.codigo
            if viagem.carga
            else ""
        ),
        "cliente": (
            viagem.carga.cliente
            if viagem.carga
            else ""
        ),
        "motorista": (
            viagem.motorista.nome
            if viagem.motorista
            else ""
        ),
        "veiculo": (
            viagem.veiculo.placa
            if viagem.veiculo
            else ""
        ),
        "origem": viagem.origem,
        "destino": viagem.destino,
        "status": viagem.status,
        "data_saida": formatar_instante_utc_brasilia(
            viagem.data_saida
        ),
        "previsao_entrega": exibir_data_operacional_local(
            viagem.previsao_entrega
        ),
        "data_criacao": formatar_instante_utc_brasilia(
            viagem.data_criacao
        ),
        "data_criacao_iso": serializar_instante_utc(
            viagem.data_criacao
        )
    }), 200


@portal_motorista_bp.route(
    "/api/motorista/minhas-viagens/<int:id>/historico",
    methods=["GET"]
)
@jwt_required()
def api_historico_viagem_motorista(id):
    usuario_id = int(get_jwt_identity())

    usuario_sistema = db.session.get(
        UsuarioSistema,
        usuario_id
    )

    if not usuario_sistema or not usuario_sistema.ativo:
        return jsonify({
            "erro": "Usuário não autorizado."
        }), 401

    if str(usuario_sistema.perfil).strip().lower() != "motorista":
        return jsonify({
            "erro": "Acesso permitido somente para motoristas."
        }), 403

    motorista = Motorista.query.filter_by(
        usuario_sistema_id=usuario_sistema.id
    ).first()

    if not motorista:
        return jsonify({
            "erro": "O usuário não está vinculado a um motorista."
        }), 404

    if str(motorista.status).strip().lower() == "inativo":
        return jsonify({
            "erro": "Este motorista está inativo."
        }), 403

    viagem = Viagem.query.filter_by(
        id=id,
        motorista_id=motorista.id
    ).first()

    if not viagem:
        return jsonify({
            "erro": "Viagem não encontrada ou não pertence a este motorista."
        }), 404

    historicos = HistoricoViagem.query.filter_by(
        viagem_id=viagem.id
    ).order_by(
        HistoricoViagem.data_evento.desc()
    ).all()

    lista = []

    for item in historicos:
     lista.append({
        "id": item.id,
        "status": item.status,
        "observacao": item.observacao,
        "data_evento": formatar_data_brasilia(
            item.data_evento
        )
    })
    return jsonify(lista), 200


@portal_motorista_bp.route(
    "/api/motorista/minhas-viagens/<int:id>/ocorrencias",
    methods=["POST"]
)
@jwt_required()
def api_criar_ocorrencia_motorista(id):
    usuario_id = int(get_jwt_identity())

    usuario_sistema = db.session.get(
        UsuarioSistema,
        usuario_id
    )

    if not usuario_sistema or not usuario_sistema.ativo:
        return jsonify({
            "erro": "Usuário não autorizado."
        }), 401

    if str(usuario_sistema.perfil).strip().lower() != "motorista":
        return jsonify({
            "erro": "Acesso permitido somente para motoristas."
        }), 403

    motorista = Motorista.query.filter_by(
        usuario_sistema_id=usuario_sistema.id
    ).first()

    if not motorista:
        return jsonify({
            "erro": "O usuário não está vinculado a um motorista."
        }), 404

    if str(motorista.status).strip().lower() == "inativo":
        return jsonify({
            "erro": "Este motorista está inativo."
        }), 403

    viagem = Viagem.query.filter_by(
        id=id,
        motorista_id=motorista.id
    ).first()

    if not viagem:
        return jsonify({
            "erro": (
                "Viagem não encontrada ou não pertence "
                "a este motorista."
            )
        }), 404

    dados = request.get_json(silent=True) or {}

    descricao = str(
        dados.get("descricao", "")
    ).strip()

    if not descricao:
        return jsonify({
            "erro": "Informe a descrição da ocorrência."
        }), 400

    try:
        ocorrencia = OcorrenciaViagem(
            viagem_id=viagem.id,
            descricao=descricao
        )

        db.session.add(ocorrencia)

        historico = HistoricoViagem(
            viagem_id=viagem.id,
            status="Ocorrência",
            observacao=descricao
        )

        db.session.add(historico)

        registrar_log(
            acao="Criação de ocorrência pelo motorista",
            detalhes=f"Ocorrência criada na viagem {viagem.id}.",
            modulo="Ocorrências",
            entidade="OcorrenciaViagem",
            entidade_id=ocorrencia.id,
            depois={"descricao": descricao},
            usuario_id=usuario_sistema.id,
            usuario_nome=usuario_sistema.nome,
            perfil=usuario_sistema.perfil
        )
        db.session.commit()

        return jsonify({
            "mensagem": "Ocorrência registrada!"
        }), 201

    except Exception as erro:
        db.session.rollback()

        print(
            "ERRO AO REGISTRAR OCORRÊNCIA DO MOTORISTA:",
            erro
        )

        return jsonify({
            "erro": "Não foi possível registrar a ocorrência."
        }), 500


@portal_motorista_bp.route(
    "/api/motorista/minhas-viagens",
    methods=["GET"]
)
@jwt_required()
def api_motorista_minhas_viagens():
    usuario_id = int(get_jwt_identity())

    usuario_sistema = db.session.get(
        UsuarioSistema,
        usuario_id
    )

    if not usuario_sistema or not usuario_sistema.ativo:
        return jsonify({
            "erro": "Usuário não autorizado."
        }), 401

    if str(usuario_sistema.perfil).strip().lower() != "motorista":
        return jsonify({
            "erro": "Acesso permitido somente para motoristas."
        }), 403

    motorista = Motorista.query.filter_by(
        usuario_sistema_id=usuario_sistema.id
    ).first()

    if not motorista:
        return jsonify({
            "erro": "O usuário não está vinculado a um motorista."
        }), 404

    if str(motorista.status).strip().lower() == "inativo":
        return jsonify({
            "erro": "Este motorista está inativo."
        }), 403

    viagens = (
        Viagem.query
        .filter_by(
            motorista_id=motorista.id
        )
        .order_by(
            Viagem.data_criacao.desc()
        )
        .all()
    )

    lista = []

    for viagem in viagens:
        lista.append({
            "id": viagem.id,
            "codigo": viagem.codigo or "",
            "origem": viagem.origem,
            "destino": viagem.destino,
            "status": viagem.status,
            "data_saida": formatar_instante_utc_brasilia(
                viagem.data_saida
            ),
            "previsao_entrega": exibir_data_operacional_local(
                viagem.previsao_entrega
            ),
            "carga_codigo": (
                viagem.carga.codigo
                if viagem.carga
                else ""
            ),
            "veiculo": (
                viagem.veiculo.placa
                if viagem.veiculo
                else ""
            ),
        })

    return jsonify(lista), 200


@portal_motorista_bp.route(
    "/api/motorista/minhas-viagens/<int:viagem_id>/finalizar",
    methods=["POST"]
)
@jwt_required()
def api_finalizar_viagem_motorista(viagem_id):
    usuario_id = int(get_jwt_identity())

    usuario = db.session.get(
        UsuarioSistema,
        usuario_id
    )

    if not usuario or not usuario.ativo:
        return jsonify({
            "erro": "Usuário não autorizado."
        }), 401

    if str(usuario.perfil).strip().lower() != "motorista":
        return jsonify({
            "erro": "Acesso permitido somente para motoristas."
        }), 403

    motorista_logado = Motorista.query.filter_by(
        usuario_sistema_id=usuario.id
    ).first()

    if not motorista_logado:
        return jsonify({
            "erro": "O usuário não está vinculado a um motorista."
        }), 404

    if str(motorista_logado.status).strip().lower() == "inativo":
        return jsonify({
            "erro": "Este motorista está inativo."
        }), 403

    viagem = Viagem.query.filter_by(
        id=viagem_id,
        motorista_id=motorista_logado.id
    ).first()

    if not viagem:
        return jsonify({
            "erro": (
                "Viagem não encontrada ou não pertence "
                "a este motorista."
            )
        }), 404

    status_atual = str(viagem.status).strip().lower()

    if status_atual == "cancelada":
        return jsonify({
            "erro": "Não é possível finalizar uma viagem cancelada."
        }), 409

    if status_atual == "entregue":
        return jsonify({
            "erro": "Esta viagem já foi finalizada."
        }), 409

    if viagem.status != "Saiu para entrega":
        return jsonify({
            "erro": "A viagem precisa estar em 'Saiu para entrega' para ser finalizada."
        }), 409

    dados = request.get_json(silent=True) or {}

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

    veiculo = db.session.get(
        Veiculo,
        viagem.veiculo_id
    )

    if not carga:
        return jsonify({
            "erro": (
                "A carga vinculada à viagem "
                "não foi encontrada."
            )
        }), 404

    if str(carga.status).strip().lower() == "cancelada":
        return jsonify({
            "erro": "Não é possível finalizar uma viagem cancelada."
        }), 409

    try:
        comprovante_existente = (
            ComprovanteEntrega.query
            .filter_by(
                viagem_id=viagem.id
            )
            .first()
        )

        if comprovante_existente:
            return jsonify({
                "erro": (
                    "Esta viagem já possui um "
                    "comprovante de entrega."
                )
            }), 409

        comprovante = ComprovanteEntrega(
            viagem_id=viagem.id,
            recebedor=recebedor,
            observacao=observacao,
            data_entrega=datetime.utcnow()
        )

        db.session.add(comprovante)

        # Finaliza viagem e carga
        viagem.status = "Entregue"
        carga.status = "Entregue"

        if hasattr(carga, "ultima_atualizacao"):
            carga.ultima_atualizacao = datetime.utcnow()

        recalcular_disponibilidade_motorista(
            motorista_logado,
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
                f"Entrega finalizada pelo motorista. "
                f"Recebedor: {recebedor}."
                + (
                    f" Observação: {observacao}"
                    if observacao
                    else ""
                )
            )
        )

        # ... históricos ...

        db.session.flush()
        registrar_log(
            acao="Finalização de viagem pelo motorista",
            detalhes=f"Motorista {usuario.nome} finalizou a viagem {viagem.id}.",
            modulo="Viagens",
            entidade="Viagem",
            entidade_id=viagem.id,
            antes={"status": status_atual, "comprovante": False},
            depois={
                "status": viagem.status,
                "comprovante": True,
                "comprovante_id": comprovante.id,
                "recebedor": recebedor,
            },
            usuario_id=usuario.id,
            usuario_nome=usuario.nome,
            perfil=usuario.perfil
        )

        print(
            "ANTES DO COMMIT:",
            motorista_logado.id,
            motorista_logado.nome,
            motorista_logado.status,
            motorista_logado.disponibilidade
        )

        db.session.commit()

        db.session.refresh(motorista_logado)

        print(
            "DEPOIS DO COMMIT:",
            motorista_logado.id,
            motorista_logado.nome,
            motorista_logado.status,
            motorista_logado.disponibilidade
        )

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
            "ERRO AO FINALIZAR ENTREGA PELO MOTORISTA:",
            erro
        )

        return jsonify({
            "erro": "Não foi possível finalizar a entrega."
        }), 500
