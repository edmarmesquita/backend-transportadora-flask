# Rate limiting

## Arquitetura

O backend compartilhado usa Redis por meio de `REDIS_URL`. Cada verificação
executa um script Lua atômico que:

1. verifica todas as regras da requisição;
2. retorna o TTL da primeira regra excedida;
3. incrementa todos os contadores somente quando nenhuma regra foi excedida;
4. configura expiração automática na primeira contagem de cada janela.

As chaves usam o namespace `transportadora:rate-limit` e incluem somente a
operação e o IP ou a identidade numérica do JWT. Senhas, JWTs, secrets e dados
do payload não são armazenados.

## Política

| Fluxo | Chave | Limite |
| --- | --- | --- |
| `POST /api/login` | IP | 5 por minuto |
| `POST /api/cotacoes` | IP | 5 por minuto e 30 por hora |
| `GET /api/rastreamento/<codigo>` | IP | 30 por minuto |
| uploads de admin e motorista | identidade numérica do JWT | 10 por minuto |

Excessos retornam JSON genérico com status `429` e `Retry-After` em segundos.
O limiter não retorna a chave usada nem informa se um usuário existe.

## Ambientes e fallback

`APP_ENV` aceita `development`, `test`, `staging` ou `production`. Se não
for informada, a aplicação usa `RAILWAY_ENVIRONMENT_NAME` e, fora do Railway,
assume `development`.

- `development` e `test`: `REDIS_URL` é opcional; sem ela, o limiter em
  memória permanece disponível para desenvolvimento e testes locais.
- `staging` e `production`: `REDIS_URL` é obrigatória. A aplicação falha de
  forma explícita durante a inicialização se a variável estiver ausente ou se
  a conexão Redis não puder ser estabelecida.

Não existe fallback silencioso para memória em staging ou produção. Uma falha
do Redis durante a execução também não libera a requisição: a operação falha
fechada, sem expor a URL de conexão.

## IP e proxy

Em `staging` e `production` executados no Railway, os limites por IP preferem
o header `X-Real-IP`, documentado pelo Railway como o identificador do IP
remoto do cliente em requisições públicas. O header somente é aceito quando
contém um único endereço IPv4 ou IPv6 validado pela biblioteca padrão
`ipaddress`. Valores vazios, listas, portas, texto arbitrário, espaços extras e
identificadores de escopo são rejeitados.

A confiança em `X-Real-IP` fica limitada a processos com `APP_ENV` igual a
`staging` ou `production` e com `RAILWAY_ENVIRONMENT_NAME` presente. A premissa
de segurança é que o tráfego público passou pelo edge proxy do Railway, que
fornece esse header. Fora dessa fronteira, ou se o header estiver ausente ou
inválido, a chave usa `request.remote_addr`.

`X-Forwarded-For` continua ignorado. `TRUSTED_PROXY_HOPS=0` e a configuração
do `ProxyFix` não são alterados por esta correção.

## Escala

Todas as instâncias e threads que usam a mesma `REDIS_URL` compartilham os
contadores. A expiração é mantida pelo Redis, sem limpeza periódica no processo
Flask. O limiter em memória continua local ao processo e deve ser usado somente
em desenvolvimento ou testes.

## Rotas autenticadas avaliadas

Uploads de comprovantes recebem limite específico por identidade JWT. Login,
cotação pública e rastreamento público recebem limites por IP. As demais
escritas administrativas permanecem sem limite genérico adicional nesta fase.
