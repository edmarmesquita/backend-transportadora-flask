import re

from flask import Blueprint, request

from extensions import db
from models.cotacoes import Cotacao
from models.operacao import Rastreamento
from utils.datas import formatar_data_brasilia


public_bp = Blueprint("public", __name__)

PADRAO_CODIGO_RASTREAMENTO = re.compile(r"^[A-Z0-9-]{2,30}$")


@public_bp.route("/")
def index():
    return {
        "mensagem": "Backend da Transportadora Ramos ativo.",
        "status": "online"
    }


@public_bp.route("/api/rastreamento/<codigo>", methods=["GET"])
def api_buscar_rastreamento(codigo):
    codigo = codigo.strip().upper()

    if not PADRAO_CODIGO_RASTREAMENTO.fullmatch(codigo):
        return {"erro": "Código de rastreamento inválido."}, 400

    carga = Rastreamento.query.filter_by(codigo=codigo).first()

    if not carga:
        return {"erro": "Rastreamento não encontrado."}, 404

    ultima_atualizacao = ""
    if carga.ultima_atualizacao:
        ultima_atualizacao = formatar_data_brasilia(carga.ultima_atualizacao)

    previsao_entrega = ""
    if carga.previsao_entrega:
        previsao_entrega = formatar_data_brasilia(carga.previsao_entrega)

    return {
        "codigo": carga.codigo,
        "status": carga.status,
        "previsao_entrega": previsao_entrega,
        "ultima_atualizacao": ultima_atualizacao
    }, 200


@public_bp.route("/api/cotacoes", methods=["POST"])
def api_criar_cotacao_publica():
    dados = request.get_json()

    cliente = dados.get("cliente", "").strip()
    whatsapp = dados.get("whatsapp", "").strip()
    origem = dados.get("origem", "").strip()
    destino = dados.get("destino", "").strip()
    tipo_carga = dados.get("tipoCarga", "").strip()
    observacoes = dados.get("observacoes", "").strip()

    if not all([cliente, whatsapp, origem, destino, tipo_carga]):
        return {"erro": "Preencha todos os campos obrigatórios."}, 400

    nova_cotacao = Cotacao(
        cliente=cliente,
        whatsapp=whatsapp,
        origem=origem,
        destino=destino,
        tipo_carga=tipo_carga,
        observacoes=observacoes
    )

    db.session.add(nova_cotacao)
    db.session.commit()

    return {
        "mensagem": "Orçamento enviado com sucesso!",
        "cotacao_id": nova_cotacao.id
    }, 201
