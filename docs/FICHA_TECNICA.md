# Ficha técnica — Estudo experimental de protocolos Web

> Documento técnico do estado efetivamente implementado e validado do projeto. Os dados numéricos têm como fonte o lote oficial `20261030T185905Z` e os artefatos de `results/processed/`. Esta ficha não substitui o futuro relatório acadêmico.

## 1. Identificação e visão geral

| Campo | Identificação |
|---|---|
| Projeto | Estudo experimental de desempenho de protocolos Web em ambiente emulado |
| Disciplina | Redes de Computadores II |
| Instituição | Universidade Federal do Piauí (UFPI) |
| Avaliação | Segunda Avaliação — trabalho prático |
| Protocolos | HTTP/1.1, HTTP/2 com TLS 1.3 e HTTP/3 sobre QUIC |
| Lote oficial | `20261030T185905Z` |
| Estado | Infraestrutura, cliente, automação, coleta e processamento estatístico concluídos |

O objetivo geral é investigar experimentalmente o comportamento dos três protocolos em condições de rede controladas. O ambiente combina contêineres Linux, três servidores, um cliente assíncrono e emulação com `tc netem` para comparar uma rede LAN de baixa latência com uma WAN de 50 ms de RTT desejado e 2% de perda sintética na direção servidor–cliente.

Objetivos específicos:

- medir TTFB, duração, throughput, RPS e percentis de latência;
- separar o custo inicial de conexão (`cold`) do uso de conexões previamente aquecidas (`warm`);
- avaliar uma transferência grande de 50 MiB e uma bateria de 100 objetos de 10 KiB;
- observar o efeito conjunto de latência e perda sem presumir superioridade de um protocolo;
- preservar medições individuais e produzir estatísticas sobre dez repetições independentes.

Foram executados 12 testes, dez repetições por teste e dois modos por repetição, totalizando 240 JSONs oficiais. A Carga B `cold` usa somente um objeto de 10 KiB; a Carga B `warm` usa os 100 objetos concorrentes. Esses dois casos não são cargas equivalentes.

## 2. Tecnologias utilizadas

As versões abaixo são apenas as que puderam ser verificadas no ambiente, nos arquivos ou nos registros do projeto. Tags móveis e pacotes Alpine sem versão fixada são identificados como tais.

| Tecnologia | Versão verificável | Função no projeto |
|---|---|---|
| Windows | 25H2, build 26200.9711 | Sistema hospedeiro registrado na preparação |
| Docker Desktop | 4.74.0 | Execução dos contêineres Linux no Windows |
| Docker Engine/CLI | 29.4.3 | Construção e gerenciamento dos contêineres |
| Docker Compose | 5.1.3 | Orquestração dos quatro serviços e da rede `net_bench` |
| Python | 3.12.10 no ambiente virtual; imagem `python:3.12-alpine` no cliente | Cliente, validação, geração de cargas e análise |
| `asyncio` | Biblioteca padrão do Python 3.12 | Concorrência assíncrona |
| HTTPX | 0.28.1 | HTTP/1.1 e HTTP/2 no cliente |
| aioquic | 1.7.0 | QUIC e HTTP/3 no cliente e no validador |
| NGINX | 1.31.8 registrado na validação; Dockerfile usa `nginx:alpine` | Servidores HTTP/1.1 e HTTP/2 |
| Caddy | 2.7.6 registrado; imagem `caddy:2.7-alpine` | Servidor HTTP/3/QUIC |
| TLS | 1.3 | Segurança do HTTP/2 e integrada ao QUIC |
| Linux Traffic Control | versão não registrada | Manipulação da disciplina de enfileiramento em `eth0` |
| `tc netem` | módulo do kernel; versão não registrada | Atraso e perda sintéticos |
| `iproute2` | pacote Alpine sem versão fixada | Disponibiliza `ip` e `tc` nos quatro contêineres |
| Matplotlib | 3.11.2 | Seis gráficos estatísticos em PNG |
| Shell POSIX / Git Bash | Git 2.51.0; Bash 5.2.37 registrado | Automação e scripts de rede no Windows |
| OpenSSL | 3.2.4 no Git Bash; Python ligado ao OpenSSL 3.0.16 | Certificado autoassinado e TLS do cliente |
| JSON | esquema interno 2 | Dados brutos de cada medição |
| CSV | texto tabular | Resultados estatísticos consolidados |

`requirements.txt` fixa `httpx[http2]==0.28.1`, `aioquic==1.7.0` e `matplotlib==3.11.2`. A imagem do cliente instala apenas HTTPX e aioquic, pois o processamento estatístico ocorre no host. `asyncio`, `csv`, `json` e `statistics` pertencem à biblioteca padrão.

## 3. Arquitetura do sistema

### 3.1 Componentes

| Serviço Compose | Contêiner | Implementação | Transporte e porta interna | Porta no host | IP interno |
|---|---|---|---|---|---|
| `server-http1` | `server_http11` | NGINX | HTTP/1.1, TCP 80 | `8080:80/tcp` | `172.20.0.10` |
| `server-http2` | `server_http2_tls` | NGINX | HTTP/2, TCP 443, TLS 1.3 | `8443:443/tcp` | `172.20.0.20` |
| `server-http3` | `server_http3_quic` | Caddy | HTTP/3, UDP 443, TLS 1.3 integrada; TCP 443 também publicado | `9443:443/tcp` e `9443:443/udp` | `172.20.0.30` |
| `network-client` | `network_client` | Python 3.12, HTTPX e aioquic | Cliente sem porta publicada | — | `172.20.0.40` |

Todos os serviços participam da bridge `net_bench`, com sub-rede `172.20.0.0/16`. A resolução pelos nomes Compose permite ao cliente usar `http://server-http1`, `https://server-http2` e `https://server-http3`.

### 3.2 Diagrama textual

```text
Host Windows / Docker Desktop
│
├── portas 8080, 8443 e 9443 para validação pelo host
│
└── rede bridge net_bench — 172.20.0.0/16
    │
    ├── network_client       172.20.0.40
    │   ├── HTTPX: HTTP/1.1 e HTTP/2
    │   ├── aioquic: HTTP/3
    │   └── /app/results/raw ── bind mount ──> results/raw/ no host
    │
    ├── server_http11        172.20.0.10 :80/TCP
    ├── server_http2_tls     172.20.0.20 :443/TCP
    └── server_http3_quic    172.20.0.30 :443/UDP e :443/TCP

    eth0 dos quatro contêineres
    └── tc netem, autorizado por NET_ADMIN
```

### 3.3 Volumes e permissões

