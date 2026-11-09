"""Fotos de ocorrência privadas da operação."""

import os

from flask import Blueprint, current_app, jsonify, request, send_file
from flask_jwt_extended import get_jwt_identity, jwt_required
from sqlalchemy.exc import IntegrityError

from extensions import db
from models.ocorrencias import AnexoOcorrenciaViagem, OcorrenciaViagem
from models.operacao import Viagem
from models.recursos import Motorista
from models.usuarios import UsuarioSistema
from services.fotos_ocorrencia import EXTENSOES_FOTO, preparar_foto
from services.rate_limit import verificar_limite
from utils.arquivos import ErroValidacaoArquivo, remover_arquivo_criado, salvar_arquivo_upload
from utils.datas import serializar_instante_utc


fotos_ocorrencia_bp = Blueprint("fotos_ocorrencia", __name__)
STATUS_FOTO = {"Em trânsito", "Saiu para entrega"}
MAX_FOTOS = 5


def _usuario():
    return db.session.get(UsuarioSistema, int(get_jwt_identity()))


def _motorista(usuario):
    if not usuario or not usuario.ativo or str(usuario.perfil).strip().lower() != "motorista":
        return None
    motorista = Motorista.query.filter_by(usuario_sistema_id=usuario.id).first()
    if not motorista or str(motorista.status).strip().lower() == "inativo":
        return None
    return motorista


def _viagem_ocorrencia(viagem_id, ocorrencia_id, motorista):
    viagem = Viagem.query.filter_by(id=viagem_id, motorista_id=motorista.id).first()
    ocorrencia = db.session.get(OcorrenciaViagem, ocorrencia_id)
    if not viagem or not ocorrencia or ocorrencia.viagem_id != viagem.id:
        return None, None
    return viagem, ocorrencia


def _dados(anexo):
    return {
        "id": anexo.id,
        "ocorrencia_id": anexo.ocorrencia_id,
        "nome_original": anexo.nome_original,
        "mime_type": anexo.mime_type,
        "tamanho_bytes": anexo.tamanho_bytes,
        "data_upload": serializar_instante_utc(anexo.data_upload),
        "download_endpoint": f"/api/ocorrencias/fotos/{anexo.id}/download",
    }


@fotos_ocorrencia_bp.route(
    "/api/motorista/minhas-viagens/<int:viagem_id>/ocorrencias/<int:ocorrencia_id>/fotos",
    methods=["GET", "POST"],
)
@jwt_required()
def fotos_ocorrencia_motorista(viagem_id, ocorrencia_id):
    usuario = _usuario()
    if not usuario or not usuario.ativo:
        return jsonify({"erro": "Usuário não autorizado."}), 401
    motorista = _motorista(usuario)
    if not motorista:
        return jsonify({"erro": "Acesso permitido somente ao motorista ativo."}), 403
    viagem, ocorrencia = _viagem_ocorrencia(viagem_id, ocorrencia_id, motorista)
    if not viagem:
        return jsonify({"erro": "Ocorrência não encontrada nesta viagem."}), 404
    existentes = AnexoOcorrenciaViagem.query.filter_by(ocorrencia_id=ocorrencia.id).order_by(
        AnexoOcorrenciaViagem.id.asc()
    ).all()
    if request.method == "GET":
        return jsonify([_dados(anexo) for anexo in existentes]), 200

    limite = verificar_limite([(f"upload:usuario:{usuario.id}", 10, 60)])
    if limite:
        return limite
    if viagem.status not in STATUS_FOTO:
        return jsonify({"erro": "Fotos de ocorrência só podem ser enviadas em trânsito ou após sair para entrega."}), 409
    arquivos = request.files.getlist("fotos")
    if not arquivos:
        return jsonify({"erro": "Selecione ao menos uma foto."}), 400

    preparados = []
    try:
        for arquivo in arquivos:
            preparados.append(preparar_foto(arquivo, current_app.config["UPLOAD_MAX_FILE_SIZE"]))
    except ErroValidacaoArquivo as erro:
        return jsonify({"erro": erro.mensagem}), erro.status_code

    hashes_existentes = {anexo.hash_sha256 for anexo in existentes}
    novos = []
    hashes_novos = set()
    for preparado in preparados:
        hash_foto = preparado[4]
        if hash_foto not in hashes_existentes and hash_foto not in hashes_novos:
            novos.append(preparado)
            hashes_novos.add(hash_foto)
    if len(existentes) + len(novos) > MAX_FOTOS:
        return jsonify({"erro": "Cada ocorrência aceita no máximo 5 fotos."}), 409
    if not novos:
        return jsonify({"mensagem": "Fotos já registradas.", "anexos": [_dados(a) for a in existentes], "ja_enviado": True}), 200

    criados = []
    try:
        pasta = os.path.join(current_app.config["UPLOAD_FOLDER"], "ocorrencias")
        for preparado, original, mime, tamanho, hash_foto in novos:
            _, nome, caminho = salvar_arquivo_upload(
                preparado, pasta, EXTENSOES_FOTO, current_app.config["UPLOAD_MAX_FILE_SIZE"]
            )
            criados.append(caminho)
            db.session.add(AnexoOcorrenciaViagem(
                ocorrencia_id=ocorrencia.id, viagem_id=viagem.id, motorista_id=motorista.id,
                nome_arquivo=nome, nome_original=original, mime_type=mime,
                tamanho_bytes=tamanho, hash_sha256=hash_foto, visibilidade="INTERNO",
            ))
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        for caminho in criados:
            remover_arquivo_criado(caminho, current_app.logger)
        return jsonify({"erro": "O envio foi repetido. Atualize a lista de fotos."}), 409
    except Exception:
        db.session.rollback()
        for caminho in criados:
            remover_arquivo_criado(caminho, current_app.logger)
        current_app.logger.exception("Falha ao salvar fotos da ocorrência.")
        return jsonify({"erro": "Não foi possível salvar as fotos."}), 500
    anexos = AnexoOcorrenciaViagem.query.filter_by(ocorrencia_id=ocorrencia.id).order_by(
        AnexoOcorrenciaViagem.id.asc()
    ).all()
    return jsonify({"mensagem": "Fotos registradas.", "anexos": [_dados(a) for a in anexos], "ja_enviado": False}), 201


