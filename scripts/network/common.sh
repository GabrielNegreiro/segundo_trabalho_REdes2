#!/usr/bin/env sh

interface=eth0
client_container=network_client
server_containers="server_http11 server_http2_tls server_http3_quic"
all_containers="$client_container $server_containers"

require_containers() {
  for container in $all_containers; do
    running=$(docker inspect --format '{{.State.Running}}' "$container" 2>/dev/null || true)
    if [ "$running" != "true" ]; then
      printf 'Erro: o contêiner %s não está ativo.\n' "$container" >&2
      exit 1
    fi

    if ! docker exec "$container" ip link show dev "$interface" >/dev/null 2>&1; then
      printf 'Erro: a interface %s não existe em %s.\n' "$interface" "$container" >&2
      exit 1
    fi
  done
}

replace_netem() {
  container=$1
  shift
  docker exec "$container" tc qdisc replace dev "$interface" root netem "$@"
}

show_rules() {
  for container in $all_containers; do
    printf '%s: ' "$container"
    docker exec "$container" tc qdisc show dev "$interface"
  done
}

require_netem() {
  for container in $all_containers; do
    if ! docker exec "$container" tc qdisc show dev "$interface" | grep -q netem; then
      printf 'Erro: netem não foi confirmado em %s.\n' "$container" >&2
      exit 1
    fi
  done
}