- `servers/content/` é montado nos três servidores; nos servidores, somente para leitura.
- Certificado e chave de `servers/certs/` são montados nos servidores TLS. O certificado público também é montado no cliente como autoridade confiável.
- `client/` e `scripts/` são montados no cliente para leitura.
- `results/raw/` é montado com escrita em `/app/results/raw`; assim, cada JSON criado no contêiner persiste diretamente no host.
- O conteúdo é montado com escrita no cliente porque `generate_workloads.py` cria ou valida as cargas antes da execução.
- Os quatro serviços recebem `NET_ADMIN`. Não há uso de `--privileged` na implementação atual.

## 4. Estrutura do código-fonte

```text
.
├── client/
│   ├── benchmark.py
│   ├── httpx_benchmark.py
│   ├── http3_benchmark.py
│   ├── metrics.py
│   ├── models.py
│   ├── requirements.txt
│   └── network/Dockerfile
├── docs/
│   ├── specification-notes.md
│   └── FICHA_TECNICA.md
├── results/
│   ├── raw/
│   └── processed/
│       └── figures/
├── scripts/
│   ├── analysis/process_results.py
│   ├── network/common.sh
│   ├── network/apply_lan.sh
│   ├── network/apply_wan.sh
│   ├── network/reset_network.sh
│   ├── generate_certs.sh
│   ├── generate_workloads.py
│   ├── validate_experiment.py
│   └── validate_http3.py
├── servers/
│   ├── certs/
│   ├── content/
│   ├── http1/{Dockerfile,nginx.conf}
│   ├── http2/{Dockerfile,nginx.conf}
│   └── http3/{Dockerfile,Caddyfile}
├── docker-compose.yml
├── requirements.txt
├── run_experiments.sh
└── README.md
```

| Arquivo ou módulo | Responsabilidade efetiva |
|---|---|
| `docker-compose.yml` | Serviços, IPs, portas, bind mounts, rede e `NET_ADMIN` |
| `servers/http1/nginx.conf` | HTTP/1.1 sem TLS, `gzip off`, conteúdo estático |
| `servers/http2/nginx.conf` | HTTP/2, TLS 1.3, certificado local, `gzip off` |
| `servers/http3/Caddyfile` | HTTPS na porta 443, protocolos h1/h2/h3, TLS 1.3 e arquivos estáticos |
| `client/benchmark.py` | CLI, seleção de protocolo/carga, metadados, validação de bytes e JSON |
| `client/httpx_benchmark.py` | Requisições HTTP/1.1 e HTTP/2, pools, TLS e medição em fluxo |
| `client/http3_benchmark.py` | Protocolo aioquic, streams HTTP/3, ALPN e medição em fluxo |
| `client/metrics.py` | RPS, throughput, médias e percentis internos |
| `client/models.py` | Estrutura do registro individual e temporização em microssegundos |
| `scripts/network/*.sh` | Aplicação, inspeção e remoção do `netem` |
| `scripts/generate_workloads.py` | Geração determinística e validação de tamanho/hash das cargas |
| `run_experiments.sh` | Execução integral T01–T12, validação e limpeza |
| `scripts/validate_experiment.py` | Validação individual de protocolo, TLS, bytes, conexões e métricas |
| `scripts/validate_http3.py` | Teste funcional HTTP/3 independente do benchmark |
| `scripts/analysis/process_results.py` | Auditoria do lote, estatísticas, outliers, CSVs e seis gráficos |

## 5. Funcionamento dos protocolos

### 5.1 HTTP/1.1

O servidor NGINX escuta TCP 80 sem TLS. O cliente HTTPX exige negociação `HTTP/1.1`. No modo `cold`, um `AsyncClient` novo é criado para cada requisição e fechado em seguida. No modo `warm`, uma requisição de aquecimento não contabilizada prepara o pool.

Na Carga B `warm`, o executor configura `HTTP1_CONNECTIONS=6` por padrão. O HTTPX usa até seis conexões TCP persistentes e distribui as 100 operações assíncronas entre elas. Isso mitiga a ausência de multiplexação, mas não equivale a streams independentes em uma única conexão. O HTTP/1.1 do projeto não usa pipelining.

### 5.2 HTTP/2

O segundo NGINX oferece HTTP/2 sobre uma conexão TCP com TLS restrita à versão 1.3. A seleção ocorre por ALPN e a resposta só é aceita se o HTTPX informar `HTTP/2` e `TLSv1.3`. O cliente limita o pool a uma conexão no modo `warm` e lança as requisições com `asyncio.gather`; a biblioteca as multiplexa como streams HTTP/2.

O HTTP/2 remove a serialização HTTP/1.1 na camada de aplicação, mas todos os streams continuam sobre o mesmo fluxo de bytes TCP. Uma perda pode atrasar a entrega ordenada do TCP para dados posteriores, embora esta coleta não tenha registrado retransmissões nem bloqueios diretamente.

### 5.3 HTTP/3

O Caddy recebe QUIC em UDP 443 e negocia ALPN `h3`. O cliente cria uma `H3Connection` sobre aioquic, atribui um stream QUIC a cada requisição e processa eventos de cabeçalhos e dados. No modo `warm`, uma única conexão recebe uma requisição de aquecimento e, em seguida, os 100 objetos são enviados concorrentemente em streams distintos.

O QUIC integra TLS 1.3 e fornece entrega ordenada por stream, sem exigir uma ordem global entre todos os streams. Isso reduz o bloqueio entre streams causado pela entrega ordenada global do TCP; não elimina perda, retransmissão ou controle de congestionamento da conexão.

### 5.4 Controle de congestionamento: limite de verificação

Nenhum JSON registra `tcp_congestion_control`, janela de congestionamento ou algoritmo do Caddy. Portanto, não é possível afirmar que os fluxos oficiais TCP usaram CUBIC nem que o HTTP/3 usou BBR. O `QuicConfiguration` do aioquic 1.7.0, que o cliente não sobrescreve, tem `reno` como padrão para o tráfego enviado pelo cliente; isso não identifica o algoritmo do Caddy, que envia a maior parte dos bytes nos downloads. BBR não foi configurado em nenhum arquivo do projeto.

## 6. Emulação de rede

| Cenário | Configuração no cliente | Configuração em cada servidor | RTT desejado | Perda desejada |
|---|---|---|---:|---:|
| LAN | `delay 0.5ms` | `delay 0.5ms` | 1 ms | 0% |
| WAN | `delay 25ms` | `delay 25ms loss 2%` | 50 ms | 2% no tráfego servidor–cliente |

`netem` atua na saída da interface. Em cada RTT, o pedido atravessa a saída do cliente e a resposta atravessa a saída do servidor; por isso o atraso foi dividido entre os dois sentidos. A perda WAN fica somente nos servidores para evitar a composição de duas probabilidades próximas de 2%, que produziria perda total próxima de 4%.

`common.sh` verifica se os quatro contêineres estão ativos e se possuem `eth0`. `apply_lan.sh` e `apply_wan.sh` usam `tc qdisc replace`, conferem a presença de `netem` e validam a perda esperada. `reset_network.sh` remove a raiz de `eth0` em todos os contêineres e falha se ainda encontrar `netem`.

