#!/usr/bin/env sh
set -u

# Impede que o Git Bash no Windows converta caminhos internos dos conteineres.
MSYS_NO_PATHCONV=1
export MSYS_NO_PATHCONV

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$script_dir"

repetitions=${REPETITIONS:-10}
run_kind=official
http1_connections=${HTTP1_CONNECTIONS:-6}
smoke=0

usage() {
  printf '%s\n' \
    'Uso: sh run_experiments.sh [--smoke] [--repetitions N]' \
    '  --smoke          executa 1 repeticao dos 12 testes com cargas reais' \
    '  --repetitions N  repeticoes por teste (padrao: 10)'
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --smoke)
      smoke=1
      repetitions=1
      run_kind=smoke
      shift
      ;;
    --repetitions)
      [ "$#" -ge 2 ] || { usage >&2; exit 2; }
      repetitions=$2
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      printf 'Argumento desconhecido: %s\n' "$1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

case "$repetitions" in
  ''|*[!0-9]*|0)
    printf 'Numero de repeticoes invalido: %s\n' "$repetitions" >&2
    exit 2
    ;;
esac

case "$http1_connections" in
  ''|*[!0-9]*|0)
    printf 'HTTP1_CONNECTIONS invalido: %s\n' "$http1_connections" >&2
    exit 2
    ;;
esac

if [ "$smoke" -eq 1 ] && [ "$repetitions" -ne 1 ]; then
  printf '%s\n' 'O modo --smoke exige exatamente uma repeticao.' >&2
  exit 2
fi

if ! command -v docker >/dev/null 2>&1; then
  printf '%s\n' 'Docker nao encontrado.' >&2
  exit 2
fi
if ! docker compose version >/dev/null 2>&1; then
  printf '%s\n' 'Docker Compose nao esta disponivel.' >&2
  exit 2
fi
if ! docker info >/dev/null 2>&1; then
  printf '%s\n' 'Docker Engine nao esta acessivel.' >&2
  exit 2
fi

mkdir -p results/raw
batch_id=$(date -u '+%Y%m%dT%H%M%SZ')
failure_log="results/raw/${batch_id}_${run_kind}_failures.log"
failures=0
executed=0
valid=0
containers_started=0

