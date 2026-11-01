STATUS_VIAGEM_ATIVOS_RECURSOS = [
    "Planejada",
    "Em andamento",
    "Em coleta",
    "Carregando",
    "Em trânsito",
    "Parada operacional",
    "Saiu para entrega"
]

STATUS_CARGA_ATIVOS_RECURSOS = [
    "Pendente",
    "Programada",
    "Em preparação",
    "Em andamento",
    "Em coleta",
    "Carregando",
    "Em trânsito",
    "Parada operacional",
    "Saiu para entrega"
]

STATUS_CARGA_TERMINAIS = {"Entregue", "Cancelada"}
STATUS_VIAGEM_TERMINAIS = {"Entregue", "Finalizada", "Cancelada"}

SEQUENCIA_OPERACIONAL = (
    "Em preparação",
    "Em coleta",
    "Carregando",
    "Em trânsito",
    "Saiu para entrega",
    "Entregue",
)

# Status auxiliares mantêm os pontos de entrada já usados pelo sistema.
# Parada operacional conserva compatibilidade histórica: pode avançar para
# trânsito ou saída para entrega, pois não há campo que guarde o estágio de origem.
TRANSICOES_OPERACIONAIS = {
    "Em preparação": {"Em coleta"},
    "Em coleta": {"Carregando"},
    "Carregando": {"Em trânsito"},
    "Em trânsito": {"Saiu para entrega"},
    "Saiu para entrega": {"Entregue"},
}

TRANSICOES_AUXILIARES = {
    "Pendente": {"Programada", "Em preparação", "Cancelada"},
    "Programada": {"Em preparação", "Cancelada"},
    "Planejada": {"Em preparação", "Em coleta", "Carregando", "Em trânsito", "Cancelada"},
    "Em andamento": {"Em coleta", "Carregando", "Em trânsito", "Parada operacional", "Saiu para entrega", "Cancelada"},
    "Parada operacional": {"Em trânsito", "Saiu para entrega", "Cancelada"},
}

TRANSICOES_CARGA = {
    **TRANSICOES_OPERACIONAIS,
    **TRANSICOES_AUXILIARES,
    "Entregue": set(),
    "Cancelada": set(),
    "Finalizada": set(),
}

TRANSICOES_VIAGEM = {
    **TRANSICOES_OPERACIONAIS,
    **TRANSICOES_AUXILIARES,
    "Entregue": set(),
    "Cancelada": set(),
    "Finalizada": set(),
}

STATUS_CARGA_EXCLUSAO_PERMITIDA = {
    "Pendente", "Programada", "Em preparação"
}
STATUS_CARGA_INICIAIS = {"Pendente", "Programada"}


def transicao_carga_permitida(status_atual, novo_status):
    return novo_status in TRANSICOES_CARGA.get(status_atual, set())


def transicao_viagem_permitida(status_atual, novo_status):
    return novo_status in TRANSICOES_VIAGEM.get(status_atual, set())


def opcoes_proximo_status(status_atual, transicoes=TRANSICOES_VIAGEM):
    """Retorna status subsequentes autorizados pela máquina central."""
    return set(transicoes.get(status_atual, set()))