Valores observados na validação da Etapa 3:

| Estado | Configurado | RTT médio observado | Perda observada |
|---|---|---:|---:|
| Original | sem `netem` | 0,102–0,119 ms | 0% |
| LAN | 0,5 ms em cada sentido | 1,248–1,319 ms | 0% |
| WAN | 25 ms em cada sentido; 2% na saída dos servidores | 50,442–50,562 ms | 1,4–2,2% em 500 amostras por servidor |
| Após reset | sem `netem` | 0,077–0,117 ms | 0% |

O intervalo medido inclui overhead do ambiente virtualizado; os valores configurados não são apresentados como medições exatas.

## 7. Funcionamento do cliente de benchmark

### 7.1 Fluxo geral

1. `benchmark.py` valida CLI, protocolo, URL, recursos, contagem e timeout.
2. Um UUID identifica a execução e timestamps UTC marcam início/fim.
3. HTTPX ou aioquic executa as operações assíncronas.
4. `perf_counter_ns()` mede cabeçalhos, primeiro byte do corpo e último byte.
5. O corpo é lido em fluxo; somente a contagem de bytes é mantida.
6. Protocolo negociado, TLS, status, compressão e tamanho são verificados.
7. Falhas viram `RequestRecord` com erro; não desaparecem da exportação.
8. `metrics.py` resume apenas requisições bem-sucedidas para RPS e percentis.
9. O JSON é aberto em modo exclusivo (`x`), impedindo sobrescrita.

Cada URL recebe `benchmark_nonce` único e os cabeçalhos `Cache-Control: no-cache, no-store`, `Pragma: no-cache` e `Accept-Encoding: identity`. NGINX mantém `gzip off`. Isso evita cache no cliente e compressão, mas não limpa o page cache do sistema operacional do servidor.

### 7.2 Cold Connection

- HTTP/1.1 e HTTP/2: um `AsyncClient` novo por recurso, encerrado após a resposta.
- HTTP/3: um novo contexto `connect()` QUIC por recurso.
- A medição começa antes da criação/negociação da conexão; o TTFB inclui os handshakes.
- Na bateria oficial, Carga A `cold` transfere 50 MiB; Carga B `cold` mede um único arquivo de 10 KiB.

### 7.3 Warm Connection

- Uma requisição de aquecimento é executada e não entra nas métricas.
- HTTP/2 usa uma conexão TCP/TLS 1.3 com streams concorrentes.
- HTTP/3 usa uma conexão QUIC/TLS 1.3 com streams concorrentes.
- HTTP/1.1 usa um pool persistente de até seis conexões na Carga B; na Carga A usa uma conexão.
- A janela medida começa depois do aquecimento e termina após a última operação.

## 8. Cargas experimentais

| Carga | Arquivos | Tamanho por objeto | Total por bateria warm | Finalidade |
|---|---:|---:|---:|---|
| A | 1 | 52.428.800 bytes (50 MiB) | 52.428.800 bytes | Transferência sustentada e throughput |
| B | 100 | 10.240 bytes (10 KiB) | 1.024.000 bytes | Latência, concorrência e multiplexação |

`generate_workloads.py` gera conteúdo determinístico, grava atomicamente e valida tamanhos. O arquivo grande auditado possui SHA-256 `624bbe3f61588f97cfaad1af50360bb8c5fc94774d3c15dbf471dcd42b9bea8e`. O manifesto da Carga B contém 100 caminhos e os 100 objetos somam 1.024.000 bytes.

Na Carga A, cold e warm transferem o mesmo objeto integral. Na Carga B, cold usa apenas `object-001.bin`, enquanto warm usa os 100 caminhos do manifesto. Por isso, duração e RPS de cold e warm da Carga B não devem ser comparados como se representassem a mesma quantidade de trabalho.

## 9. Matriz experimental

| ID | Carga | Protocolo | Cenário | Objetivo específico |
|---|---|---|---|---|
| T01 | A | HTTP/1.1 | LAN | Referência de transferência TCP sem TLS em baixa latência |
| T02 | A | HTTP/2 + TLS 1.3 | LAN | Transferência HTTP/2 cifrada em baixa latência |
| T03 | A | HTTP/3 + QUIC | LAN | Transferência QUIC sem perda sintética |
| T04 | A | HTTP/1.1 | WAN | Efeito de 50 ms e 2% de perda sobre TCP |
| T05 | A | HTTP/2 + TLS 1.3 | WAN | HTTP/2/TCP sob latência e perda |
| T06 | A | HTTP/3 + QUIC | WAN | QUIC sob latência e perda |
| T07 | B | HTTP/1.1 | LAN | Pool HTTP/1.1 com até seis conexões |
| T08 | B | HTTP/2 + TLS 1.3 | LAN | Multiplexação HTTP/2 em baixa latência |
| T09 | B | HTTP/3 + QUIC | LAN | Streams HTTP/3 em baixa latência |
| T10 | B | HTTP/1.1 | WAN | Pool HTTP/1.1 sob degradação |
| T11 | B | HTTP/2 + TLS 1.3 | WAN | Streams HTTP/2 sobre TCP degradado |
| T12 | B | HTTP/3 + QUIC | WAN | Streams QUIC sob degradação |

Cada ID foi repetido dez vezes. Cada repetição gerou um arquivo cold e um warm: `12 × 10 × 2 = 240` medições. O modo de execução é identificado no JSON e os dois modos permanecem separados no processamento.

## 10. Métricas de desempenho

### 10.1 Métricas por execução

| Métrica | Definição implementada | Unidade |
|---|---|---|
| Tempo de cabeçalhos | início da operação até os cabeçalhos | µs no JSON |
| TTFB | início da operação até o primeiro byte não vazio do corpo | µs no JSON; ms nos CSVs |
| Tempo individual | início até o último byte de uma resposta | µs no JSON; ms nos CSVs |
| Duração da bateria | janela monotônica da execução medida | s |
| RPS | `requisições bem-sucedidas / duração da janela` | req/s |
| Throughput | `(bytes recebidos × 8) / (duração × 1.000.000)` | Mbps decimais |
| Sucesso | `sucessos / (sucessos + falhas) × 100` | % |

O TTFB adotado é o intervalo observável pelo cliente, do início da operação ao primeiro byte do corpo. Ele não corresponde literalmente ao intervalo servidor-cabeçalho → cliente-corpo descrito no enunciado, pois o cliente não observa o instante interno de emissão no servidor. `headers_time_us` permanece separado. A temporização usa relógio monotônico com resolução de nanossegundos e é exportada em microssegundos com três casas.

### 10.2 Estatísticas entre repetições

Para os dez valores independentes `x_i` de cada combinação:

