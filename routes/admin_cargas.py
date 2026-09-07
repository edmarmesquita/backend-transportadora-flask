from datetime import datetime

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from extensions import db
from models.clientes import Cliente
from models.historicos import HistoricoRastreamento
from models.operacao import Rastreamento, Viagem
from models.recursos import Motorista, Veiculo
from models.usuarios import UsuarioSistema
from services.historicos import registrar_historico
from services.recursos import (
    recalcular_disponibilidade_motorista,
    recalcular_status_veiculo,
)
from services.codigos_rastreamento import gerar_codigo_rastreamento
from utils.constantes import (
    STATUS_CARGA_ATIVOS_RECURSOS,
    STATUS_CARGA_EXCLUSAO_PERMITIDA,
    STATUS_CARGA_INICIAIS,
    STATUS_VIAGEM_ATIVOS_RECURSOS,
    TRANSICOES_CARGA,
    transicao_carga_permitida,
)
from utils.valores import converter_valor_brasileiro


admin_cargas_bp = Blueprint(
    "admin_cargas",
    __name__
)


@admin_cargas_bp.route("/api/admin/cargas", methods=["GET"])
@jwt_required()
def api_admin_cargas():
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
            "erro": "Você não possui permissão para acessar cargas."
        }), 403

    cargas = Rastreamento.query.order_by(
        Rastreamento.ultima_atualizacao.desc()
    ).all()

    lista = []

    for carga in cargas:
        lista.append({
            "id": carga.id,
            "codigo": carga.codigo,
            "cliente": carga.cliente,
            "status": carga.status,
            "local_atual": carga.local_atual,
            "destino": carga.destino,
            "motorista": carga.motorista_relacao.nome if carga.motorista_relacao else "",
            "veiculo": carga.veiculo_relacao.placa if carga.veiculo_relacao else "",
        })

    return lista


@admin_cargas_bp.route("/api/admin/cargas/<int:id>", methods=["GET"])
@jwt_required()
def api_admin_carga_detalhe(id):
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
            "erro": "Você não possui permissão para acessar cargas."
        }), 403

    carga = db.session.get(
        Rastreamento,
        id
    )

    if not carga:
        return jsonify({
            "erro": "Carga não encontrada."
        }), 404

    viagem = Viagem.query.filter_by(
        rastreamento_id=carga.id
    ).first()

    return jsonify({
        "id": carga.id,
        "codigo": carga.codigo,
        "cliente": carga.cliente,
        "cliente_id": carga.cliente_id,
        "local_atual": carga.local_atual,
        "destino": carga.destino,
        "motorista_id": carga.motorista_id,
        "motorista": (
            carga.motorista_relacao.nome
            if carga.motorista_relacao
            else ""
        ),
        "veiculo_id": carga.veiculo_id,
        "veiculo": (
            carga.veiculo_relacao.placa
            if carga.veiculo_relacao
            else ""
        ),
        "status": carga.status,
        "ultima_atualizacao": (
            carga.ultima_atualizacao.strftime("%d/%m/%Y %H:%M")
            if carga.ultima_atualizacao
            else ""
        ),
        "valor_frete": carga.valor_frete,
        "status_pagamento": carga.status_pagamento,
        "viagem_id": viagem.id if viagem else None,
    }), 200


