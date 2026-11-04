from config import DB_PATH as db_path


def adicionar_colunas_auditoria():
    import sqlite3

    conexao = sqlite3.connect(db_path)
    cursor = conexao.cursor()

    cursor.execute("PRAGMA table_info(log_acao)")
    colunas = [coluna[1] for coluna in cursor.fetchall()]

    novas_colunas = {
        "perfil": "TEXT",
        "modulo": "TEXT",
        "entidade": "TEXT",
        "entidade_id": "INTEGER",
        "antes": "TEXT",
        "depois": "TEXT",
    }

    for nome_coluna, tipo_coluna in novas_colunas.items():
        if nome_coluna not in colunas:
            cursor.execute(
                f"ALTER TABLE log_acao "
                f"ADD COLUMN {nome_coluna} {tipo_coluna}"
            )

    conexao.commit()
    conexao.close()


def adicionar_colunas_operacionais():
    import sqlite3

    conexao = sqlite3.connect(db_path)
    cursor = conexao.cursor()

    try:
        # ==========================
        # TABELA RASTREAMENTO
        # ==========================
        cursor.execute("PRAGMA table_info(rastreamento)")
        colunas_rastreamento = [
            coluna[1] for coluna in cursor.fetchall()
        ]

        if "cliente_id" not in colunas_rastreamento:
            cursor.execute(
                "ALTER TABLE rastreamento "
                "ADD COLUMN cliente_id INTEGER"
            )

        if "motorista_id" not in colunas_rastreamento:
            cursor.execute(
                "ALTER TABLE rastreamento "
                "ADD COLUMN motorista_id INTEGER"
            )

        if "veiculo_id" not in colunas_rastreamento:
            cursor.execute(
                "ALTER TABLE rastreamento "
                "ADD COLUMN veiculo_id INTEGER"
            )

        if "rota_id" not in colunas_rastreamento:
            cursor.execute(
                "ALTER TABLE rastreamento "
                "ADD COLUMN rota_id INTEGER"
            )

        if "previsao_entrega" not in colunas_rastreamento:
            cursor.execute(
                "ALTER TABLE rastreamento "
                "ADD COLUMN previsao_entrega DATETIME"
            )

        novas_colunas_planejamento = {
            "descricao_carga": "TEXT",
            "peso_kg": "REAL",
            "data_prevista_saida": "DATETIME",
        }
        for nome_coluna, tipo_coluna in novas_colunas_planejamento.items():
            if nome_coluna not in colunas_rastreamento:
                cursor.execute(
                    f"ALTER TABLE rastreamento "
                    f"ADD COLUMN {nome_coluna} {tipo_coluna}"
                )

        if "destino_latitude" not in colunas_rastreamento:
            cursor.execute(
                "ALTER TABLE rastreamento "
                "ADD COLUMN destino_latitude TEXT"
            )

        if "destino_longitude" not in colunas_rastreamento:
            cursor.execute(
                "ALTER TABLE rastreamento "
                "ADD COLUMN destino_longitude TEXT"
            )

        if "valor_frete" not in colunas_rastreamento:
            cursor.execute(
                "ALTER TABLE rastreamento "
                "ADD COLUMN valor_frete REAL DEFAULT 0"
            )

        if "status_pagamento" not in colunas_rastreamento:
            cursor.execute(
                "ALTER TABLE rastreamento "
                "ADD COLUMN status_pagamento TEXT "
                "DEFAULT 'Pendente'"
            )

        # ==========================
        # TABELA CLIENTE_USUARIO
        # ==========================
        cursor.execute("PRAGMA table_info(cliente_usuario)")
        colunas_cliente_usuario = [
            coluna[1] for coluna in cursor.fetchall()
        ]

        colunas_estruturais_cliente_usuario = {
            "cliente_id",
            "usuario_sistema_id",
        }
        if not colunas_estruturais_cliente_usuario.issubset(
            colunas_cliente_usuario
        ):
            raise RuntimeError(
                "Schema legado de cliente_usuario detectado. "
                "Execute a migração estrutural controlada."
            )

        cursor.execute("PRAGMA index_list(cliente_usuario)")
        indices_cliente_usuario = cursor.fetchall()
        colunas_indices_unicos = {}

        for indice in indices_cliente_usuario:
            nome_indice = indice[1]
            indice_unico = bool(indice[2])

            if not indice_unico:
                continue

            nome_indice_sql = nome_indice.replace('"', '""')
            cursor.execute(
                f'PRAGMA index_info("{nome_indice_sql}")'
            )
            colunas_indices_unicos[nome_indice] = tuple(
                coluna[2] for coluna in cursor.fetchall()
            )

        if (
            ("empresa",) in colunas_indices_unicos.values()
            or ("email",) not in colunas_indices_unicos.values()
            or colunas_indices_unicos.get(
                "uq_cliente_usuario_usuario_sistema_id"
            ) != ("usuario_sistema_id",)
        ):
            raise RuntimeError(
                "Schema legado de cliente_usuario detectado. "
                "Execute a migração estrutural controlada."
            )

        # ==========================
        # TABELA MOTORISTA
        # ==========================
        cursor.execute("PRAGMA table_info(motorista)")
        colunas_motorista = [
            coluna[1] for coluna in cursor.fetchall()
        ]

        if "usuario" not in colunas_motorista:
            cursor.execute(
                "ALTER TABLE motorista "
                "ADD COLUMN usuario TEXT"
            )

        if "senha" not in colunas_motorista:
            cursor.execute(
                "ALTER TABLE motorista "
                "ADD COLUMN senha TEXT"
            )

        if "usuario_sistema_id" not in colunas_motorista:
            cursor.execute(
                "ALTER TABLE motorista "
                "ADD COLUMN usuario_sistema_id INTEGER "
                "REFERENCES usuario_sistema(id)"
            )

        cursor.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS "
            "uq_motorista_usuario_sistema_id "
            "ON motorista (usuario_sistema_id)"
        )

        # ==========================
        # TABELA CARGA
        # ==========================
        cursor.execute("PRAGMA table_info(carga)")
        colunas_carga = [
            coluna[1] for coluna in cursor.fetchall()
        ]

        if "motorista_id" not in colunas_carga:
            cursor.execute(
                "ALTER TABLE carga "
                "ADD COLUMN motorista_id INTEGER"
            )

        # ==========================
        # TABELA VIAGEM
        # ==========================
        cursor.execute("PRAGMA table_info(viagem)")
        colunas_viagem = [
            coluna[1] for coluna in cursor.fetchall()
        ]

        if "codigo" not in colunas_viagem:
            cursor.execute(
                "ALTER TABLE viagem "
                "ADD COLUMN codigo TEXT"
            )

        conexao.commit()

    except sqlite3.Error as erro:
        conexao.rollback()

        print(
            f"Erro ao atualizar colunas operacionais: {erro}"
        )

        raise

    finally:
        conexao.close()
