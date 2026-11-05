from utils.datas import instante_atual_utc


def registrar_dados_inicio_execucao(viagem, carga):
    """Preenche datas efetivas/plano no primeiro início da execução."""
    if viagem.data_saida is None:
        # O banco mantém o instante UTC naive, convenção legada do ROTANZA.
        viagem.data_saida = instante_atual_utc().replace(tzinfo=None)

    if viagem.previsao_entrega is None and carga:
        viagem.previsao_entrega = carga.previsao_entrega