cleanup() {
  status=$?
  trap - EXIT INT TERM
  set +e
  if [ "$containers_started" -eq 1 ]; then
    sh scripts/network/reset_network.sh
    reset_status=$?
    if [ "$reset_status" -ne 0 ]; then
      printf '%s\n' 'Falha ao restaurar as regras de rede.' >> "$failure_log"
      status=1
    fi
    docker compose down
    down_status=$?
    if [ "$down_status" -ne 0 ]; then
      printf '%s\n' 'Falha ao encerrar os conteineres.' >> "$failure_log"
      status=1
    fi
  fi
  expected=$((12 * repetitions * 2))
  if [ "$failures" -ne 0 ] || [ "$executed" -ne "$expected" ] || [ "$valid" -ne "$executed" ]; then
    status=1
  fi
  if [ "$status" -eq 0 ]; then
    rm -f "$failure_log"
    printf 'Automacao concluida: 12 testes, %s repeticao(oes), %s medicoes validas.\n' \
      "$repetitions" "$valid"
  else
    printf 'Automacao encerrada com falha. Consulte %s\n' "$failure_log" >&2
  fi
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

record_failure() {
  failures=$((failures + 1))
  printf '%s test=%s repetition=%s mode=%s message=%s\n' \
    "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$1" "$2" "$3" "$4" >> "$failure_log"
}

printf 'Iniciando ambiente Docker (modo=%s, repeticoes=%s).\n' "$run_kind" "$repetitions"
containers_started=1
if ! docker compose up -d --build; then
  printf '%s\n' 'Falha ao iniciar os conteineres.' >> "$failure_log"
  exit 1
fi

if ! docker compose exec -T network-client \
  python /app/scripts/generate_workloads.py --output /app/content; then
  printf '%s\n' 'Falha ao gerar ou validar as cargas.' >> "$failure_log"
  exit 1
fi

for protocol in http1 http2 http3; do
  if ! docker compose exec -T network-client python -m client.benchmark \
    --protocol "$protocol" --mode cold --requests 1 --resource /health.txt \
    --output /tmp --timeout 30 >/dev/null; then
    printf 'Preflight falhou para %s.\n' "$protocol" >> "$failure_log"
    exit 1
  fi
done

run_measurement() {
  test_id=$1
  workload=$2
  protocol=$3
  scenario=$4
  repetition=$5
  mode=$6

  if [ "$workload" = "A" ]; then
    requests=1
    expected_bytes=52428800
    resource_args="--resource /workloads/large-50mib.bin"
    timeout=600
    concurrency=1
  else
    expected_bytes=10240
    timeout=120
    if [ "$mode" = "cold" ]; then
      requests=1
      resource_args="--resource /workloads/small/object-001.bin"
      concurrency=1
    else
      requests=100
      resource_args="--resources-manifest /app/content/workloads/small/manifest.txt"
      if [ "$protocol" = "http1" ]; then
        concurrency=$http1_connections
      else
        concurrency=1
      fi
    fi
  fi

  timestamp=$(date -u '+%Y%m%dT%H%M%S%NZ')
  filename="${batch_id}_${test_id}_r$(printf '%02d' "$repetition")_${mode}_${timestamp}.json"
  host_output="results/raw/$filename"
  container_output="/app/results/raw/$filename"
  executed=$((executed + 1))

  printf 'Executando %s repeticao=%s modo=%s protocolo=%s carga=%s cenario=%s\n' \
    "$test_id" "$repetition" "$mode" "$protocol" "$workload" "$scenario"

  # resource_args contem somente opcoes e caminhos constantes definidos acima.
  # shellcheck disable=SC2086
  if ! docker compose exec -T network-client python -m client.benchmark \
    --test-id "$test_id" --batch-id "$batch_id" \
    --repetition "$repetition" --run-kind "$run_kind" \
    --protocol "$protocol" --scenario "$scenario" --workload "$workload" \
    --mode "$mode" --requests "$requests" $resource_args \
    --expected-bytes "$expected_bytes" --http1-concurrency "$concurrency" \
    --timeout "$timeout" --output "$container_output"; then
    record_failure "$test_id" "$repetition" "$mode" "cliente retornou falha"
    return
  fi

  if [ ! -f "$host_output" ]; then
    record_failure "$test_id" "$repetition" "$mode" "JSON nao foi criado"
    return
  fi

  if docker compose exec -T network-client python /app/scripts/validate_experiment.py \
    --file "$container_output" --test-id "$test_id" --batch-id "$batch_id" \
    --protocol "$protocol" \
    --scenario "$scenario" --workload "$workload" --mode "$mode" \
    --repetition "$repetition" --requests "$requests" \
    --expected-bytes "$expected_bytes" --http1-concurrency "$concurrency"; then
    valid=$((valid + 1))
  else
    record_failure "$test_id" "$repetition" "$mode" "JSON experimental invalido"
  fi
}

run_test() {
  test_id=$1
  workload=$2
  protocol=$3
  scenario=$4
  repetition=$5
  run_measurement "$test_id" "$workload" "$protocol" "$scenario" "$repetition" cold
  run_measurement "$test_id" "$workload" "$protocol" "$scenario" "$repetition" warm
}

run_scenario() {
  scenario=$1
  if [ "$scenario" = "LAN" ]; then
    if ! sh scripts/network/apply_lan.sh; then
      printf '%s\n' 'Falha ao aplicar LAN.' >> "$failure_log"
      exit 1
    fi
  else
    if ! sh scripts/network/apply_wan.sh; then
      printf '%s\n' 'Falha ao aplicar WAN.' >> "$failure_log"
      exit 1
    fi
  fi

  repetition=1
  while [ "$repetition" -le "$repetitions" ]; do
    if [ "$scenario" = "LAN" ]; then
      run_test T01 A http1 LAN "$repetition"
      run_test T02 A http2 LAN "$repetition"
      run_test T03 A http3 LAN "$repetition"
      run_test T07 B http1 LAN "$repetition"
      run_test T08 B http2 LAN "$repetition"
      run_test T09 B http3 LAN "$repetition"
    else
      run_test T04 A http1 WAN "$repetition"
      run_test T05 A http2 WAN "$repetition"
      run_test T06 A http3 WAN "$repetition"
      run_test T10 B http1 WAN "$repetition"
      run_test T11 B http2 WAN "$repetition"
      run_test T12 B http3 WAN "$repetition"
    fi
    repetition=$((repetition + 1))
  done
}

run_scenario LAN
run_scenario WAN

if [ "$failures" -ne 0 ]; then
  exit 1
fi
