import re

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from extensions import db
from models.configuracao_transportadora import ConfiguracaoTransportadora
from models.usuarios import UsuarioSistema
from services.auditoria import registrar_log, snapshot_objeto


configuracao_transportadora_bp = Blueprint(
    "configuracao_transportadora", __name__
)

CAMPOS = (
    "nome_exibicao", "razao_social", "cnpj", "telefone",
    "whatsapp", "email", "endereco", "logo",
)
LIMITES = {
    "nome_exibicao": 120, "razao_social": 150, "cnpj": 18,
    "telefone": 30, "whatsapp": 30, "email": 120,
    "endereco": 200,
}


def _usuario_atual():
    try:
        usuario_id = int(get_jwt_identity())
    except (TypeError, ValueError):
        return None
    return db.session.get(UsuarioSistema, usuario_id)


def _cnpj_valido(valor):
    numeros = re.sub(r"\D", "", valor)
    if len(numeros) != 14 or len(set(numeros)) == 1:
        return False
    for tamanho, pesos in (
        (12, [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]),
        (13, [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]),
    ):
        resto = sum(int(n) * p for n, p in zip(numeros[:tamanho], pesos)) % 11
        digito = 0 if resto < 2 else 11 - resto
        if int(numeros[tamanho]) != digito:
            return False
    return True


def _serializar(configuracao):
    return {
        campo: getattr(configuracao, campo) if configuracao else None
        for campo in CAMPOS
    }


@configuracao_transportadora_bp.route(
    "/api/configuracao/transportadora", methods=["GET"]
)
@jwt_required()
def consultar_configuracao_transportadora():
    usuario = _usuario_atual()
    if not usuario or not usuario.ativo:
        return jsonify({"erro": "Usuário não autorizado."}), 401

    configuracao = db.session.get(ConfiguracaoTransportadora, 1)
    return jsonify(_serializar(configuracao)), 200


@configuracao_transportadora_bp.route(
    "/api/configuracao/transportadora", methods=["PUT"]
)
@jwt_required()
def editar_configuracao_transportadora():
    usuario = _usuario_atual()
    if not usuario or not usuario.ativo:
        return jsonify({"erro": "Usuário não autorizado."}), 401
    if str(usuario.perfil).strip().lower() != "administrador":
        return jsonify({"erro": "Acesso não autorizado."}), 403

    dados = request.get_json(silent=True)
    if not isinstance(dados, dict) or set(dados) - set(CAMPOS):
        return jsonify({"erro": "Dados inválidos."}), 400

    configuracao = db.session.get(ConfiguracaoTransportadora, 1)
    valores = _serializar(configuracao)
    for campo in CAMPOS:
        if campo not in dados:
            continue
        valor = dados[campo]
        if not isinstance(valor, str) and valor is not None:
            return jsonify({"erro": f"{campo} inválido."}), 400
        valor = (valor or "").strip()
        if campo == "logo":
            if valor:
                return jsonify({"erro": "Upload de logo ainda não disponível."}), 400
            continue
        if len(valor) > LIMITES[campo] or any(ord(c) < 32 for c in valor):
            return jsonify({"erro": f"{campo} inválido."}), 400
        valores[campo] = valor

    if not valores["nome_exibicao"] or not valores["razao_social"]:
        return jsonify({"erro": "Nome de exibição e razão social são obrigatórios."}), 400
    if valores["cnpj"]:
        if not re.fullmatch(r"\d{14}|\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}", valores["cnpj"]):
            return jsonify({"erro": "CNPJ inválido."}), 400
        if not _cnpj_valido(valores["cnpj"]):
            return jsonify({"erro": "CNPJ inválido."}), 400
        valores["cnpj"] = re.sub(r"\D", "", valores["cnpj"])
    if valores["email"] and not re.fullmatch(
        r"[^\s@]+@[^\s@]+\.[^\s@]+", valores["email"]
    ):
        return jsonify({"erro": "E-mail inválido."}), 400
    for campo in ("telefone", "whatsapp"):
        if valores[campo] and (
            not re.fullmatch(r"[+()0-9\s.-]+", valores[campo])
            or not 8 <= len(re.findall(r"[0-9]", valores[campo])) <= 15
        ):
            return jsonify({"erro": f"{campo} inválido."}), 400

    antes = snapshot_objeto(configuracao, CAMPOS) if configuracao else None
    if configuracao is None:
        configuracao = ConfiguracaoTransportadora(id=1)
        db.session.add(configuracao)
    for campo in CAMPOS:
        if campo != "logo":
            setattr(configuracao, campo, valores[campo] or None)
    db.session.flush()
    registrar_log(
        acao="Atualização da transportadora",
        modulo="Configuração",
        entidade="ConfiguracaoTransportadora",
        entidade_id=1,
        antes=antes,
        depois=snapshot_objeto(configuracao, CAMPOS),
        usuario_id=usuario.id,
        usuario_nome=usuario.nome,
        perfil=usuario.perfil,
    )
    db.session.commit()
    return jsonify(_serializar(configuracao)), 200
