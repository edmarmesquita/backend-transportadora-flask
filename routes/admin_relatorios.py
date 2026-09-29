import io

from flask import Blueprint, current_app, jsonify, send_file
from flask_jwt_extended import get_jwt_identity, jwt_required
from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from extensions import db
from models.clientes import Cliente
from models.configuracao_transportadora import ConfiguracaoTransportadora
from models.operacao import Rastreamento, Viagem
from models.recursos import Motorista, Veiculo
from models.usuarios import UsuarioSistema
from services.logo_transportadora import logo_existente


admin_relatorios_bp = Blueprint(
    "admin_relatorios",
    __name__
)


def nome_transportadora_relatorio():
    configuracao = db.session.get(ConfiguracaoTransportadora, 1)
    if configuracao and configuracao.nome_exibicao:
        return configuracao.nome_exibicao
    return "TRANSPORTADORA"


def desenhar_logo_relatorio(pdf):
    configuracao = db.session.get(ConfiguracaoTransportadora, 1)
    referencia = configuracao.logo if configuracao else None
    caminho = logo_existente(current_app.config["UPLOAD_FOLDER"], referencia)
    if not caminho:
        return False
    try:
        with Image.open(caminho, formats=("PNG", "JPEG")) as imagem:
            imagem.load()
            pdf.drawImage(
                ImageReader(imagem.copy()), 50, 782,
                width=84, height=56, preserveAspectRatio=True,
                anchor="c", mask="auto",
            )
    except Exception:
        current_app.logger.warning("Logo indisponível para o relatório.")
        return False
    return True


@admin_relatorios_bp.route("/api/admin/relatorios/viagens")
@jwt_required()
def api_relatorio_viagens():
    usuario_id = int(get_jwt_identity())
    usuario = db.session.get(UsuarioSistema, usuario_id)

    if not usuario or not usuario.ativo:
        return jsonify({"erro": "Usuário não autorizado."}), 401

    if str(usuario.perfil).strip().lower() not in [
        "administrador", "operador"
    ]:
        return jsonify({
            "erro": "Você não possui permissão para acessar relatórios de viagens."
        }), 403

    viagens = Viagem.query.all()

    lista = []

    for viagem in viagens:
        lista.append({
            "codigo": viagem.carga.codigo if viagem.carga else "",
            "cliente": viagem.carga.cliente if viagem.carga else "",
            "origem": viagem.origem,
            "destino": viagem.destino,
            "status": viagem.status
        })

    return lista


@admin_relatorios_bp.route("/api/admin/relatorios/viagens/pdf")
@jwt_required()
def api_relatorio_viagens_pdf():
    usuario_id = int(get_jwt_identity())
    usuario = db.session.get(UsuarioSistema, usuario_id)

    if not usuario or not usuario.ativo:
        return jsonify({"erro": "Usuário não autorizado."}), 401

    if str(usuario.perfil).strip().lower() not in [
        "administrador", "operador"
    ]:
        return jsonify({
            "erro": "Você não possui permissão para acessar relatórios de viagens."
        }), 403

    buffer = io.BytesIO()

    pdf = canvas.Canvas(buffer, pagesize=A4)

    pdf.setTitle("Relatório de Viagens")

    tem_logo = desenhar_logo_relatorio(pdf)
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(
        144 if tem_logo else 50,
        800,
        nome_transportadora_relatorio()
    )

    pdf.setFont("Helvetica", 12)
    pdf.drawString(
        50,
        764 if tem_logo else 780,
        "Relatório de Viagens"
    )

    y = 740

    viagens = Viagem.query.all()

    for viagem in viagens:

        codigo = (
            viagem.carga.codigo
            if viagem.carga
            else "Sem código"
        )

        cliente = (
            viagem.carga.cliente
            if viagem.carga
            else "Sem cliente"
        )

        pdf.drawString(
            50,
            y,
            f"Código: {codigo}"
        )

        pdf.drawString(
            220,
            y,
            f"Cliente: {cliente}"
        )

        y -= 20

        pdf.drawString(
            50,
            y,
            f"Origem: {viagem.origem}"
        )

        y -= 20

        pdf.drawString(
            50,
            y,
            f"Destino: {viagem.destino}"
        )

        y -= 20

        pdf.drawString(
            50,
            y,
            f"Status: {viagem.status}"
        )

        y -= 35

        if y < 80:
            pdf.showPage()
            y = 800

    pdf.save()

    buffer.seek(0)

    return send_file(
        buffer,
        as_attachment=True,
        download_name="relatorio_viagens.pdf",
        mimetype="application/pdf"
    )


