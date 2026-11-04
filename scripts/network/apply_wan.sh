#!/usr/bin/env sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$script_dir/common.sh"

require_containers

# Atraso em ambos os sentidos; perda apenas na saída dos servidores.
replace_netem "$client_container" delay 25ms
for container in $server_containers; do
  replace_netem "$container" delay 25ms loss 2%
done

require_netem

client_rule=$(docker exec "$client_container" tc qdisc show dev "$interface")
if printf '%s\n' "$client_rule" | grep -q 'loss'; then
  printf 'Erro: perda não deveria estar configurada na saída do cliente.\n' >&2
  exit 1
fi

for container in $server_containers; do
  if ! docker exec "$container" tc qdisc show dev "$interface" | grep -q 'loss 2%'; then
    printf 'Erro: a perda de 2%% não foi confirmada em %s.\n' "$container" >&2
    exit 1
  fi
done

printf '%s\n' 'Cenário WAN aplicado: 25 ms por sentido e 2% de perda na saída dos servidores.'
show_rules
