# Gate local pre-staging

## Execucao

Use o ambiente virtual existente e nao instale dependencias:

```powershell
$python = (Resolve-Path .\venv\Scripts\python.exe).Path
& $python -m unittest discover -s tests -p "test_pre_staging_*.py" -v
```

A suite cria SQLite e uploads em `TemporaryDirectory`, configura um segredo e
bootstrap temporarios, e nao acessa `database.db` real.

## Escopo

O gate verifica bootstrap limpo e repetido, configuracao insegura, jornada
administrativa, isolamento dinamico de clientes, usuario inativo, JWT,
rate limiting, contrato minimo de rastreamento, upload/download privado,
CORS e integridade SQLite temporaria. Checks de producao complementares sao
executados pelo script abaixo e pelos comandos do relatorio da fase.

```powershell
& $python .\scripts\check_pre_staging.py
```

## Politica de dados

Nao executar a suite contra o banco real. Para um ambiente por transportadora,
o banco, uploads e segredos devem ser proprios da instalacao. O gate nao faz
deploy, migration, backup sobre o original, `git add`, commit ou push.

## Classificacao

- P0: indisponibilidade, perda de dados, bypass de autorizacao ou segredo inseguro que impeça staging.
- P1: falha relevante que impede uso comercial, mas nao impede staging controlado.
- P2: risco ou melhoria sem bloqueio de staging.

## Resultado da remediacao 2G.7A.1

- Waitress 3.0.2 foi instalado somente no venv usando `requirements.txt`.
- JWT ausente, invalido, malformado e expirado retornam 401 JSON generico.
- Excecoes nao HTTP em `/api/...` retornam 500 JSON generico.
- HTTPException continua preservada, sem converter 400, 401, 403, 404, 409,
  413 ou 429 em 500.

## Resultado deste gate

- Suite automatizada: 10 testes passaram em SQLite e uploads temporarios.
- Bootstrap vazio/repetido, jornada administrativa, IDOR de clientes,
	usuario inativo, contrato minimo de rastreamento, CORS e rate limiting:
	passaram nos cenarios cobertos.
- Persistencia entre dois processos: passou com banco e uploads temporarios.
- Backup/restore local do banco e uploads reais, fora do repositorio:
	integridade `ok`, zero foreign keys invalidas, 22 registros e 22 arquivos,
	sem ausentes ou arquivos sem registro.
- Contencao SQLite moderada: 20 transacoes, zero erros de lock.
- Headers de seguranca: CSP, X-Content-Type-Options, Referrer-Policy,
	X-Frame-Options e HSTS nao sao emitidos pela aplicacao atualmente.
- Frontend: TypeScript/build passaram; bundle principal de aproximadamente
	916 kB gera aviso P2 de code splitting.

### Bloqueadores e riscos

- **P2:** headers de seguranca ausentes e bundle acima de 500 kB. A decisao de
	CSP/HSTS depende do dominio HTTPS e do proxy/frontend de staging.

O veredito local apos a remediacao e `PRONTO PARA STAGING: SIM`. Os itens P2
continuam fora desta subfase e nao foram alterados. A aplicacao nao foi
hospedada e nenhum provedor foi acessado.
