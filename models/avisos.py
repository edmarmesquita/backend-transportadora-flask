from datetime import datetime

from extensions import db


class AvisoChegada(db.Model):
    __tablename__ = "aviso_chegada"

    id = db.Column(db.Integer, primary_key=True)
    viagem_id = db.Column(db.Integer, db.ForeignKey("viagem.id"), nullable=False)
    rastreamento_id = db.Column(db.Integer, db.ForeignKey("rastreamento.id"), nullable=False)
    motorista_id = db.Column(db.Integer, db.ForeignKey("motorista.id"), nullable=False)
    data_aviso = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    viagem = db.relationship("Viagem", backref=db.backref("aviso_chegada", uselist=False))
    rastreamento = db.relationship("Rastreamento")
    motorista = db.relationship("Motorista")

    __table_args__ = (
        db.UniqueConstraint("viagem_id", name="uq_aviso_chegada_viagem"),
    )