```text
média = (Σ x_i) / n
s = √[Σ(x_i − média)² / (n − 1)]
IC95 = média ± t(0,975; 9) × s / √n
t(0,975; 9) = 2,2621571627409915
```

A mediana é o p50. Os percentis usam interpolação linear na posição `(n − 1) × p`. O p99 entre dez repetições é descritivo e sensível aos extremos; não equivale a um percentil estimado de uma população grande.

Na Carga B warm, `client/metrics.py` primeiro calcula p50/p99 entre as 100 respostas de uma bateria. `process_results.py` trata cada p50/p99 interno como um valor da respectiva repetição e só depois calcula média, desvio e IC95 sobre dez repetições. As 100 respostas não são tratadas como 100 experimentos independentes.

## 11. Automação dos experimentos

`run_experiments.sh` executa o seguinte fluxo:

1. desativa conversão automática de caminhos do Git Bash com `MSYS_NO_PATHCONV=1`;
2. valida argumentos, Docker, Compose e acesso ao Engine;
3. cria `batch_id` UTC e instala `trap` de limpeza;
4. executa `docker compose up -d --build`;
5. gera/valida as cargas dentro do cliente;
6. realiza preflight de `/health.txt` nos três protocolos;
7. aplica LAN e executa T01–T03 e T07–T09;
8. aplica WAN e executa T04–T06 e T10–T12;
9. para cada teste/repetição, executa cold e depois warm;
10. valida imediatamente cada JSON com `validate_experiment.py`;
11. registra qualquer falha em arquivo do lote;
12. no `trap`, remove `netem` e executa `docker compose down`.

Comandos reais, em Git Bash:

```sh
# uma repetição de cada teste, ainda com cargas integrais
sh run_experiments.sh --smoke

# coleta oficial padrão: dez repetições
sh run_experiments.sh

# quantidade explicitamente configurada
sh run_experiments.sh --repetitions 3
```

O `--smoke` produz 24 medições, mas não é agregado ao lote oficial. O executor nunca apaga JSONs já gravados.

## 12. Coleta e integridade dos dados

Cada JSON possui `schema_version: 2`, objeto `run` e lista `requests`. `run` contém UUID, lote, teste, repetição, tipo de execução, timestamps UTC, protocolo, cenário, carga, modo, recursos, bytes esperados, estratégia de concorrência e resumo. Cada requisição contém protocolo negociado, transporte, TLS, status, temporizações, bytes, sucesso, erro e conexão.

O padrão oficial é:

```text
20261030T185905Z_T01_r01_cold_<timestamp>.json
20261030T185905Z_T01_r01_warm_<timestamp>.json
```

`validate_experiment.py` exige esquema, metadados, quantidade de registros, status 200, bytes corretos, protocolo negociado, TLS 1.3 em HTTP/2 e HTTP/3 e coerência de conexões. `process_results.py` repete e amplia a auditoria, rejeitando ausências, duplicações, NaN, infinito e inconsistências de métricas.

| Item do lote oficial | Valor verificado |
|---|---:|
| Identificador | `20261030T185905Z` |
| JSONs | 240 |
| Cold | 120 |
| Warm | 120 |
| Medições válidas | 240 |
| Medições inválidas | 0 |
| Requisições agendadas | 6.180 |
| Requisições bem-sucedidas | 6.180 |
| Requisições com falha | 0 |
| Bytes recebidos | 6.353.510.400 |
| Taxa de sucesso | 100% |
| Divergências SHA-256 contra o manifesto | 0 de 240 |

O manifesto `results/raw/20261030T185905Z_official_manifest.txt` contém o hash de cada JSON. A análise lê `results/raw/` sem alterar, mover ou excluir os arquivos. Os 52 apontamentos do critério de Tukey são marcações por métrica, podem se referir repetidamente à mesma execução e foram preservados; nenhuma observação foi excluída.

## 13. Resultados estatísticos completos

As tabelas abaixo arredondam somente para apresentação. Os valores completos estão nos CSVs de `results/processed/`. `s` é o desvio-padrão amostral e todos os IC95 usam `n=10`. Nas tabelas entre repetições, mediana e p50 são a mesma estatística.

### 13.1 TTFB por teste e modo

| Teste | Carga | Protocolo | Cenário | Modo | Média (ms) | Mediana/p50 | s | p99 | IC95 |
|---|---|---|---|---|---:|---:|---:|---:|---|
| T01 | A | HTTP/1.1 | LAN | cold | 33.766 | 32.595 | 3.983 | 43.673 | [30.917; 36.615] |
| T01 | A | HTTP/1.1 | LAN | warm | 5.144 | 5.305 | 0.386 | 5.577 | [4.868; 5.421] |
| T02 | A | HTTP/2 | LAN | cold | 37.682 | 37.945 | 1.275 | 39.327 | [36.771; 38.594] |
| T02 | A | HTTP/2 | LAN | warm | 6.489 | 5.843 | 1.705 | 10.797 | [5.270; 7.709] |
| T03 | A | HTTP/3 | LAN | cold | 20.028 | 20.089 | 0.652 | 20.879 | [19.562; 20.494] |
| T03 | A | HTTP/3 | LAN | warm | 4.219 | 4.083 | 0.398 | 4.999 | [3.934; 4.504] |
| T04 | A | HTTP/1.1 | WAN | cold | 237.760 | 136.777 | 321.599 | 1061.963 | [7.702; 467.818] |
| T04 | A | HTTP/1.1 | WAN | warm | 58.162 | 57.644 | 3.832 | 63.579 | [55.421; 60.903] |
| T05 | A | HTTP/2 | WAN | cold | 260.023 | 248.305 | 35.844 | 352.015 | [234.382; 285.665] |
| T05 | A | HTTP/2 | WAN | warm | 79.513 | 61.463 | 33.948 | 153.729 | [55.228; 103.798] |
| T06 | A | HTTP/3 | WAN | cold | 153.575 | 146.807 | 16.212 | 191.649 | [141.977; 165.172] |
| T06 | A | HTTP/3 | WAN | warm | 66.107 | 56.228 | 21.562 | 106.813 | [50.682; 81.532] |
| T07 | B | HTTP/1.1 | LAN | cold | 32.359 | 31.820 | 1.340 | 34.901 | [31.400; 33.317] |
| T07 | B | HTTP/1.1 | LAN | warm | 116.112 | 112.067 | 13.677 | 149.189 | [106.328; 125.896] |
| T08 | B | HTTP/2 | LAN | cold | 37.058 | 37.206 | 1.631 | 39.412 | [35.891; 38.225] |
| T08 | B | HTTP/2 | LAN | warm | 145.069 | 142.982 | 10.505 | 168.147 | [137.555; 152.584] |
| T09 | B | HTTP/3 | LAN | cold | 20.745 | 20.605 | 1.717 | 24.447 | [19.517; 21.973] |
| T09 | B | HTTP/3 | LAN | warm | 41.243 | 41.257 | 1.294 | 43.358 | [40.318; 42.169] |
| T10 | B | HTTP/1.1 | WAN | cold | 137.875 | 138.435 | 2.792 | 141.646 | [135.878; 139.873] |
| T10 | B | HTTP/1.1 | WAN | warm | 671.838 | 648.886 | 56.987 | 761.226 | [631.072; 712.604] |
| T11 | B | HTTP/2 | WAN | cold | 357.476 | 239.931 | 346.652 | 1247.311 | [109.497; 605.456] |
| T11 | B | HTTP/2 | WAN | warm | 885.038 | 419.175 | 764.738 | 2266.790 | [337.978; 1432.099] |
| T12 | B | HTTP/3 | WAN | cold | 125.449 | 123.435 | 4.724 | 135.091 | [122.069; 128.828] |
| T12 | B | HTTP/3 | WAN | warm | 182.676 | 184.823 | 31.740 | 247.563 | [159.970; 205.382] |