@admin_cargas_bp.route("/api/admin/cargas", methods=["POST"])
@jwt_required()
def api_criar_carga():
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
            "erro": "Você não possui permissão para criar cargas."
        }), 403

    dados = request.get_json()

    codigo = gerar_codigo_rastreamento()
    cliente_id_recebido = dados.get("cliente_id")

    if cliente_id_recebido not in [None, ""]:
        try:
            cliente_id = int(cliente_id_recebido)
        except (TypeError, ValueError):
            return {"erro": "Informe um cliente válido."}, 400

        cliente_cadastrado = db.session.get(
            Cliente,
            cliente_id
        )

        if not cliente_cadastrado:
            return {"erro": "Cliente não encontrado."}, 404

        if not cliente_cadastrado.ativo:
            return {"erro": "O cliente informado está inativo."}, 400

        cliente = cliente_cadastrado.razao_social.strip()
    else:
        cliente_id = None
        cliente = dados.get("cliente", "").strip()

    status = dados.get("status", "").strip()

    if status not in STATUS_CARGA_INICIAIS:
        return jsonify({
            "erro": "Status inicial de carga inválido."
        }), 400
    local_atual = dados.get("local_atual", "").strip()
    destino = dados.get("destino", "").strip()

    if not all([codigo, cliente, status, local_atual, destino]):
        return {"erro": "Preencha todos os campos obrigatórios."}, 400

    existente = Rastreamento.query.filter_by(codigo=codigo).first()

    if existente:
        return {"erro": "Já existe uma carga com esse código."}, 400

    nova_carga = Rastreamento()
    nova_carga.codigo = codigo
    nova_carga.cliente = cliente
    nova_carga.cliente_id = cliente_id
    nova_carga.status = status
    nova_carga.local_atual = local_atual
    nova_carga.destino = destino
    nova_carga.ultima_atualizacao = datetime.utcnow()
    nova_carga.valor_frete = converter_valor_brasileiro(
    dados.get("valor_frete")
)
    nova_carga.status_pagamento = dados.get("status_pagamento", "Pendente")

    db.session.add(nova_carga)
    db.session.flush()

    primeiro_evento = HistoricoRastreamento(
    rastreamento_id=nova_carga.id,
    status=nova_carga.status or "Carga criada",
    local=nova_carga.local_atual or "Origem não informada",
    observacao="Carga cadastrada no sistema."
    )

    db.session.add(primeiro_evento)
    db.session.commit()

    return {
        "mensagem": "Carga criada com sucesso!",
        "id": nova_carga.id
    }, 201


@admin_cargas_bp.route("/api/admin/cargas/<int:id>", methods=["PUT"])
@jwt_required()
def api_editar_carga(id):
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
            "erro": "Você não possui permissão para editar cargas."
        }), 403

    carga = Rastreamento.query.get_or_404(id)
    dados = request.get_json() or {}

    cliente_id_recebido = dados.get("cliente_id")

    if cliente_id_recebido not in [None, ""]:
        try:
            cliente_id = int(cliente_id_recebido)
        except (TypeError, ValueError):
            return {"erro": "Informe um cliente válido."}, 400

        cliente_cadastrado = db.session.get(
            Cliente,
            cliente_id
        )

        if not cliente_cadastrado:
            return {"erro": "Cliente não encontrado."}, 404

        if not cliente_cadastrado.ativo:
            return {"erro": "O cliente informado está inativo."}, 400

        cliente = cliente_cadastrado.razao_social.strip()
    else:
        cliente_id = None
        cliente = dados.get("cliente", "").strip()

    # Guarda os dados anteriores antes de alterar
    local_anterior = carga.local_atual

    carga.cliente = cliente

    if cliente_id is not None:
        carga.cliente_id = cliente_id

    carga.local_atual = dados.get("local_atual", "").strip()
    carga.destino = dados.get("destino", "").strip()
    carga.ultima_atualizacao = datetime.utcnow()

    if not all([
        carga.codigo,
        carga.cliente,
        carga.local_atual,
        carga.destino,
    ]):
        return {
            "erro": "Preencha todos os campos obrigatórios."
        }, 400

    carga.valor_frete = converter_valor_brasileiro(
        dados.get("valor_frete")
    )

    carga.status_pagamento = dados.get(
        "status_pagamento",
        "Pendente"
    )

    # Descobre se houve alteração relevante para a timeline
    local_mudou = local_anterior != carga.local_atual

    # Cria evento somente quando a localização mudar
    if local_mudou:
        evento = HistoricoRastreamento(
            rastreamento_id=carga.id,
            status=carga.status,
            local=carga.local_atual,
            observacao=(
                f"Local anterior: {local_anterior or '-'}"
            )
        )

        db.session.add(evento)

    db.session.commit()

    return {
        "mensagem": "Carga atualizada com sucesso!"
    }, 200


