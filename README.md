# Estudo experimental de protocolos Web

Projeto acadêmico da disciplina de Redes de Computadores II da UFPI para comparar o desempenho de HTTP/1.1, HTTPS com HTTP/2 e TLS 1.3, e HTTP/3 sobre QUIC em condições de rede controladas.

## Objetivo experimental

O projeto deverá medir o efeito de latência, perda de pacotes, handshakes e bloqueio *head-of-line* em duas cargas: um objeto de 50 MB e 100 objetos concorrentes de 10 KB. A matriz final terá três protocolos em dois cenários de rede, totalizando 12 testes.

Nesta versão foram concluídas as Etapas 1 a 7: preparação, infraestrutura Docker, emulação LAN/WAN, cliente de benchmark, cargas, automação, execução oficial da matriz T01–T12 e processamento estatístico com tabelas e gráficos. O relatório conclusivo ainda não foi produzido.

## Tecnologias previstas

- Docker Desktop e Docker Compose para os três servidores e a rede isolada;
- Nginx para HTTP/1.1 e HTTPS/HTTP/2;
- Caddy para HTTP/3/QUIC;
- Linux `tc netem` para atraso e perda controlados;
- Python assíncrono com `httpx[http2]`, `aioquic` e `asyncio`;
- Matplotlib para as visualizações estatísticas.

## Estrutura

```text
.
├── client/
│   ├── benchmark.py        # interface de linha de comando e exportação
│   ├── httpx_benchmark.py  # HTTP/1.1 e HTTP/2
│   ├── http3_benchmark.py  # HTTP/3 sobre QUIC
│   ├── metrics.py          # RPS, p50 e p99
│   ├── models.py           # registros individuais
│   ├── requirements.txt    # dependências do contêiner cliente
│   └── network/            # imagem do network_client
├── docs/                   # documentação e notas da especificação
├── report/                 # fontes do futuro relatório técnico
├── results/
│   ├── raw/                # resultados JSON/CSV brutos
│   └── processed/          # tabelas, auditoria e figuras da Etapa 7
├── scripts/
│   ├── analysis/           # processamento estatístico e gráficos
│   ├── network/            # scripts LAN, WAN, reset e auxiliar comum
│   ├── generate_workloads.py # geração determinística das Cargas A e B
│   ├── generate_certs.sh   # geração do certificado autoassinado
│   ├── validate_experiment.py # validação dos JSONs experimentais
│   └── validate_http3.py   # validação funcional, sem benchmark
├── servers/
│   ├── certs/              # certificados locais (não versionados)
│   ├── content/            # health.txt e cargas compartilhadas
│   ├── http1/              # Dockerfile e configuração NGINX HTTP/1.1
│   ├── http2/              # Dockerfile e configuração NGINX HTTP/2
│   └── http3/              # Dockerfile e Caddyfile HTTP/3
├── .gitignore
├── docker-compose.yml
├── README.md
├── run_experiments.sh      # executor da matriz T01–T12
└── requirements.txt
```

O executor de comando único é `run_experiments.sh`, na raiz do projeto.

## Requisitos básicos

- Docker com suporte a contêineres Linux e Docker Compose;
- Python 3.11 ou posterior (o ambiente preparado usa Python 3.12);
- `venv` e `pip`;
- shell compatível com os futuros scripts `.sh`;
- permissão Docker `NET_ADMIN` nos serviços que executarão `tc netem`.

## Ambiente verificado na Etapa 1

Verificação realizada em 30/10/2026:

- Windows x64, versão exibida 25H2, build 26200.9711;
- PowerShell 5.1.26100.9711;
- Docker Desktop 4.74.0, Engine/CLI 29.4.3, contêineres Linux;
- Docker Compose 5.1.3;
- Python 3.12.10, `pip` 25.0.1 e OpenSSL 3.0.16;
- Git 2.51.0 e Git Bash 5.2.37;
- ambiente virtual `.venv` criado e dependências instaladas sem conflitos.

O `tc` não existe no host Windows, o que é esperado. As imagens Linux incluem `iproute2`, e os quatro serviços recebem `NET_ADMIN`. As regras são aplicadas somente às interfaces `eth0` dos contêineres deste projeto.

## Preparação inicial

No PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
docker version
docker compose version
```

Em Linux/macOS, a ativação equivalente é:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
```

As versões diretas estão fixadas em `requirements.txt` para tornar a preparação repetível. Não inclua dados experimentais ou chaves privadas no repositório.

## Infraestrutura Docker