@fotos_ocorrencia_bp.route(
    "/api/admin/viagens/<int:viagem_id>/ocorrencias/<int:ocorrencia_id>/fotos",
    methods=["GET"],
)
@jwt_required()
def fotos_ocorrencia_admin(viagem_id, ocorrencia_id):
    usuario = _usuario()
    if not usuario or not usuario.ativo:
        return jsonify({"erro": "Usuário não autorizado."}), 401
    if str(usuario.perfil).strip().lower() not in {"administrador", "operador"}:
        return jsonify({"erro": "Acesso não autorizado."}), 403
    ocorrencia = db.session.get(OcorrenciaViagem, ocorrencia_id)
    if not ocorrencia or ocorrencia.viagem_id != viagem_id:
        return jsonify({"erro": "Ocorrência não encontrada nesta viagem."}), 404
    anexos = AnexoOcorrenciaViagem.query.filter_by(ocorrencia_id=ocorrencia_id).order_by(
        AnexoOcorrenciaViagem.id.asc()
    ).all()
    return jsonify([_dados(anexo) for anexo in anexos]), 200


@fotos_ocorrencia_bp.route("/api/ocorrencias/fotos/<int:anexo_id>/download", methods=["GET"])
@jwt_required()
def baixar_foto_ocorrencia(anexo_id):
    usuario = _usuario()
    if not usuario or not usuario.ativo:
        return jsonify({"erro": "Usuário não autorizado."}), 401
    anexo = db.session.get(AnexoOcorrenciaViagem, anexo_id)
    if not anexo or not anexo.viagem or not anexo.ocorrencia or anexo.ocorrencia.viagem_id != anexo.viagem_id:
        return jsonify({"erro": "Foto não encontrada."}), 404
    perfil = str(usuario.perfil).strip().lower()
    if perfil == "motorista":
        motorista = _motorista(usuario)
        autorizado = bool(motorista and anexo.viagem.motorista_id == motorista.id)
    else:
        autorizado = perfil in {"administrador", "operador"}
    if not autorizado:
        return jsonify({"erro": "Acesso não autorizado."}), 403
    nome = anexo.nome_arquivo
    pasta = os.path.abspath(os.path.join(current_app.config["UPLOAD_FOLDER"], "ocorrencias"))
    if not nome or os.path.basename(nome) != nome or os.path.isabs(nome):
        return jsonify({"erro": "Foto não encontrada."}), 404
    caminho = os.path.abspath(os.path.join(pasta, nome))
    if os.path.commonpath([pasta, caminho]) != pasta or not os.path.isfile(caminho):
        return jsonify({"erro": "Foto não encontrada."}), 404
    if anexo.mime_type not in {"image/jpeg", "image/png"}:
        return jsonify({"erro": "Foto não encontrada."}), 404
    resposta = send_file(caminho, mimetype=anexo.mime_type, as_attachment=True, download_name=anexo.nome_original)
    resposta.headers["X-Content-Type-Options"] = "nosniff"
    return resposta
