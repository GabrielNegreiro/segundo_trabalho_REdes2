#!/usr/bin/env sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$script_dir/common.sh"

require_containers

# Metade do RTT em cada sentido: cliente -> servidor e servidor -> cliente.
replace_netem "$client_container" delay 0.5ms
for container in $server_containers; do
  replace_netem "$container" delay 0.5ms
done

require_netem

if show_rules | grep -q 'loss'; then
  printf 'Erro: uma regra de perda permaneceu ativa no cenário LAN.\n' >&2
  exit 1
fi

printf '%s\n' 'Cenário LAN aplicado: 0,5 ms por sentido, sem perda sintética.'
show_rules
