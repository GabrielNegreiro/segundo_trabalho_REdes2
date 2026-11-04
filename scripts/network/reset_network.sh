#!/usr/bin/env sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$script_dir/common.sh"

require_containers

for container in $all_containers; do
  docker exec "$container" tc qdisc del dev "$interface" root >/dev/null 2>&1 || true
done

for container in $all_containers; do
  if docker exec "$container" tc qdisc show dev "$interface" | grep -q netem; then
    printf 'Erro: netem ainda está ativo em %s.\n' "$container" >&2
    exit 1
  fi
done

printf '%s\n' 'Regras netem removidas; interfaces restauradas.'
show_rules