### 13.2 Duração completa da transferência ou bateria

| Teste | Carga | Protocolo | Cenário | Modo | Média (s) | Mediana/p50 | s | p99 | IC95 |
|---|---|---|---|---|---:|---:|---:|---:|---|
| T01 | A | HTTP/1.1 | LAN | cold | 0.3078 | 0.3082 | 0.0088 | 0.3212 | [0.3015; 0.3141] |
| T01 | A | HTTP/1.1 | LAN | warm | 0.2409 | 0.2327 | 0.0163 | 0.2652 | [0.2293; 0.2526] |
| T02 | A | HTTP/2 | LAN | cold | 0.8623 | 0.8600 | 0.0150 | 0.8896 | [0.8516; 0.8731] |
| T02 | A | HTTP/2 | LAN | warm | 0.7885 | 0.7836 | 0.0164 | 0.8155 | [0.7768; 0.8002] |
| T03 | A | HTTP/3 | LAN | cold | 4.0691 | 4.0057 | 0.1599 | 4.3313 | [3.9547; 4.1835] |
| T03 | A | HTTP/3 | LAN | warm | 3.8661 | 3.8095 | 0.1357 | 4.1141 | [3.7691; 3.9632] |
| T04 | A | HTTP/1.1 | WAN | cold | 162.0298 | 165.2024 | 13.9953 | 173.4380 | [152.0181; 172.0414] |
| T04 | A | HTTP/1.1 | WAN | warm | 174.5162 | 175.4176 | 4.0716 | 180.2484 | [171.6036; 177.4288] |
| T05 | A | HTTP/2 | WAN | cold | 169.0642 | 168.4544 | 10.3088 | 180.7220 | [161.6898; 176.4386] |
| T05 | A | HTTP/2 | WAN | warm | 174.2077 | 173.3196 | 4.8536 | 185.3226 | [170.7357; 177.6798] |
| T06 | A | HTTP/3 | WAN | cold | 118.7359 | 118.4196 | 3.6523 | 123.7150 | [116.1231; 121.3486] |
| T06 | A | HTTP/3 | WAN | warm | 119.2618 | 118.8860 | 3.4320 | 124.1027 | [116.8067; 121.7169] |
| T07 | B | HTTP/1.1 | LAN | cold | 0.0743 | 0.0730 | 0.0043 | 0.0834 | [0.0713; 0.0774] |
| T07 | B | HTTP/1.1 | LAN | warm | 0.2198 | 0.2082 | 0.0284 | 0.2886 | [0.1995; 0.2401] |
| T08 | B | HTTP/2 | LAN | cold | 0.0709 | 0.0711 | 0.0019 | 0.0734 | [0.0696; 0.0723] |
| T08 | B | HTTP/2 | LAN | warm | 0.2854 | 0.2804 | 0.0219 | 0.3373 | [0.2698; 0.3011] |
| T09 | B | HTTP/3 | LAN | cold | 0.1235 | 0.1203 | 0.0090 | 0.1458 | [0.1170; 0.1299] |
| T09 | B | HTTP/3 | LAN | warm | 0.1458 | 0.1453 | 0.0038 | 0.1516 | [0.1430; 0.1485] |
| T10 | B | HTTP/1.1 | WAN | cold | 0.1870 | 0.1869 | 0.0039 | 0.1928 | [0.1842; 0.1897] |
| T10 | B | HTTP/1.1 | WAN | warm | 1.3515 | 1.3512 | 0.1320 | 1.5611 | [1.2570; 1.4459] |
| T11 | B | HTTP/2 | WAN | cold | 0.3945 | 0.2777 | 0.3455 | 1.2812 | [0.1473; 0.6416] |
| T11 | B | HTTP/2 | WAN | warm | 1.7405 | 0.9402 | 1.5595 | 4.5447 | [0.6249; 2.8561] |
| T12 | B | HTTP/3 | WAN | cold | 0.5749 | 0.5505 | 0.0382 | 0.6413 | [0.5476; 0.6022] |
| T12 | B | HTTP/3 | WAN | warm | 1.6727 | 1.8683 | 0.5500 | 2.2814 | [1.2793; 2.0662] |

Na Carga B, as linhas cold representam uma requisição; as warm, 100. A tabela registra ambas sem equipará-las.

### 13.3 Throughput da Carga A

| Teste | Protocolo | Cenário | Modo | Média (Mbps) | Mediana/p50 | s | p99 | IC95 |
|---|---|---|---|---:|---:|---:|---:|---|
| T01 | HTTP/1.1 | LAN | cold | 1363.557 | 1360.902 | 39.115 | 1423.214 | [1335.576; 1391.538] |
| T01 | HTTP/1.1 | LAN | warm | 1747.796 | 1802.544 | 114.569 | 1853.558 | [1665.838; 1829.754] |
| T02 | HTTP/2 | LAN | cold | 486.524 | 487.708 | 8.397 | 495.546 | [480.517; 492.531] |
| T02 | HTTP/2 | LAN | warm | 532.162 | 535.230 | 10.938 | 545.283 | [524.337; 539.986] |
| T03 | HTTP/3 | LAN | cold | 103.216 | 104.708 | 3.946 | 107.139 | [100.394; 106.039] |
| T03 | HTTP/3 | LAN | warm | 108.605 | 110.102 | 3.681 | 111.741 | [105.972; 111.238] |
| T04 | HTTP/1.1 | WAN | cold | 2.610 | 2.539 | 0.273 | 3.288 | [2.415; 2.805] |
| T04 | HTTP/1.1 | WAN | warm | 2.405 | 2.391 | 0.057 | 2.506 | [2.364; 2.445] |
| T05 | HTTP/2 | WAN | cold | 2.490 | 2.490 | 0.168 | 2.887 | [2.370; 2.610] |
| T05 | HTTP/2 | WAN | warm | 2.409 | 2.420 | 0.065 | 2.492 | [2.363; 2.456] |
| T06 | HTTP/3 | WAN | cold | 3.536 | 3.542 | 0.111 | 3.754 | [3.456; 3.615] |
| T06 | HTTP/3 | WAN | warm | 3.520 | 3.528 | 0.102 | 3.697 | [3.447; 3.592] |