| Serviço | Servidor | Protocolo | Porta do host | IP Docker |
|---|---|---|---:|---|
| `server-http1` | NGINX 1.31.8 | HTTP/1.1 sobre TCP | 8080 | 172.20.0.10 |
| `server-http2` | NGINX 1.31.8 | HTTP/2 sobre TCP e TLS 1.3 | 8443 | 172.20.0.20 |
| `server-http3` | Caddy 2.7.6 | HTTP/3 sobre QUIC/UDP e TLS 1.3 | 9443 TCP/UDP | 172.20.0.30 |

Os serviços compartilham a rede bridge `net_bench` (`172.20.0.0/16`) e servem o mesmo recurso `/health.txt`.

O serviço `network-client` usa Python 3.12 no IP `172.20.0.40`. Ele executa o benchmark dentro da rede emulada, mantém `NET_ADMIN` para a Etapa 3 e grava os JSONs no diretório `results/raw/` do host.

### Certificado local

Execute em Linux, macOS ou Git Bash:

```sh
sh scripts/generate_certs.sh
```

O comando cria `servers/certs/localhost.crt` e `localhost.key`, incluindo SANs para `localhost`, nomes dos serviços e IPs Docker. A chave privada é ignorada pelo Git.

### Iniciar e encerrar

```sh
docker compose config
docker compose up -d --build
docker compose ps
docker compose down
```

### Validação funcional

```sh
curl --http1.1 http://localhost:8080/health.txt
python scripts/validate_http3.py
```

O HTTP/2 pode ser confirmado com `httpx.Client(http2=True, verify=False)` e o TLS/ALPN com:

```sh
openssl s_client -connect localhost:8443 -servername localhost -alpn h2 -tls1_3
```

Em 30/10/2026 foram comprovados: HTTP/1.1 `200`, HTTP/2 `200` com ALPN `h2` e TLS 1.3, e HTTP/3 `200` com ALPN `h3` sobre QUIC/UDP. O ciclo `down` seguido de `up -d` também foi validado.

## Emulação de rede

O `netem` atua somente no tráfego de saída. Por isso, o atraso é dividido entre o cliente e cada servidor:

- LAN: `0,5 ms` na saída do cliente e `0,5 ms` na saída dos servidores, sem perda;
- WAN: `25 ms` na saída do cliente e `25 ms` na saída dos servidores;
- a perda WAN de `2%` é aplicada somente na saída dos servidores, evitando combinar duas taxas de perda no mesmo RTT.

No Git Bash:

```sh
sh scripts/network/apply_lan.sh
sh scripts/network/apply_wan.sh
sh scripts/network/reset_network.sh
```

No PowerShell, execute os mesmos scripts por meio do Git Bash:

```powershell
& 'C:\Program Files\Git\bin\bash.exe' './scripts/network/apply_lan.sh'
& 'C:\Program Files\Git\bin\bash.exe' './scripts/network/apply_wan.sh'
& 'C:\Program Files\Git\bin\bash.exe' './scripts/network/reset_network.sh'
```

Para consultar as regras:

```powershell
docker exec network_client tc qdisc show dev eth0
docker exec server_http11 tc qdisc show dev eth0
docker exec server_http2_tls tc qdisc show dev eth0
docker exec server_http3_quic tc qdisc show dev eth0
```

Resultados de validação da Etapa 3:

| Estado | RTT médio observado | Perda observada |
|---|---:|---:|
| Original | 0,102–0,119 ms | 0% |
| LAN | 1,248–1,319 ms | 0% |
| WAN | 50,442–50,562 ms | 1,4–2,2% em 500 amostras por servidor |
| Após reset | 0,077–0,117 ms | 0% |

Após a validação, `reset_network.sh` foi executado e o estado atual é `qdisc noqueue`, sem emulação ativa.

## Cliente de benchmark

O cliente usa HTTPX para HTTP/1.1 e HTTP/2, aioquic para HTTP/3 e `asyncio` para as operações assíncronas. O certificado autoassinado é montado como autoridade local e validado pelo cliente; a verificação TLS não é desativada.

Exemplos de execução no contêiner:

```sh
docker compose exec -T network-client python -m client.benchmark --protocol http1 --mode cold --requests 3 --resource /health.txt
docker compose exec -T network-client python -m client.benchmark --protocol http2 --mode warm --requests 5 --resource /health.txt
docker compose exec -T network-client python -m client.benchmark --protocol http3 --mode warm --requests 5 --resource /health.txt
```

