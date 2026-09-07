# Rate limiting da V1

O limiter atual e propositalmente local ao processo Flask. Ele usa memoria,
`threading.Lock` e janelas monotonicamente cronometradas. Nao ha dependencia
nova nem alteracao de banco.

## Politica

| Fluxo | Chave | Limite |
| --- | --- | --- |
| `POST /api/login` | IP | 5 por minuto |
| `POST /api/cotacoes` | IP | 5 por minuto e 30 por hora |
| `GET /api/rastreamento/<codigo>` | IP | 30 por minuto |
| uploads de admin e motorista | identidade numerica do JWT | 10 por minuto |

Os demais endpoints autenticados nao recebem um limite generico nesta fase.
As rotas de escrita autenticadas permanecem protegidas por JWT e autorizacao;
um limite global conservador sera avaliado com metricas reais de uso.

Excessos retornam JSON generico com status 429 e `Retry-After` em segundos.
O limiter nao retorna a chave usada nem informa se um usuario existe.

## IP e proxy

Por padrao, `TRUSTED_PROXY_HOPS=0`: o IP vem de `request.remote_addr` e
qualquer `X-Forwarded-For` recebido diretamente e ignorado. Em staging ou
producao, defina o numero exato de proxies reversos sob controle da equipe,
por exemplo `TRUSTED_PROXY_HOPS=1` para um unico proxy confiavel. O valor
habilita `ProxyFix` somente para essa quantidade de saltos; nao use o valor
para aceitar headers arbitrarios de clientes.

Em desenvolvimento local, mantenha zero. Em staging, configure conforme a
topologia confirmada e teste o endereco observado. Em producao, confirme a
cadeia do provedor antes de habilitar.

Uma quantidade incorreta de hops pode fazer muitos usuarios compartilharem o
IP do proxy, reduzindo a efetividade do limite. Se houver confianca em hops
que nao pertencem a infraestrutura controlada, um cliente pode forjar o IP e
contornar a cota. Essa configuracao deve ser homologada no staging do provedor.

## Storage e escala

O estado em memoria e aceitavel para a V1 com uma unica instancia. Reiniciar o
processo zera os contadores. Multiplas instancias exigem storage compartilhado,
como Redis, e uma decisao de infraestrutura antes do deploy horizontal.

Flask-Limiter nao foi adicionado nesta fase: `requirements.txt` permanece
inalterado e nao houve instalacao automatica. Ele continua sendo uma opcao
para a proxima etapa caso Redis ou outra estrategia compartilhada seja
aprovada.

## Rotas autenticadas avaliadas

Uploads de comprovantes sao a escrita com maior risco de abuso e recebem
limite especifico por identidade JWT. Login, cotacao publica e rastreamento
publico recebem limites especificos. As demais escritas administrativas sao
operacoes autenticadas de baixo volume relativo e ficam sem limite adicional
na V1 para evitar quebrar fluxos existentes.