@admin_cargas_bp.route(
    "/api/admin/cargas/<int:id>",
    methods=["DELETE"]
)
@jwt_required()
def api_excluir_carga(id):
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
            "erro": "Somente administradores podem excluir cargas."
        }), 403

    carga = db.session.get(
        Rastreamento,
        id
    )

    if not carga:
        return jsonify({
            "erro": "Carga não encontrada."
        }), 404

    if carga.status not in STATUS_CARGA_EXCLUSAO_PERMITIDA:
        return jsonify({
            "erro": (
                f"Não é possível excluir uma carga "
                f"com status '{carga.status}'."
            )
        }), 409

    viagem = Viagem.query.filter_by(
        rastreamento_id=carga.id
    ).first()

    if viagem:
        return jsonify({
            "erro": (
                "Não é possível excluir esta carga "
                "porque ela possui uma viagem vinculada."
            )
        }), 409

    historico = HistoricoRastreamento.query.filter_by(
        rastreamento_id=carga.id
    ).first()

    if historico:
        return jsonify({
            "erro": (
                "Não é possível excluir esta carga "
                "porque ela possui histórico de rastreamento."
            )
        }), 409

    try:
        db.session.delete(carga)
        db.session.commit()

        return jsonify({
            "mensagem": "Carga excluída com sucesso!"
        }), 200

    except Exception as erro:
        db.session.rollback()

        print(
            "ERRO AO EXCLUIR CARGA:",
            erro
        )

        return jsonify({
            "erro": (
                "Não foi possível excluir a carga "
                "porque existem registros vinculados a ela."
            )
        }), 409


@admin_cargas_bp.route(
    "/api/admin/cargas/<int:id>/criar-viagem",
    methods=["POST"]
)
@jwt_required()
def criar_viagem_para_carga(id):
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
            "erro": "Você não possui permissão para criar viagens para cargas."
        }), 403

    carga = Rastreamento.query.get(id)

    if not carga:
        return {
            "mensagem": "Carga não encontrada."
        }, 404

    viagem_existente = Viagem.query.filter_by(
        rastreamento_id=carga.id
    ).first()

    if viagem_existente:
        return {
            "mensagem": "Esta carga já possui uma viagem.",
            "viagem_id": viagem_existente.id
        }, 200

    if not carga.motorista_id:
        return {
            "mensagem": "Atribua um motorista antes de criar a viagem."
        }, 400

    if not carga.veiculo_id:
        return {
            "mensagem": "Atribua um veículo antes de criar a viagem."
        }, 400

    if not carga.local_atual:
        return {
            "mensagem": "A carga não possui uma origem definida."
        }, 400

    if not carga.destino:
        return {
            "mensagem": "A carga não possui um destino definido."
        }, 400

    nova_viagem = Viagem(
        rastreamento_id=carga.id,
        motorista_id=carga.motorista_id,
        veiculo_id=carga.veiculo_id,
        origem=carga.local_atual,
        destino=carga.destino,
        status="Planejada"
    )

    db.session.add(nova_viagem)

    db.session.flush()

    registrar_historico(
        nova_viagem.id,
        "PLANEJAMENTO",
        "Viagem criada para a carga pelo painel administrativo."
    )

    historico_rastreamento = HistoricoRastreamento(
        rastreamento_id=carga.id,
        status=carga.status,
        local=carga.local_atual,
        observacao="Viagem planejada para a carga."
    )

    db.session.add(historico_rastreamento)
    db.session.commit()

    return {
        "mensagem": "Viagem criada com sucesso!",
        "viagem_id": nova_viagem.id
    }, 201


