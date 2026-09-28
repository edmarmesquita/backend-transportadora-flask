from extensions import db


class ConfiguracaoTransportadora(db.Model):
    __tablename__ = "configuracao_transportadora"
    __table_args__ = (
        db.CheckConstraint("id = 1", name="ck_configuracao_transportadora_unica"),
    )

    id = db.Column(db.Integer, primary_key=True)
    nome_exibicao = db.Column(db.String(120), nullable=False)
    razao_social = db.Column(db.String(150), nullable=False)
    cnpj = db.Column(db.String(18), nullable=True)
    telefone = db.Column(db.String(30), nullable=True)
    whatsapp = db.Column(db.String(30), nullable=True)
    email = db.Column(db.String(120), nullable=True)
    endereco = db.Column(db.String(200), nullable=True)
    logo = db.Column(db.String(255), nullable=True)