@admin_relatorios_bp.route("/api/admin/relatorios/financeiro/pdf")
@jwt_required()
def api_relatorio_financeiro_pdf():
    usuario_id = int(get_jwt_identity())
    usuario = db.session.get(UsuarioSistema, usuario_id)

    if not usuario or not usuario.ativo:
        return jsonify({"erro": "Usuário não autorizado."}), 401

    if str(usuario.perfil).strip().lower() != "administrador":
        return jsonify({
            "erro": "Você não possui permissão para acessar relatórios financeiros."
        }), 403

    buffer = io.BytesIO()

    pdf = canvas.Canvas(
        buffer,
        pagesize=A4
    )

    pdf.setTitle(
        "Relatório Financeiro"
    )

    tem_logo = desenhar_logo_relatorio(pdf)
    pdf.setFont(
        "Helvetica-Bold",
        16
    )

    pdf.drawString(
        144 if tem_logo else 50,
        800,
        nome_transportadora_relatorio()
    )

    pdf.setFont(
        "Helvetica",
        12
    )

    pdf.drawString(
        50,
        764 if tem_logo else 780,
        "Relatório Financeiro"
    )

    cargas = Rastreamento.query.all()

    faturamento_total = 0
    total_pago = 0
    total_pendente = 0

    for carga in cargas:

        valor = carga.valor_frete or 0

        faturamento_total += valor

        if carga.status_pagamento == "Pago":
            total_pago += valor
        else:
            total_pendente += valor

    ticket_medio = 0

    if len(cargas) > 0:
        ticket_medio = (
            faturamento_total /
            len(cargas)
        )

    y = 720

    pdf.drawString(
        50,
        y,
        f"Faturamento Total: R$ {faturamento_total:,.2f}"
    )

    y -= 30

    pdf.drawString(
        50,
        y,
        f"Total Pago: R$ {total_pago:,.2f}"
    )

    y -= 30

    pdf.drawString(
        50,
        y,
        f"Total Pendente: R$ {total_pendente:,.2f}"
    )

    y -= 30

    pdf.drawString(
        50,
        y,
        f"Ticket Médio: R$ {ticket_medio:,.2f}"
    )

    pdf.save()

    buffer.seek(0)

    return send_file(
        buffer,
        as_attachment=True,
        download_name="relatorio_financeiro.pdf",
        mimetype="application/pdf"
    )


@admin_relatorios_bp.route("/api/admin/viagens/evolucao", methods=["GET"])
@jwt_required()
def api_evolucao_viagens():
    usuario_id = int(get_jwt_identity())
    usuario = db.session.get(UsuarioSistema, usuario_id)

    if not usuario or not usuario.ativo:
        return jsonify({"erro": "Usuário não autorizado."}), 401

    if str(usuario.perfil).strip().lower() not in [
        "administrador", "operador"
    ]:
        return jsonify({
            "erro": "Você não possui permissão para acessar indicadores de viagens."
        }), 403

    viagens = Viagem.query.all()

    meses = {}

    nomes_meses = [
        "Jan", "Fev", "Mar", "Abr", "Mai", "Jun",
        "Jul", "Ago", "Set", "Out", "Nov", "Dez"
    ]

    for viagem in viagens:
        if viagem.data_criacao:
            mes = nomes_meses[viagem.data_criacao.month - 1]

            if mes not in meses:
                meses[mes] = 0

            meses[mes] += 1

    lista = []

    for mes, total in meses.items():
        lista.append({
            "mes": mes,
            "total": total
        })

    return lista


@admin_relatorios_bp.route("/api/admin/relatorios/resumo", methods=["GET"])
@jwt_required()
def api_relatorios_resumo():
    usuario_id = int(get_jwt_identity())
    usuario = db.session.get(UsuarioSistema, usuario_id)

    if not usuario or not usuario.ativo:
        return jsonify({"erro": "Usuário não autorizado."}), 401

    if str(usuario.perfil).strip().lower() not in [
        "administrador", "operador"
    ]:
        return jsonify({
            "erro": "Você não possui permissão para acessar relatórios administrativos."
        }), 403

    total_clientes = Cliente.query.count()
    clientes_ativos = Cliente.query.filter_by(ativo=True).count()
    clientes_inativos = Cliente.query.filter_by(ativo=False).count()

    total_motoristas = Motorista.query.count()
    motoristas_ativos = Motorista.query.filter_by(status="Ativo").count()
    motoristas_inativos = Motorista.query.filter_by(status="Inativo").count()

    total_veiculos = Veiculo.query.count()
    veiculos_disponiveis = Veiculo.query.filter_by(status="Disponível").count()
    veiculos_manutencao = Veiculo.query.filter_by(status="Manutenção").count()
    veiculos_inativos = Veiculo.query.filter_by(status="Inativo").count()

    total_viagens = Viagem.query.count()
    viagens_planejadas = Viagem.query.filter_by(status="Planejada").count()
    viagens_transito = Viagem.query.filter_by(status="Em trânsito").count()
    viagens_entregues = Viagem.query.filter_by(status="Entregue").count()

    return {
        "clientes": {
            "total": total_clientes,
            "ativos": clientes_ativos,
            "inativos": clientes_inativos
        },
        "motoristas": {
            "total": total_motoristas,
            "ativos": motoristas_ativos,
            "inativos": motoristas_inativos
        },
        "veiculos": {
            "total": total_veiculos,
            "disponiveis": veiculos_disponiveis,
            "manutencao": veiculos_manutencao,
            "inativos": veiculos_inativos
        },
        "viagens": {
            "total": total_viagens,
            "planejadas": viagens_planejadas,
            "em_transito": viagens_transito,
            "entregues": viagens_entregues
        }
    }