@admin_cargas_bp.route(
    "/api/admin/cargas/<int:id>/atribuir-motorista",
    methods=["PUT"]
)
@jwt_required()
def atribuir_motorista(id):
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
            "erro": "Você não possui permissão para atribuir motoristas."
        }), 403

    dados = request.get_json() or {}

    motorista_id = dados.get("motorista_id")

    if not motorista_id:
        return jsonify({
            "erro": "motorista_id é obrigatório."
        }), 400

    carga = db.session.get(
        Rastreamento,
        id
    )

    if not carga:
        return jsonify({
            "erro": "Carga não encontrada."
        }), 404

    # Viagem vinculada a esta carga, caso exista.
    viagem_atual = Viagem.query.filter_by(
        rastreamento_id=carga.id
    ).first()

    status_carga = str(
        carga.status or ""
    ).strip().lower()

    status_viagem = str(
        viagem_atual.status if viagem_atual else ""
    ).strip().lower()

    if (
        status_carga in ["entregue", "cancelada"]
        or status_viagem in ["entregue", "cancelada"]
    ):
        return jsonify({
            "erro": (
                "Não é possível alterar o motorista de uma "
                "carga com operação finalizada."
            )
        }), 409

    motorista = db.session.get(
        Motorista,
        int(motorista_id)
    )

    if not motorista:
        return jsonify({
            "erro": "Motorista não encontrado."
        }), 404

    if str(motorista.status).strip().lower() == "inativo":
        return jsonify({
            "erro": "O motorista selecionado está inativo."
        }), 400

    status_viagem_ativos = STATUS_VIAGEM_ATIVOS_RECURSOS

    # Verifica se o NOVO motorista
    # já possui outra viagem ativa.
    consulta_viagem = Viagem.query.filter(
        Viagem.motorista_id == motorista.id,
        Viagem.status.in_(status_viagem_ativos)
    )

    if viagem_atual:
        consulta_viagem = consulta_viagem.filter(
            Viagem.id != viagem_atual.id
        )

    viagem_conflitante = consulta_viagem.first()

    if viagem_conflitante:
        return jsonify({
            "erro": (
                "Este motorista já está vinculado "
                "a outra viagem ativa."
            )
        }), 409

    status_carga_ativos = STATUS_CARGA_ATIVOS_RECURSOS

    # Verifica se o NOVO motorista
    # já possui outra carga ativa.
    carga_conflitante = Rastreamento.query.filter(
        Rastreamento.motorista_id == motorista.id,
        Rastreamento.id != carga.id,
        Rastreamento.status.in_(status_carga_ativos)
    ).first()

    if carga_conflitante:
        return jsonify({
            "erro": (
                "Este motorista já está vinculado "
                f"à carga {carga_conflitante.codigo}."
            )
        }), 409

    try:
        # Guarda o motorista anterior
        # ANTES de fazer a troca.
        motorista_anterior_id = carga.motorista_id

        motorista_anterior = None

        if motorista_anterior_id:
            motorista_anterior = db.session.get(
                Motorista,
                motorista_anterior_id
            )

        # Atualiza motorista da carga.
        carga.motorista_id = motorista.id

        # Se a carga já possui viagem,
        # sincroniza o motorista da viagem.
        if viagem_atual:
            viagem_atual.motorista_id = motorista.id

            # Se a viagem está ativa,
            # o novo motorista fica Em viagem.
            operacao_atual_ativa = (
                viagem_atual.status in status_viagem_ativos
                or carga.status in status_carga_ativos
            )

            if operacao_atual_ativa:
                motorista.disponibilidade = "Em viagem"
            else:
                motorista.disponibilidade = "Disponível"

            # Só registra histórico
            # quando realmente houve troca.
            if motorista_anterior_id != motorista.id:
                nome_anterior = (
                    motorista_anterior.nome
                    if motorista_anterior
                    else "Não definido"
                )

                registrar_historico(
                    viagem_atual.id,
                    "MOTORISTA",
                    (
                        f"Motorista alterado de "
                        f"{nome_anterior} para {motorista.nome}."
                    )
                )

        else:
            # Ainda não existe viagem.
            motorista.disponibilidade = (
                "Em viagem"
                if carga.status in status_carga_ativos
                else "Disponível"
            )

        if motorista_anterior_id != motorista.id:
            nome_anterior = (
                motorista_anterior.nome
                if motorista_anterior
                else "Não definido"
            )

            historico_rastreamento = HistoricoRastreamento(
                rastreamento_id=carga.id,
                status=carga.status,
                local=carga.local_atual,
                observacao=(
                    f"Motorista alterado de {nome_anterior} "
                    f"para {motorista.nome}."
                )
            )

            db.session.add(historico_rastreamento)

        # -------------------------------------------------
        # LIBERA O MOTORISTA ANTERIOR
        # -------------------------------------------------

        if (
            motorista_anterior
            and motorista_anterior.id != motorista.id
        ):
            recalcular_disponibilidade_motorista(
                motorista_anterior,
                excluir_viagem_id=(
                    viagem_atual.id
                    if viagem_atual
                    else None
                ),
                excluir_carga_id=carga.id
            )

        db.session.commit()

        return jsonify({
            "mensagem": "Motorista atribuído com sucesso!",
            "carga_id": carga.id,
            "motorista_id": motorista.id,
            "motorista_nome": motorista.nome,
            "disponibilidade": motorista.disponibilidade,
            "viagem_id": (
                viagem_atual.id
                if viagem_atual
                else None
            )
        }), 200

    except Exception as erro:
        db.session.rollback()

        print(
            "ERRO AO ATRIBUIR MOTORISTA:",
            erro
        )

        return jsonify({
            "erro": "Não foi possível atribuir o motorista."
        }), 500


