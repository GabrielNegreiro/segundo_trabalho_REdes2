#!/usr/bin/env sh
set -eu

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cert_dir="$project_root/servers/certs"

mkdir -p "$cert_dir"

# O prefixo duplo evita que o MSYS2 do Git Bash converta o DN em caminho.
case "$(uname -s)" in
  MINGW*|MSYS*) subject="//CN=localhost" ;;
  *) subject="/CN=localhost" ;;
esac

openssl req \
  -x509 \
  -newkey rsa:2048 \
  -sha256 \
  -nodes \
  -days 3650 \
  -keyout "$cert_dir/localhost.key" \
  -out "$cert_dir/localhost.crt" \
  -subj "$subject" \
  -addext "subjectAltName=DNS:localhost,DNS:server-http2,DNS:server-http3,IP:127.0.0.1,IP:172.20.0.20,IP:172.20.0.30" \
  -addext "keyUsage=critical,digitalSignature,keyEncipherment" \
  -addext "extendedKeyUsage=serverAuth"

chmod 600 "$cert_dir/localhost.key" 2>/dev/null || true
printf '%s\n' "Certificado criado em $cert_dir/localhost.crt"
