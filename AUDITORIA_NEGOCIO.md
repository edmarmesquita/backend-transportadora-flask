# Auditoria de negocio da V1

## Conceitos

- **Log tecnico:** excecao, erro e diagnostico em logger/console. Nao e `LogAcao`.
- **Historico operacional:** status, localizacao e ocorrencias da carga/viagem. Continua em `HistoricoRastreamento`, `HistoricoViagem` e tabelas de ocorrencia.
- **Auditoria de negocio:** responsabilidade do usuario por mutacoes relevantes, gravada em `LogAcao` com modulo, entidade, ID e snapshots whitelistados.

## Arquitetura

`registrar_log` somente adiciona o `LogAcao` na sessao por padrao. A rota faz `commit` da alteracao e do log juntos; rollback remove ambos. O argumento `commit=True` fica reservado para o login, que nao possui mutacao de negocio pendente.

`services/auditoria.py` fornece `snapshot_objeto`, que serializa somente campos explicitamente escolhidos. Senhas, hashes, JWTs, secrets e binarios nunca entram em antes/depois.

## Matriz final

| Operacao | Perfil | Auditoria antes | Auditoria depois | Campos antes/depois | Justificativa |
| --- | --- | --- | --- | --- | --- |
| Login bem-sucedido | qualquer | nao aplicavel | evento de login | nenhum | responsabilidade de autenticacao |
| Alterar propria senha | usuario autenticado | marcador | `senha_alterada: true` | nenhum segredo | registra responsabilidade sem credencial |
| Reset administrativo | administrador | cadastro seguro | cadastro seguro + `senha_redefinida` | nome, usuario, email, perfil, ativo | mutacao de credencial |
| Criar/editar/inativar usuario | administrador | cadastro seguro | cadastro seguro | nome, usuario, email, perfil, ativo | ciclo cadastral |
| Criar/editar/inativar cliente | admin/operador | cadastro | cadastro | dados cadastrais minimos e ativo | ciclo cadastral |
| Criar/editar/ativar/inativar motorista | admin/operador | cadastro/status | cadastro/status | identificacao, documentos operacionais, status, disponibilidade | recurso operacional |
| Criar/editar/inativar veiculo | admin/operador | cadastro/status | cadastro/status | placa, modelo, marca, tipo, ano, capacidade, status | recurso operacional |
| Criar cotacao administrativa | admin/operador | nao aplicavel | cotacao | campos da cotacao sem excesso de PII | origem administrativa |
| Aprovar cotacao | admin/operador | status e sem carga | carga/rastreamento criados | IDs, status, cliente selecionado | cria carga operacional |
| Criar/editar/excluir carga | admin/operador | snapshot da carga | snapshot da carga ou nulo | codigo, cliente, status, locais, recursos, valores operacionais | mutacao critica e exclusao exige antes |
| Atribuir motorista/veiculo | admin/operador | ID anterior | ID novo | somente IDs e efeitos | responsabilidade sobre recursos |
| Alterar status de carga | admin/operador | status anterior | status posterior | status | regra operacional critica |
| Criar/despachar/status/finalizar viagem | admin/operador | status e comprovante | status, recursos e comprovante | IDs, status, recebedor necessario | ciclo operacional |
| Status/upload/ocorrencia/finalizacao motorista | motorista | status/comprovante quando aplicavel | status/comprovante/descricao | identidade JWT, IDs e dados minimos | mutacoes feitas pelo portal |
| Ocorrencia cliente | cliente | nao aplicavel | titulo e descricao | somente ocorrencia | mutacao feita pelo portal |
| Upload admin/motorista | admin/motorista | nao aplicavel | arquivo criado | viagem, `arquivo_id`, resultado | nao registra path, blob ou conteudo |
| Localizacao | admin/motorista | nao necessario | nao necessario | historico/localizacao operacional | alta frequencia; evitar crescimento inutil |
| Cotacao publica | anonimo | nao necessario | nao necessario | tabela de negocio propria | nao inventar usuario fake |
| Relatorios/PDF | admin | nao necessario | nao necessario | nenhum | leitura/exportacao sem exigencia de trilha nesta V1 |

## Cobertura deliberadamente fora de LogAcao

Falhas de login permanecem como resposta/rate limiting e log tecnico, sem gerar `LogAcao` por tentativa. Localizacoes permanecem no historico operacional. GETs e geracao de relatorios nao sao auditoria de mutacao. Cotacao publica continua somente na tabela de negocio.

## Performance e rollback

Os eventos escolhidos sao mutacoes de baixa ou moderada frequencia. Telemetria de localizacao nao gera `LogAcao`. O SQLite recebe o log na mesma transacao da mutacao; falha seguida de rollback nao deixa auditoria de sucesso.