@admin_cargas_bp.route(
    "/api/admin/cargas/<int:id>/atribuir-veiculo",
    methods=["PUT"]
)
@jwt_required()
def atribuir_veiculo(id):
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
            "erro": "Você não possui permissão para atribuir veículos."
        }), 403

    dados = request.get_json() or {}

    veiculo_id = dados.get("veiculo_id")

    if not veiculo_id:
        return jsonify({
            "erro": "veiculo_id é obrigatório."
        }), 400

    carga = db.session.get(
        Rastreamento,
        id
    )

    if not carga:
        return jsonify({
            "erro": "Carga não encontrada."
        }), 404

    # Busca a viagem vinculada à carga antes de qualquer alteração.
    viagem_atual = Viagem.query.filter_by(
        rastreamento_id=carga.id
    ).first()

    status_carga = str(
        carga.status or ""
    ).strip().lower()

    status_viagem = str(
        viagem_atual.status if viagem_atual else ""
    ).strip().lower()

    if (
        status_carga in ["entregue", "cancelada"]
        or status_viagem in ["entregue", "cancelada"]
    ):
        return jsonify({
            "erro": (
                "Não é possível alterar o veículo de uma "
                "carga com operação finalizada."
            )
        }), 409

    try:
        veiculo_id = int(veiculo_id)
    except (TypeError, ValueError):
        return jsonify({
            "erro": "veiculo_id inválido."
        }), 400

    veiculo = db.session.get(
        Veiculo,
        veiculo_id
    )

    if not veiculo:
        return jsonify({
            "erro": "Veículo não encontrado."
        }), 404

    status_veiculo = str(
        veiculo.status or ""
    ).strip().lower()

    if status_veiculo in [
        "inativo",
        "manutenção",
        "em manutenção"
    ]:
        return jsonify({
            "erro": (
                "O veículo selecionado não está "
                "disponível para operação."
            )
        }), 400

    status_viagem_ativos = STATUS_VIAGEM_ATIVOS_RECURSOS

    # Procura o mesmo veículo em outra viagem ativa.
    consulta_viagem = Viagem.query.filter(
        Viagem.veiculo_id == veiculo.id,
        Viagem.status.in_(status_viagem_ativos)
    )

    if viagem_atual:
        consulta_viagem = consulta_viagem.filter(
            Viagem.id != viagem_atual.id
        )

    viagem_conflitante = consulta_viagem.first()

    if viagem_conflitante:
        return jsonify({
            "erro": (
                "Este veículo já está vinculado "
                "a outra viagem ativa."
            )
        }), 409

    status_carga_ativos = STATUS_CARGA_ATIVOS_RECURSOS

    # Procura o veículo em outra carga ativa,
    # mesmo que essa carga ainda não tenha viagem.
    carga_conflitante = Rastreamento.query.filter(
        Rastreamento.veiculo_id == veiculo.id,
        Rastreamento.id != carga.id,
        Rastreamento.status.in_(status_carga_ativos)
    ).first()

    if carga_conflitante:
        return jsonify({
            "erro": (
                "Este veículo já está vinculado "
                f"à carga {carga_conflitante.codigo}."
            )
        }), 409

    try:
        veiculo_anterior_id = carga.veiculo_id

        veiculo_anterior = None

        if veiculo_anterior_id:
            veiculo_anterior = db.session.get(
                Veiculo,
                veiculo_anterior_id
            )

        carga.veiculo_id = veiculo.id

        # Se já existe viagem, sincroniza o veículo.
        if viagem_atual:
            veiculo_anterior_viagem_id = (
                viagem_atual.veiculo_id
            )

            viagem_atual.veiculo_id = veiculo.id

            operacao_atual_ativa = (
                viagem_atual.status in status_viagem_ativos
                or carga.status in status_carga_ativos
            )

            if operacao_atual_ativa:
                veiculo.status = "Em viagem"
            else:
                recalcular_status_veiculo(
                    veiculo,
                    excluir_viagem_id=viagem_atual.id,
                    excluir_carga_id=carga.id
                )

            # Evita repetir o mesmo evento na Timeline.
            if (
                veiculo_anterior_viagem_id
                != veiculo.id
            ):
                placa_anterior = (
                    veiculo_anterior.placa
                    if veiculo_anterior
                    else "Não definido"
                )

                registrar_historico(
                    viagem_atual.id,
                    "VEÍCULO",
                    (
                        f"Veículo alterado de {placa_anterior} "
                        f"para {veiculo.placa}."
                    )
                )

        else:
            if carga.status in status_carga_ativos:
                veiculo.status = "Em viagem"
            else:
                recalcular_status_veiculo(
                    veiculo,
                    excluir_carga_id=carga.id
                )

        if veiculo_anterior_id != veiculo.id:
            placa_anterior = (
                veiculo_anterior.placa
                if veiculo_anterior
                else "Não definido"
            )

            historico_rastreamento = HistoricoRastreamento(
                rastreamento_id=carga.id,
                status=carga.status,
                local=carga.local_atual,
                observacao=(
                    f"Veículo alterado de {placa_anterior} "
                    f"para {veiculo.placa}."
                )
            )

            db.session.add(historico_rastreamento)

        if (
            veiculo_anterior
            and veiculo_anterior.id != veiculo.id
        ):
            recalcular_status_veiculo(
                veiculo_anterior,
                excluir_viagem_id=(
                    viagem_atual.id
                    if viagem_atual
                    else None
                ),
                excluir_carga_id=carga.id
            )

        db.session.commit()

        return jsonify({
            "mensagem": "Veículo atribuído com sucesso!",
            "carga_id": carga.id,
            "veiculo_id": veiculo.id,
            "veiculo_placa": veiculo.placa,
            "veiculo_alterado": (
                veiculo_anterior_id != veiculo.id
            ),
            "viagem_id": (
                viagem_atual.id
                if viagem_atual
                else None
            )
        }), 200

    except Exception as erro:
        db.session.rollback()

        print(
            "ERRO AO ATRIBUIR VEÍCULO:",
            erro
        )

        return jsonify({
            "erro": "Não foi possível atribuir o veículo."
        }), 500


