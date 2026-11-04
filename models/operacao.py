from datetime import datetime

from extensions import db


class Rastreamento(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    rota_id = db.Column(db.Integer, db.ForeignKey('rota.id'), nullable=True)
    rota_relacao = db.relationship('Rota', backref='rastreamentos')

    cliente_id = db.Column(db.Integer, db.ForeignKey('cliente.id'), nullable=True)
    cliente_relacao = db.relationship('Cliente', backref='rastreamentos')

    motorista_id = db.Column(db.Integer, db.ForeignKey('motorista.id'), nullable=True)
    motorista_relacao = db.relationship('Motorista', backref='rastreamentos')

    veiculo_id = db.Column(db.Integer, db.ForeignKey('veiculo.id'), nullable=True)
    veiculo_relacao = db.relationship('Veiculo', backref='rastreamentos')
  
    destino_latitude = db.Column(db.String(50), nullable=True)
    destino_longitude = db.Column(db.String(50), nullable=True)

    codigo = db.Column(db.String(30), unique=True, nullable=False)
    cliente = db.Column(db.String(100), nullable=False)  # vamos manter por compatibilidade
    status = db.Column(db.String(50), nullable=False)
    valor_frete = db.Column(db.Float, default=0)
    status_pagamento = db.Column(db.String(30), default="Pendente")
    local_atual = db.Column(db.String(100), nullable=False)
    destino = db.Column(db.String(100), nullable=False)
    descricao_carga = db.Column(db.Text, nullable=True)
    peso_kg = db.Column(db.Float, nullable=True)
    # Planejamento usa horario operacional local, sem conversao UTC.
    data_prevista_saida = db.Column(db.DateTime, nullable=True)
    previsao_entrega = db.Column(db.DateTime, nullable=True)
    ultima_atualizacao = db.Column(db.DateTime, default=datetime.utcnow)


class Viagem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    
    codigo = db.Column(
    db.String(30),
    nullable=True,
    unique=True
)

    rastreamento_id = db.Column(db.Integer, db.ForeignKey("rastreamento.id"), nullable=False)
    motorista_id = db.Column(db.Integer, db.ForeignKey("motorista.id"), nullable=True)
    veiculo_id = db.Column(db.Integer, db.ForeignKey("veiculo.id"), nullable=True)

    origem = db.Column(db.String(120), nullable=False)
    destino = db.Column(db.String(120), nullable=False)
    status = db.Column(db.String(30), default="Planejada")

    # Saida efetiva da execucao; nao representa o agendamento da carga.
    data_saida = db.Column(db.DateTime, nullable=True)
    previsao_entrega = db.Column(db.DateTime, nullable=True)
    data_criacao = db.Column(db.DateTime, default=datetime.utcnow)

    carga = db.relationship("Rastreamento", backref="viagens")
    motorista = db.relationship("Motorista", backref="viagens")
    veiculo = db.relationship("Veiculo", backref="viagens")