### 13.4 RPS da Carga B warm

| Teste | Protocolo | Cenário | Média (req/s) | Mediana/p50 | s | p99 | IC95 |
|---|---|---|---:|---:|---:|---:|---|
| T07 | HTTP/1.1 | LAN | 460.587 | 480.338 | 48.814 | 504.118 | [425.667; 495.506] |
| T08 | HTTP/2 | LAN | 352.013 | 356.632 | 24.147 | 377.676 | [334.739; 369.286] |
| T09 | HTTP/3 | LAN | 686.398 | 688.238 | 17.865 | 708.571 | [673.618; 699.177] |
| T10 | HTTP/1.1 | WAN | 74.626 | 74.024 | 7.212 | 84.037 | [69.467; 79.785] |
| T11 | HTTP/2 | WAN | 118.534 | 109.354 | 89.989 | 259.260 | [54.160; 182.908] |
| T12 | HTTP/3 | WAN | 68.980 | 53.569 | 32.242 | 134.976 | [45.915; 92.044] |

RPS cold da Carga B não é consolidado como comparação de capacidade, pois cada medição cold contém apenas uma requisição.

### 13.5 Percentis internos da Carga B warm

| Teste | Protocolo | Cenário | Percentil interno | Média (ms) | s entre repetições | IC95 |
|---|---|---|---|---:|---:|---|
| T07 | HTTP/1.1 | LAN | p50 | 115.163 | 14.872 | [104.524; 125.802] |
| T07 | HTTP/1.1 | LAN | p99 | 206.337 | 26.068 | [187.689; 224.985] |
| T08 | HTTP/2 | LAN | p50 | 143.586 | 11.159 | [135.604; 151.569] |
| T08 | HTTP/2 | LAN | p99 | 260.060 | 21.150 | [244.930; 275.189] |
| T09 | HTTP/3 | LAN | p50 | 125.151 | 3.183 | [122.875; 127.428] |
| T09 | HTTP/3 | LAN | p99 | 139.242 | 5.867 | [135.045; 143.438] |
| T10 | HTTP/1.1 | WAN | p50 | 682.263 | 66.693 | [634.554; 729.972] |
| T10 | HTTP/1.1 | WAN | p99 | 1265.070 | 104.400 | [1190.387; 1339.753] |
| T11 | HTTP/2 | WAN | p50 | 943.284 | 870.426 | [320.619; 1565.949] |
| T11 | HTTP/2 | WAN | p99 | 1724.952 | 1564.557 | [605.735; 2844.168] |
| T12 | HTTP/3 | WAN | p50 | 1568.009 | 518.485 | [1197.107; 1938.911] |
| T12 | HTTP/3 | WAN | p99 | 1667.171 | 549.078 | [1274.384; 2059.958] |

### 13.6 Tempo individual médio na Carga B warm

| Teste | Protocolo | Cenário | Média das médias por bateria (ms) | s | IC95 |
|---|---|---|---:|---:|---|
| T07 | HTTP/1.1 | LAN | 117.694 | 13.569 | [107.987; 127.400] |
| T08 | HTTP/2 | LAN | 145.445 | 10.507 | [137.929; 152.961] |
| T09 | HTTP/3 | LAN | 121.966 | 4.084 | [119.044; 124.887] |
| T10 | HTTP/1.1 | WAN | 683.882 | 62.072 | [639.479; 728.286] |
| T11 | HTTP/2 | WAN | 959.769 | 856.464 | [347.092; 1572.446] |
| T12 | HTTP/3 | WAN | 1508.482 | 492.204 | [1156.380; 1860.583] |

Essa métrica descreve o tempo de resposta individual médio; não é a duração completa da bateria da Seção 13.2.

## 14. Gráficos gerados

Todos os gráficos são PNG a 300 DPI. As barras de erro representam IC95 da média calculado sobre dez repetições independentes.

| Figura | Métrica e escopo | Comparação objetiva |
|---|---|---|
| `01_ttfb_cold.png` | TTFB médio cold | três protocolos, LAN/WAN, cargas A e B separadas |
| `02_total_time_load_a_warm.png` | duração warm de 50 MiB | três protocolos em painéis LAN e WAN |
| `03_throughput_load_a_warm.png` | Mbps warm da Carga A | três protocolos em LAN e WAN |
| `04_rps_load_b_warm.png` | RPS da bateria de 100 objetos | três protocolos em LAN e WAN |
| `05_latency_p50_p99_load_b_warm.png` | p50/p99 internos | latência individual e variabilidade entre repetições |
| `06_network_degradation_load_b_warm.png` | duração da bateria, escala log | trabalho equivalente LAN/WAN por protocolo |

### 14.1 TTFB cold

![TTFB cold](../results/processed/figures/01_ttfb_cold.png)

### 14.2 Tempo total da Carga A warm

![Tempo total da Carga A](../results/processed/figures/02_total_time_load_a_warm.png)

### 14.3 Throughput da Carga A warm

![Throughput da Carga A](../results/processed/figures/03_throughput_load_a_warm.png)

### 14.4 RPS da Carga B warm

![RPS da Carga B](../results/processed/figures/04_rps_load_b_warm.png)

### 14.5 Latência p50 e p99 da Carga B warm

![Latência p50 e p99](../results/processed/figures/05_latency_p50_p99_load_b_warm.png)

### 14.6 Impacto LAN/WAN na Carga B warm

![Impacto da degradação](../results/processed/figures/06_network_degradation_load_b_warm.png)

## 15. Discussão técnica dos resultados

### 15.1 Custo inicial e modos de conexão

Nos quatro grupos cold (cargas A/B em LAN/WAN), HTTP/3 apresentou o menor TTFB médio: 20,028 e 20,745 ms em LAN; 153,575 e 125,449 ms em WAN. Esse resultado é compatível com a negociação integrada do QUIC/TLS, mas não isola sozinho o número de RTTs, pois NGINX, Caddy, HTTPX e aioquic são implementações diferentes.

O aquecimento reduziu fortemente o TTFB da Carga A nos três protocolos. Em WAN, por exemplo, HTTP/1.1 passou de 237,760 ms cold para 58,162 ms warm. O T04 cold teve média muito acima da mediana e IC amplo, evidência de uma ou mais repetições extremas; o valor foi preservado.

Na Carga B, comparar diretamente cold e warm seria inválido: cold contém uma resposta e warm contém 100 operações concorrentes. O TTFB warm também inclui efeitos de concorrência e escalonamento, não apenas handshake.