@admin_cargas_bp.route(
    "/api/admin/cargas/<int:id>/status",
    methods=["PUT"]
)
@jwt_required()
def atualizar_status_carga(id):
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
            "erro": "Você não possui permissão para alterar o status de cargas."
        }), 403

    dados = request.get_json() or {}

    novo_status = dados.get("status")

    if not novo_status:
        return jsonify({
            "erro": "O status é obrigatório."
        }), 400

    if novo_status not in TRANSICOES_CARGA:
     return jsonify({
            "erro": "Status inválido."
        }), 400

    carga = Rastreamento.query.get(id)

    if not carga:
        return jsonify({
            "erro": "Carga não encontrada."
        }), 404

    if not transicao_carga_permitida(carga.status, novo_status):
        return jsonify({
            "erro": (
                f"Transição de '{carga.status}' para "
                f"'{novo_status}' não permitida."
            )
        }), 409

    viagem = Viagem.query.filter_by(
        rastreamento_id=carga.id
    ).first()

    if viagem:
        status_viagem = str(viagem.status).strip().lower()

        if status_viagem == "cancelada":
            return jsonify({
                "erro": "Não é possível alterar o status de uma viagem cancelada."
            }), 409

        if status_viagem == "entregue":
            return jsonify({
                "erro": "Não é possível alterar o status de uma viagem já entregue."
            }), 409

    status_anterior = carga.status

    carga.status = novo_status
    carga.ultima_atualizacao = datetime.utcnow()

    if viagem:
        viagem.status = novo_status

        registrar_historico(
    viagem.id,
    "STATUS",
        f"Status alterado para {novo_status}."
)

    historico_rastreamento = HistoricoRastreamento(
        rastreamento_id=carga.id,
        status=novo_status,
        local=carga.local_atual,
        observacao=(
            f"Status alterado de {status_anterior} para {novo_status}."
        )
    )

    db.session.add(historico_rastreamento)

    db.session.commit()

    return jsonify({
        "mensagem": "Status atualizado com sucesso!",
        "carga_id": carga.id,
        "status": carga.status,
        "viagem_id": viagem.id if viagem else None,
        "viagem_status": viagem.status if viagem else None,
    }), 200