Parâmetros principais:

- `--protocol`: `http1`, `http2` ou `http3`;
- `--mode`: `cold` ou `warm`;
- `--requests`: quantidade de requisições medidas;
- `--resource`: caminho iniciado por `/`;
- `--base-url`: sobrescreve o servidor interno padrão;
- `--output`: diretório ou nome de um novo arquivo JSON;
- `--timeout`: timeout por requisição em segundos.

No modo `cold`, cada requisição cria e encerra seu próprio cliente e sua própria conexão, sem compartilhar sessão TLS ou QUIC. No modo `warm`, uma requisição não contabilizada aquece a conexão; HTTP/2 e HTTP/3 enviam as requisições medidas concorrentemente em múltiplos streams da mesma conexão. HTTP/1.1 reutiliza uma única conexão, mas executa as requisições em série porque não oferece essa multiplexação.

Não existe cache local no HTTPX ou no cliente aioquic. Cada requisição também envia `Cache-Control: no-cache, no-store`, `Pragma: no-cache` e um parâmetro de consulta exclusivo.

### Métricas e resultados

- TTFB: início da operação até o primeiro byte não vazio do corpo; no cold inclui os handshakes;
- tempo de cabeçalhos: início até o recebimento dos cabeçalhos, registrado separadamente;
- tempo total: início até o último byte do corpo;
- RPS: sucessos divididos pela duração monotônica da janela completa;
- p50 e p99: interpolação linear sobre os tempos individuais das requisições bem-sucedidas;
- timestamps: UTC ISO 8601 com indicação `+00:00`;
- precisão: `time.perf_counter_ns()`, exportada em microssegundos.

Por padrão, cada execução cria sem sobrescrever:

```text
results/raw/validation_<timestamp>_<protocolo>_<modo>_<run-id>.json
```

O JSON contém metadados da execução, estatísticas agregadas e registros individuais, incluindo protocolo negociado, TLS, status, bytes, TTFB, tempo total e erro. Requisições com falha são exportadas, mas não contam no RPS nem nos percentis de sucesso.

## Cargas e automação experimental

As cargas são geradas deterministicamente e compartilhadas pelos três servidores:

- Carga A: `servers/content/workloads/large-50mib.bin`, exatamente 50 MiB, ou 52.428.800 bytes;
- Carga B: 100 arquivos distintos em `servers/content/workloads/small/`, cada um com exatamente 10 KiB, ou 10.240 bytes;
- o manifesto `servers/content/workloads/small/manifest.txt` enumera os 100 recursos da Carga B.

Para gerar ou reparar os arquivos no host:

```sh
python scripts/generate_workloads.py --output servers/content
```

O mesmo gerador é chamado automaticamente dentro do `network-client`. O cliente envia `Accept-Encoding: identity`, os servidores NGINX mantêm `gzip off` e cada resposta é rejeitada se a quantidade recebida não corresponder ao tamanho esperado. A leitura é feita em fluxo; o arquivo de 50 MiB não é acumulado na memória do cliente.

Na Carga B warm, HTTP/1.1 usa um pool controlado de até seis conexões TCP persistentes. HTTP/2 usa streams concorrentes sobre uma conexão TCP/TLS 1.3 e HTTP/3 usa streams concorrentes sobre uma conexão QUIC/TLS 1.3. A medição cold é separada: usa uma nova conexão, sem reutilização de sessão. Para a Carga B, o cold mede um objeto de 10 KiB e o warm executa a bateria completa de 100 objetos; para a Carga A, ambos transferem o objeto real de 50 MiB.

### Executor de comando único

Validação reduzida, com uma repetição real de T01 a T12:

```sh
sh run_experiments.sh --smoke
```

Execução normal preparada para dez repetições por teste:

```sh
sh run_experiments.sh
```

Uma quantidade diferente pode ser configurada sem alterar o script:

```sh
sh run_experiments.sh --repetitions 3
# ou: REPETITIONS=3 sh run_experiments.sh
```

O padrão de dez repetições é uma decisão metodológica do projeto, pois o PDF exige múltiplas amostras, mas não fixa a quantidade. A execução normal representa 12 × 10 combinações experimentais; cada repetição salva cold e warm em arquivos separados para impedir a mistura das estatísticas.

O executor verifica Docker/Compose, sobe os serviços, gera e valida as cargas, testa os três servidores, aplica LAN, executa os seis testes LAN, aplica WAN e executa os seis testes WAN. Um `trap` sempre chama `reset_network.sh` e `docker compose down`, inclusive após erro. Resultados já gravados não são removidos.