### 15.2 Carga A

Em LAN warm, as médias foram 1.747,796 Mbps para HTTP/1.1, 532,162 Mbps para HTTP/2 e 108,605 Mbps para HTTP/3. Portanto, HTTP/3 não foi o mais rápido no ambiente local. A diferença pode envolver implementação de servidor/cliente, criptografia, caminho de software QUIC em espaço de usuário, tamanho de buffers e agendamento; o experimento não separa esses fatores.

Em WAN warm, HTTP/3 atingiu 3,520 Mbps, contra 2,409 Mbps no HTTP/2 e 2,405 Mbps no HTTP/1.1 — cerca de 46% acima das duas médias TCP. Os IC95 de HTTP/1.1 e HTTP/2 se sobrepõem; o de HTTP/3 ficou acima de ambos. A queda LAN→WAN foi de 99,86% para HTTP/1.1, 99,55% para HTTP/2 e 96,76% para HTTP/3. Esses dados mostram maior throughput HTTP/3 neste cenário específico, sem provar qual mecanismo interno causou a diferença.

Cold e warm da Carga A ficaram próximos em WAN porque o custo de handshake é pequeno diante de aproximadamente dois a três minutos de transferência. Em T04/T05, warm não foi mais rápido que cold na duração total; isso impede assumir que aquecimento sempre melhora uma transferência longa sob perda.

### 15.3 Carga B

Em LAN, HTTP/3 teve o maior RPS médio (686,398), seguido de HTTP/1.1 (460,587) e HTTP/2 (352,013). A latência p99 interna do HTTP/3 também foi a menor (139,242 ms). O resultado do HTTP/1.1 depende do pool de seis conexões e não representa uma única conexão serial.

Em WAN, o ranking pela média de RPS mudou: HTTP/2 118,534; HTTP/1.1 74,626; HTTP/3 68,980. Os três IC95 se sobrepõem, e T11/T12 apresentam grande variabilidade. Assim, não há sustentação para declarar superioridade de HTTP/2 ou HTTP/3 nessa carga WAN sem um teste inferencial adicional e/ou mais repetições.

O p50/p99 interno WAN do HTTP/3 (1.568,009/1.667,171 ms) ficou acima do HTTP/1.1 (682,263/1.265,070 ms). O HTTP/2 teve médias 943,284/1.724,952 ms, mas desvios muito grandes. A queda LAN→WAN de RPS foi 83,80% no HTTP/1.1, 66,33% no HTTP/2 e 89,95% no HTTP/3. Portanto, isolamento entre streams QUIC não garantiu maior RPS neste conjunto real.

### 15.4 Relação com TCP CUBIC, QUIC e BBR

- **TCP CUBIC, tópico indicado como Tanenbaum §6.5.11 no enunciado:** um controle baseado em perda tende a reduzir a janela após perdas e pode sofrer em caminhos de maior RTT. A queda acentuada de throughput em T04/T05 é compatível com perda, retransmissão e limitação de janela, mas o algoritmo TCP ativo não foi registrado; atribuir causalidade especificamente ao CUBIC seria hipótese.
- **QUIC, tópico indicado como §6.6.1:** streams independentes evitam que a perda de dados de um stream imponha entrega ordenada aos demais. Isso é uma propriedade arquitetural relevante para T06/T12. Contudo, a conexão QUIC ainda tem controle de congestionamento e recuperação de perdas; os resultados mistos da Carga B mostram que a propriedade não implica desempenho superior universal.
- **BBR, tópico indicado como §6.6.2:** BBR é um algoritmo de controle de congestionamento, não uma propriedade automática do QUIC. O projeto não o habilita nem registra. Consequentemente, BBR só pode ser apresentado como contraste teórico com controles baseados em perda, não como explicação factual dos resultados.

Há uma limitação bibliográfica adicional: o PDF local disponível do livro apresenta títulos diferentes nos números §6.5.11, §6.6.1 e §6.6.2 em relação aos rótulos do enunciado. Esta ficha mantém os tópicos exigidos pela avaliação, mas não fabrica citações literais, páginas ou conteúdo de uma edição não identificada.

## 16. Problemas encontrados e soluções adotadas

| Problema comprovado | Causa ou risco | Solução existente | Arquivos |
|---|---|---|---|
| `tc` indisponível no Windows | Traffic Control é recurso do kernel Linux | `iproute2` nas imagens Linux e `NET_ADMIN` nos quatro serviços | Dockerfiles, `docker-compose.yml` |
| Conversão de caminhos no Git Bash | MSYS pode transformar caminhos internos `/app/...` | `MSYS_NO_PATHCONV=1` no executor | `run_experiments.sh` |
| DN do OpenSSL interpretado como caminho | Conversão MSYS do argumento `/CN=...` | usa `//CN=localhost` em MINGW/MSYS | `scripts/generate_certs.sh` |
| Certificado local não confiável por padrão | Certificado autoassinado | SANs para nomes/IPs, montagem do CRT e `CERT_REQUIRED` | `generate_certs.sh`, cliente, Compose |
| HTTP/3 não suportado pelo HTTPX | HTTPX cobre HTTP/1.1 e HTTP/2 | cliente aioquic dedicado e Caddy com UDP publicado | `http3_benchmark.py`, `Caddyfile` |
| Atraso aplicado apenas em egress não produz RTT completo | `netem` atua na saída | metade do atraso no cliente e metade nos servidores | `apply_lan.sh`, `apply_wan.sh` |
| Risco de perda composta próxima de 4% | aplicar 2% nos dois sentidos comporia probabilidades | perda somente na saída dos servidores | `apply_wan.sh` |
| Protocolo/TLS incorreto passar silenciosamente | bibliotecas e servidores podem negociar fallback | checagem de HTTP version, ALPN e TLS; validador HTTP/3 separado | cliente, `validate_experiment.py`, `validate_http3.py` |
| Respostas comprimidas ou de tamanho errado | distorceriam throughput | `Accept-Encoding: identity`, `gzip off` e bytes esperados | cliente, NGINX, validador |
| Falha durante uma bateria deixar rede alterada | interrupção ou exceção | `trap` chama reset e `docker compose down` | `run_experiments.sh` |
| Sobrescrita de resultado existente | perda de rastreabilidade | abertura JSON em modo exclusivo e nomes com timestamp/UUID | `benchmark.py` |
| Variabilidade e execução longa na WAN | perda de 2% torna transferências de 50 MiB lentas | timeouts reais de 600 s para A e preservação das amostras | `run_experiments.sh` |

Existe um log de uma tentativa smoke (`20261030T182856Z_smoke_failures.log`) contendo apenas “Falha ao gerar ou validar as cargas”. O registro não permite determinar a causa nem uma correção específica. Uma execução smoke posterior foi validada com 24 arquivos e o lote oficial concluiu 240/240 medições; não se atribui retroativamente uma causa sem evidência.

