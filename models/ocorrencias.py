from datetime import datetime

from extensions import db


class OcorrenciaEntrega(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    rastreamento_id = db.Column(db.Integer, db.ForeignKey('rastreamento.id'), nullable=False)
    titulo = db.Column(db.String(100), nullable=False)
    descricao = db.Column(db.Text, nullable=False)
    data_ocorrencia = db.Column(db.DateTime, default=datetime.utcnow)

    rastreamento = db.relationship('Rastreamento', backref='ocorrencias')


class OcorrenciaViagem(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    viagem_id = db.Column(
        db.Integer,
        db.ForeignKey("viagem.id"),
        nullable=False
    )

    descricao = db.Column(
        db.Text,
        nullable=False
    )

    data_criacao = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    viagem = db.relationship(
        "Viagem",
        backref="ocorrencias"
    )


class AnexoOcorrenciaViagem(db.Model):
    __tablename__ = "anexo_ocorrencia_viagem"
    __table_args__ = (
        db.UniqueConstraint("ocorrencia_id", "hash_sha256", name="uq_anexo_ocorrencia_hash"),
    )

    id = db.Column(db.Integer, primary_key=True)
    ocorrencia_id = db.Column(db.Integer, db.ForeignKey("ocorrencia_viagem.id"), nullable=False)
    viagem_id = db.Column(db.Integer, db.ForeignKey("viagem.id"), nullable=False)
    motorista_id = db.Column(db.Integer, db.ForeignKey("motorista.id"), nullable=True)
    nome_arquivo = db.Column(db.String(255), nullable=False)
    nome_original = db.Column(db.String(255), nullable=False)
    mime_type = db.Column(db.String(50), nullable=False)
    tamanho_bytes = db.Column(db.Integer, nullable=False)
    hash_sha256 = db.Column(db.String(64), nullable=False)
    data_upload = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    visibilidade = db.Column(db.String(20), nullable=False, default="INTERNO", server_default="INTERNO")

    ocorrencia = db.relationship("OcorrenciaViagem", backref="anexos")
    viagem = db.relationship("Viagem", backref="anexos_ocorrencia")
    motorista = db.relationship("Motorista")
