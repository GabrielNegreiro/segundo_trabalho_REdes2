import argparse
import asyncio
import json
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from .http3_benchmark import run_http3_benchmark
from .httpx_benchmark import run_httpx_benchmark
from .metrics import summarize


DEFAULT_URLS = {
    "http1": "http://server-http1",
    "http2": "https://server-http2",
    "http3": "https://server-http3",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Cliente de benchmark HTTP/1.1, HTTP/2 e HTTP/3"
    )
    parser.add_argument(
        "--protocol", required=True, choices=("http1", "http2", "http3")
    )
    parser.add_argument("--mode", required=True, choices=("cold", "warm"))
    parser.add_argument("--requests", type=int, default=1)
    parser.add_argument(
        "--resource",
        action="append",
        help="recurso; pode ser repetido (padrao: /health.txt)",
    )
    parser.add_argument(
        "--resources-manifest",
        help="arquivo com um recurso iniciado por / em cada linha",
    )
    parser.add_argument("--expected-bytes", type=int)
    parser.add_argument("--http1-concurrency", type=int, default=1)
    parser.add_argument("--test-id")
    parser.add_argument("--batch-id")
    parser.add_argument("--scenario", choices=("LAN", "WAN"))
    parser.add_argument("--workload", choices=("A", "B"))
    parser.add_argument("--repetition", type=int)
    parser.add_argument(
        "--run-kind", choices=("manual", "smoke", "official"), default="manual"
    )
    parser.add_argument(
        "--base-url", help="sobrescreve o endereco padrao do protocolo"
    )
    parser.add_argument("--output", default="/app/results/raw")
    parser.add_argument("--ca-cert", default="/app/certs/localhost.crt")
    parser.add_argument("--timeout", type=float, default=15.0)
    args = parser.parse_args()

    if args.requests < 1:
        parser.error("--requests deve ser maior que zero")
    if args.timeout <= 0:
        parser.error("--timeout deve ser maior que zero")
    if args.expected_bytes is not None and args.expected_bytes < 0:
        parser.error("--expected-bytes nao pode ser negativo")
    if not 1 <= args.http1_concurrency <= 64:
        parser.error("--http1-concurrency deve estar entre 1 e 64")
    if args.repetition is not None and args.repetition < 1:
        parser.error("--repetition deve ser maior que zero")
    if args.test_id is not None and not re.fullmatch(
        r"T(?:0[1-9]|1[0-2])", args.test_id
    ):
        parser.error("--test-id deve estar entre T01 e T12")

    args.base_url = args.base_url or DEFAULT_URLS[args.protocol]
    scheme = urlsplit(args.base_url).scheme
    expected_scheme = "http" if args.protocol == "http1" else "https"
    if scheme != expected_scheme:
        parser.error(f"{args.protocol} exige URL com esquema {expected_scheme}")

    resources = list(args.resource or [])
    if args.resources_manifest:
        manifest = Path(args.resources_manifest)
        try:
            lines = manifest.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            parser.error(f"nao foi possivel ler o manifesto: {exc}")
        resources.extend(
            line.strip()
            for line in lines
            if line.strip() and not line.lstrip().startswith("#")
        )
    if not resources:
        resources = ["/health.txt"] * args.requests
    elif args.resources_manifest is None and len(resources) == 1:
        resources *= args.requests
    elif args.requests != 1 and args.requests != len(resources):
        parser.error(
            "--requests deve ser 1 ou igual a quantidade de recursos informados"
        )
    if any(not resource.startswith("/") for resource in resources):
        parser.error("todo recurso deve comecar com /")
    args.resources = resources
    return args


def output_path(args: argparse.Namespace, run_id: str) -> Path:
    requested = Path(args.output)
    if requested.suffix.lower() == ".json":
        requested.parent.mkdir(parents=True, exist_ok=True)
        if requested.exists():
            raise FileExistsError(f"o arquivo ja existe: {requested}")
        return requested

    requested.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    prefix = args.test_id.lower() if args.test_id else "validation"
    repetition = f"_r{args.repetition:02d}" if args.repetition else ""
    return requested / (
        f"{prefix}{repetition}_{args.protocol}_{args.mode}_{timestamp}_{run_id[:8]}.json"
    )


