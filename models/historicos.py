from datetime import datetime

from extensions import db


class HistoricoOperacao(db.Model):
    _tablename__ = "historico_operacao"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    viagem_id = db.Column(
        db.Integer,
        db.ForeignKey("viagem.id"),
        nullable=False
    )

    tipo = db.Column(
        db.String(40),
        nullable=False
    )

    descricao = db.Column(
        db.Text,
        nullable=False
    )

    data_hora = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    viagem = db.relationship(
        "Viagem",
        backref="historico_operacional"
    )


class HistoricoViagem(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    viagem_id = db.Column(db.Integer, db.ForeignKey("viagem.id"), nullable=False)

    status = db.Column(db.String(50), nullable=False)
    observacao = db.Column(db.Text, nullable=True)
    data_evento = db.Column(db.DateTime, default=datetime.utcnow)

    viagem = db.relationship("Viagem", backref="historico")


class HistoricoRastreamento(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    rastreamento_id = db.Column(db.Integer, db.ForeignKey('rastreamento.id'), nullable=False)
    status = db.Column(db.String(50), nullable=False)
    local = db.Column(db.String(100), nullable=False)
    observacao = db.Column(db.Text)
    tipo_evento = db.Column(db.String(50), nullable=False, default="INTERNO", server_default="INTERNO")
    data_evento = db.Column(db.DateTime, default=datetime.utcnow)

    rastreamento = db.relationship('Rastreamento', backref='historico')