## 17. Limitações metodológicas

Limitações efetivamente identificadas:

- toda a topologia roda em uma única máquina com Docker Desktop e virtualização Linux;
- NGINX atende HTTP/1.1/HTTP/2 e Caddy atende HTTP/3, introduzindo diferenças de implementação;
- HTTP/1.1 é sem TLS, enquanto HTTP/2 e HTTP/3 incluem criptografia;
- a versão das imagens `nginx:alpine` e `python:3.12-alpine` não está presa por digest;
- somente dez repetições foram coletadas; p99 entre dez valores é sensível a extremos;
- a ordem é fixa: LAN antes de WAN e testes em sequência, sem randomização;
- o page cache do host/contêiner não é limpo entre execuções;
- HTTP/1.1 usa até seis conexões, enquanto HTTP/2/3 usam uma conexão com streams;
- perda `netem` é sintética, aplicada apenas no egress dos servidores e sem jitter/reordenação configurados;
- não foram coletados pacotes, retransmissões, cwnd, RTT por conexão, CPU ou consumo de memória;
- não houve teste formal de hipóteses entre protocolos; os IC95 são descritivos;
- algoritmos de congestionamento do kernel e do Caddy não foram registrados;
- BBR não foi configurado; não pode ser associado aos resultados;
- 52 observações-métrica foram marcadas por Tukey, sobretudo em séries variáveis, sem exclusão.

Limitações potenciais coerentes com o ambiente, mas não medidas diretamente, incluem interferência do escalonador, contenção de CPU, buffers, coleta de lixo, cópias no caminho de espaço de usuário do QUIC e variação temporal durante a coleta longa. Elas são hipóteses de influência, não causas comprovadas.

## 18. Como reproduzir o projeto

### 18.1 Pré-requisitos

- Windows com Docker Desktop em modo Linux;
- PowerShell e Git Bash, ou host Linux/macOS com shell POSIX;
- Python 3.12, `venv`, pip e OpenSSL;
- portas 8080, 8443 e 9443 TCP/UDP disponíveis.

### 18.2 Ambiente Python — PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

### 18.3 Certificado — Git Bash

```sh
sh scripts/generate_certs.sh
```

### 18.4 Construção e validação funcional

No PowerShell:

```powershell
docker compose config
docker compose up -d --build
docker compose ps
curl.exe --http1.1 http://localhost:8080/health.txt
.\.venv\Scripts\python.exe scripts\validate_http3.py
```

No Git Bash, os dois últimos comandos equivalentes são:

```sh
curl --http1.1 http://localhost:8080/health.txt
python scripts/validate_http3.py
```

Para validar a carga sem iniciar experimentos:

```powershell
.\.venv\Scripts\python.exe scripts\generate_workloads.py --output servers/content
```

### 18.5 Smoke e execução oficial — Git Bash

O executor gerencia `up`, rede, coleta, reset e `down` sozinho:

```sh
sh run_experiments.sh --smoke
sh run_experiments.sh
```

No PowerShell, chamando explicitamente o Git Bash:

```powershell
& 'C:\Program Files\Git\bin\bash.exe' './run_experiments.sh' '--smoke'
& 'C:\Program Files\Git\bin\bash.exe' './run_experiments.sh'
```

A segunda linha executa as 240 medições completas e pode durar horas. Não deve ser usada quando o objetivo for apenas reprocessar o lote já existente.

### 18.6 Processamento estatístico — PowerShell

```powershell
.\.venv\Scripts\python.exe scripts\analysis\process_results.py --batch-id 20261030T185905Z
```

JSONs ficam em `results/raw/`; CSVs, auditoria e gráficos ficam em `results/processed/`.

### 18.7 Encerramento manual

Se o ambiente tiver sido iniciado manualmente, no Git Bash:

```sh
sh scripts/network/reset_network.sh
docker compose down
```

## 19. Inventário dos entregáveis

| Componente | Localização | Situação |
|---|---|---|
| Compose e rede | `docker-compose.yml` | existente e validado |
| Servidores | `servers/http1/`, `servers/http2/`, `servers/http3/` | existentes e validados |
| Certificado local | `servers/certs/` | existente; chave privada não é entregável público |
| Cliente Python | `client/` | existente e validado nos três protocolos |
| Scripts de rede | `scripts/network/` | existentes e validados |
| Geração de cargas | `scripts/generate_workloads.py` | existente e validada |
| Cargas | `servers/content/workloads/` | existentes e validadas |
| Executor de comando único | `run_experiments.sh` | existente e usado na coleta |
| Validação | `scripts/validate_experiment.py`, `scripts/validate_http3.py` | existente |
| Dados brutos oficiais | `results/raw/20261030T185905Z_*.json` | 240 preservados |
| Manifesto de integridade | `results/raw/20261030T185905Z_official_manifest.txt` | existente, 240 hashes válidos |
| Processamento | `scripts/analysis/process_results.py` | existente e reproduzível |
| CSVs processados | `results/processed/*.csv` | existentes |
| Gráficos | `results/processed/figures/*.png` | seis PNGs a 300 DPI |
| README | `README.md` | existente |
| Ficha técnica | `docs/FICHA_TECNICA.md` | este documento |
| Relatório acadêmico PDF | `report/` | não produzido nesta etapa |
| Vídeo/roteiro | — | não produzido |
| ZIP de submissão | — | não produzido |

## 20. Síntese técnica final

O projeto implementa três servidores Web isolados, cliente Python assíncrono, TLS local, emulação bidirecional de atraso, perda WAN controlada, duas cargas determinísticas, matriz T01–T12, separação cold/warm, validação por arquivo, automação de limpeza e processamento estatístico reproduzível.

Foram validadas 240 medições oficiais, 6.180 requisições bem-sucedidas, zero falhas e 6.353.510.400 bytes. Os 240 hashes continuam correspondendo ao manifesto. As estatísticas incluem média, mediana, desvio amostral, p50, p99 e IC95; os seis gráficos contêm barras de erro.

Os resultados centrais são mistos: HTTP/3 apresentou o menor TTFB cold e o maior throughput da Carga A em WAN, mas teve throughput muito inferior em LAN e não liderou o RPS da Carga B em WAN. A degradação afetou fortemente todos os protocolos e elevou a variabilidade, sobretudo em T11 e T12. Portanto, os dados não sustentam superioridade universal.

As principais limitações são virtualização em uma única máquina, servidores diferentes, estratégias de concorrência distintas, dez repetições, ordem fixa e ausência de telemetria de transporte. CUBIC e BBR não foram confirmados nas execuções. O estado técnico atual está pronto para servir de base ao relatório posterior, sem que esta ficha antecipe um PDF, apresentação, vídeo ou pacote final.