def validate_byte_counts(records, expected_bytes: int | None) -> None:
    for record in records:
        record.expected_bytes = expected_bytes
        if expected_bytes is None:
            record.bytes_valid = None
            continue
        record.bytes_valid = record.bytes_received == expected_bytes
        if record.bytes_valid:
            continue
        message = (
            f"tamanho recebido {record.bytes_received}, esperado {expected_bytes} bytes"
        )
        record.success = False
        record.error = f"{record.error}; {message}" if record.error else message


def concurrency_strategy(args: argparse.Namespace) -> str:
    if args.mode == "cold":
        return "uma nova conexao por requisicao; execucao sequencial"
    if args.protocol == "http1":
        return (
            f"HTTP/1.1 concorrente com pool de ate {args.http1_concurrency} "
            "conexoes TCP persistentes"
            if args.http1_concurrency > 1
            else "uma conexao HTTP/1.1 persistente; requisicoes sequenciais"
        )
    if args.protocol == "http2":
        return "uma conexao TCP/TLS 1.3 persistente; streams HTTP/2 concorrentes"
    return "uma conexao QUIC/TLS 1.3 persistente; streams HTTP/3 concorrentes"


async def execute(args: argparse.Namespace, run_id: str):
    common = {
        "run_id": run_id,
        "mode": args.mode,
        "resources": args.resources,
        "base_url": args.base_url,
        "resource": args.resources[0],
        "ca_cert": args.ca_cert,
        "timeout_seconds": args.timeout,
    }
    if args.protocol == "http3":
        return await run_http3_benchmark(**common)
    return await run_httpx_benchmark(
        protocol=args.protocol,
        http1_concurrency=args.http1_concurrency,
        **common,
    )


def main() -> int:
    args = parse_args()
    run_id = str(uuid.uuid4())
    run_started = datetime.now(timezone.utc).isoformat(timespec="microseconds")

    try:
        records, window_seconds, connections_created = asyncio.run(
            execute(args, run_id)
        )
        validate_byte_counts(records, args.expected_bytes)
        run_finished = datetime.now(timezone.utc).isoformat(timespec="microseconds")
        expected_total_bytes = (
            args.expected_bytes * len(args.resources)
            if args.expected_bytes is not None
            else None
        )
        summary = summarize(
            records,
            window_seconds,
            connections_created,
            expected_total_bytes,
        )
        destination = output_path(args, run_id)
        payload = {
            "schema_version": 2,
            "run": {
                "run_id": run_id,
                "batch_id": args.batch_id,
                "test_id": args.test_id,
                "repetition": args.repetition,
                "run_kind": args.run_kind,
                "started_at_utc": run_started,
                "finished_at_utc": run_finished,
                "protocol": args.protocol,
                "negotiated_protocol_required": {
                    "http1": "HTTP/1.1",
                    "http2": "HTTP/2",
                    "http3": "HTTP/3",
                }[args.protocol],
                "scenario": args.scenario,
                "workload": args.workload,
                "connection_mode": args.mode,
                "base_url": args.base_url,
                "resource_count": len(args.resources),
                "resource_manifest": args.resources_manifest,
                "first_resource": args.resources[0],
                "expected_bytes_per_request": args.expected_bytes,
                "expected_total_bytes": expected_total_bytes,
                "http1_concurrency_limit": args.http1_concurrency,
                "concurrency_strategy": concurrency_strategy(args),
                "cache_policy": (
                    "no local cache; Accept-Encoding: identity; "
                    "Cache-Control: no-cache, no-store"
                ),
                "summary": summary,
            },
            "requests": [record.to_dict() for record in records],
        }
        with destination.open("x", encoding="utf-8") as output_file:
            json.dump(payload, output_file, ensure_ascii=False, indent=2)
            output_file.write("\n")
    except Exception as exc:
        print(f"Erro fatal: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    print(f"run_id={run_id}")
    print(
        f"test_id={args.test_id} repetition={args.repetition} "
        f"protocol={args.protocol} mode={args.mode}"
    )
    print(
        "success="
        f"{summary['successful_requests']} failed={summary['failed_requests']} "
        f"bytes={summary['total_bytes_received']} rps={summary['rps']}"
    )
    print(
        f"throughput_mbps={summary['throughput_mbps']} "
        f"connections={summary['connections_created']}"
    )
    print(f"output={destination}")
    return 0 if summary["failed_requests"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
