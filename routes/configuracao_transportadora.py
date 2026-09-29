import os
import re

from flask import Blueprint, current_app, jsonify, request, send_file
from flask_jwt_extended import get_jwt_identity, jwt_required

from extensions import db
from models.configuracao_transportadora import ConfiguracaoTransportadora
from models.usuarios import UsuarioSistema
from services.auditoria import registrar_log, snapshot_objeto
from services.logo_transportadora import (
    LogoInvalido, caminho_logo, logo_existente, pasta_logos, validar_logo,
)
from utils.arquivos import remover_arquivo_criado


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


@configuracao_transportadora_bp.route(
    "/api/configuracao/transportadora/logo", methods=["GET"]
)
@jwt_required()
def obter_logo_transportadora():
    usuario = _usuario_atual()
    if not usuario or not usuario.ativo:
        return jsonify({"erro": "Usuário não autorizado."}), 401

    configuracao = db.session.get(ConfiguracaoTransportadora, 1)
    referencia = configuracao.logo if configuracao else None
    caminho = logo_existente(current_app.config["UPLOAD_FOLDER"], referencia)
    if not caminho:
        return jsonify({"erro": "Logo não encontrado."}), 404

    tipo = "image/png" if referencia.endswith(".png") else "image/jpeg"
    resposta = send_file(caminho, mimetype=tipo)
    resposta.headers["Cache-Control"] = "private, no-store"
    return resposta


@configuracao_transportadora_bp.route(
    "/api/configuracao/transportadora/logo", methods=["POST"]
)
@jwt_required()
def enviar_logo_transportadora():
    usuario = _usuario_atual()
    if not usuario or not usuario.ativo:
        return jsonify({"erro": "Usuário não autorizado."}), 401
    if str(usuario.perfil).strip().lower() != "administrador":
        return jsonify({"erro": "Acesso não autorizado."}), 403

    configuracao = db.session.get(ConfiguracaoTransportadora, 1)
    if not configuracao:
        return jsonify({"erro": "Configure a transportadora antes do logo."}), 409

    arquivo = request.files.get("arquivo")
    if arquivo is None:
        return jsonify({"erro": "Nenhum arquivo enviado."}), 400
    try:
        dados, referencia = validar_logo(arquivo)
    except LogoInvalido as erro:
        return jsonify({"erro": str(erro)}), erro.status

    pasta = pasta_logos(current_app.config["UPLOAD_FOLDER"])
    caminho_novo = caminho_logo(current_app.config["UPLOAD_FOLDER"], referencia)
    referencia_anterior = configuracao.logo
    try:
        os.makedirs(pasta, exist_ok=True)
        with open(caminho_novo, "xb") as destino:
            destino.write(dados)

        configuracao.logo = referencia
        registrar_log(
            acao="Upload de logo da transportadora",
            modulo="Configuração",
            entidade="ConfiguracaoTransportadora",
            entidade_id=1,
            antes={"logo": referencia_anterior},
            depois={"logo": referencia},
            usuario_id=usuario.id,
            usuario_nome=usuario.nome,
            perfil=usuario.perfil,
        )
        db.session.commit()
    except Exception:
        db.session.rollback()
        remover_arquivo_criado(caminho_novo, current_app.logger)
        current_app.logger.exception("Falha ao salvar logo da transportadora.")
        return jsonify({"erro": "Não foi possível salvar o logo."}), 500

    if referencia_anterior:
        caminho_antigo = caminho_logo(
            current_app.config["UPLOAD_FOLDER"], referencia_anterior
        )
        if caminho_antigo and os.path.isfile(caminho_antigo):
            try:
                os.remove(caminho_antigo)
            except OSError:
                current_app.logger.exception("Falha ao remover logo anterior.")

    return jsonify({"logo": referencia}), 201


@configuracao_transportadora_bp.route(
    "/api/configuracao/transportadora/logo", methods=["DELETE"]
)
@jwt_required()
def remover_logo_transportadora():
    usuario = _usuario_atual()
    if not usuario or not usuario.ativo:
        return jsonify({"erro": "Usuário não autorizado."}), 401
    if str(usuario.perfil).strip().lower() != "administrador":
        return jsonify({"erro": "Acesso não autorizado."}), 403

    configuracao = db.session.get(ConfiguracaoTransportadora, 1)
    if not configuracao or not configuracao.logo:
        return jsonify({"erro": "Logo não encontrado."}), 404

    referencia = configuracao.logo
    try:
        configuracao.logo = None
        registrar_log(
            acao="Remoção de logo da transportadora",
            modulo="Configuração",
            entidade="ConfiguracaoTransportadora",
            entidade_id=1,
            antes={"logo": referencia},
            depois={"logo": None},
            usuario_id=usuario.id,
            usuario_nome=usuario.nome,
            perfil=usuario.perfil,
        )
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Falha ao remover logo da transportadora.")
        return jsonify({"erro": "Não foi possível remover o logo."}), 500

    caminho = caminho_logo(current_app.config["UPLOAD_FOLDER"], referencia)
    if caminho and os.path.isfile(caminho):
        try:
            os.remove(caminho)
        except OSError:
            current_app.logger.exception("Falha ao remover arquivo de logo.")

    return jsonify({"logo": None}), 200
