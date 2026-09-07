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

TRANSICOES_CARGA = {
    "Pendente": {"Programada", "Em preparação"},
    "Programada": {"Em preparação"},
    "Em preparação": {"Carregando"},
    "Carregando": set(),
    "Em andamento": set(),
    "Em coleta": set(),
    "Em trânsito": set(),
    "Parada operacional": set(),
    "Saiu para entrega": set(),
    "Entregue": set(),
    "Cancelada": set(),
}

TRANSICOES_VIAGEM = {
    "Planejada": {"Em coleta", "Carregando", "Em trânsito", "Cancelada"},
    "Em andamento": {
        "Em coleta", "Carregando", "Em trânsito",
        "Parada operacional", "Saiu para entrega", "Cancelada",
    },
    "Em coleta": {"Carregando", "Em trânsito", "Cancelada"},
    "Carregando": {"Em trânsito", "Cancelada"},
    "Em trânsito": {"Parada operacional", "Saiu para entrega", "Cancelada"},
    "Parada operacional": {"Em trânsito", "Saiu para entrega", "Cancelada"},
    "Saiu para entrega": {"Cancelada"},
    "Entregue": set(),
    "Finalizada": set(),
    "Cancelada": set(),
}

STATUS_CARGA_EXCLUSAO_PERMITIDA = {
    "Pendente", "Programada", "Em preparação"
}
STATUS_CARGA_INICIAIS = {"Pendente", "Programada"}


def transicao_carga_permitida(status_atual, novo_status):
    return novo_status in TRANSICOES_CARGA.get(status_atual, set())


def transicao_viagem_permitida(status_atual, novo_status):
    return novo_status in TRANSICOES_VIAGEM.get(status_atual, set())