Os resultados são criados em `results/raw/` no formato:

```text
<lote>_T01_r01_cold_<timestamp>.json
<lote>_T01_r01_warm_<timestamp>.json
```

Cada JSON identifica teste, repetição, protocolo, cenário, carga, modo, estratégia de concorrência, bytes, throughput em Mbps e MiB/s, RPS, TTFB, tempo total, p50, p99 e registros individuais. `scripts/validate_experiment.py` verifica metadados, protocolo negociado, TLS, conexões, tamanhos e métricas antes de aceitar a medição.

O modo smoke da Etapa 5 foi validado com as cargas integrais: 12 testes e 24 arquivos cold/warm válidos. Ao final, as quatro interfaces apresentaram `qdisc noqueue` e os contêineres foram removidos.

## Processamento estatístico da Etapa 7

O processamento é restrito ao lote oficial `20261030T185905Z`; resultados de smoke não entram nas tabelas. Para reproduzi-lo no Windows com o ambiente virtual do projeto:

```powershell
.\.venv\Scripts\python.exe scripts\analysis\process_results.py --batch-id 20261030T185905Z
```

Em outro ambiente com as dependências instaladas, o comando equivalente é:

```sh
python scripts/analysis/process_results.py --batch-id 20261030T185905Z
```

Antes de calcular qualquer estatística, o script confere o manifesto e os hashes SHA-256 dos 240 JSONs, a matriz T01–T12, as dez repetições, a separação cold/warm, os protocolos negociados, TLS, tamanhos, contagens e métricas derivadas. Cada combinação possui `n=10` repetições independentes. São calculados média aritmética, mediana, desvio-padrão amostral (`n-1`), p50, p99 e intervalo de confiança de 95% da média pelo t de Student (`gl=9`, `t=2,262157`).

Para valores de repetição `x_i`, são usadas `média = Σx_i/n`, `s = √[Σ(x_i-média)²/(n-1)]` e `IC95 = média ± t × s/√n`. Os percentis usam interpolação linear. TTFB e latência individual são exportados em milissegundos; duração completa, em segundos; RPS, em requisições por segundo; bytes, como contagem inteira; e throughput, em Mbps decimais, por `(bytes × 8)/(duração × 1.000.000)`. O percentual de sucesso é `sucessos/(sucessos+falhas) × 100`.

Na Carga B, os 100 objetos de uma bateria não são tratados como 100 repetições independentes. Primeiro é produzido um valor por bateria/repetição; só então os dez valores independentes são agregados. Em particular, `request_latency_percentiles.csv` contém a variabilidade entre repetições dos p50/p99 calculados internamente em cada bateria, enquanto RPS e duração usam a bateria completa como unidade experimental.

Os arquivos principais em `results/processed/` são:

- `ttfb_statistics.csv`: TTFB por carga, protocolo, cenário e modo;
- `total_time_statistics.csv`: tempo médio individual e duração completa da transferência/bateria;
- `rps_statistics.csv`: RPS warm da Carga B;
- `throughput_statistics.csv`: throughput da Carga A;
- `request_latency_percentiles.csv`: p50/p99 internos da Carga B warm, agregados entre repetições;
- `execution_quality.csv`: sucesso, falhas, bytes e consistência das execuções;
- `repetition_metrics.csv`: valores por repetição usados nas agregações;
- `outlier_observations.csv`: marcações pela regra de Tukey (`1,5 × IQR`), preservadas sem exclusão;
- `analysis_summary.json` e `figures_manifest.csv`: auditoria do lote, método e inventário das figuras.

As seis figuras PNG estão em `results/processed/figures/`, a 300 DPI:

- `01_ttfb_cold.png`: TTFB cold, com cargas A/B e LAN/WAN separados;
- `02_total_time_load_a_warm.png`: duração warm da transferência de 50 MiB;
- `03_throughput_load_a_warm.png`: throughput warm da Carga A;
- `04_rps_load_b_warm.png`: RPS da bateria warm de 100 objetos;
- `05_latency_p50_p99_load_b_warm.png`: p50/p99 internos e sua variabilidade entre repetições;
- `06_network_degradation_load_b_warm.png`: impacto LAN/WAN sobre a duração equivalente da Carga B warm.

Todas usam barras de erro correspondentes ao IC95 calculado sobre as dez repetições independentes. Os dados brutos em `results/raw/` são somente leitura para esta etapa.

