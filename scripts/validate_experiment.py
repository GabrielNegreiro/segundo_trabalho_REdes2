import argparse
import json
from pathlib import Path


NEGOTIATED = {
    "http1": "HTTP/1.1",
    "http2": "HTTP/2",
    "http3": "HTTP/3",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def main() -> int:
    parser = argparse.ArgumentParser(description="Valida um JSON experimental")
    parser.add_argument("--file", required=True)
    parser.add_argument("--test-id", required=True)
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--protocol", required=True, choices=tuple(NEGOTIATED))
    parser.add_argument("--scenario", required=True, choices=("LAN", "WAN"))
    parser.add_argument("--workload", required=True, choices=("A", "B"))
    parser.add_argument("--mode", required=True, choices=("cold", "warm"))
    parser.add_argument("--repetition", required=True, type=int)
    parser.add_argument("--requests", required=True, type=int)
    parser.add_argument("--expected-bytes", required=True, type=int)
    parser.add_argument("--http1-concurrency", type=int, default=1)
    args = parser.parse_args()

    path = Path(args.file)
    with path.open(encoding="utf-8") as source:
        payload = json.load(source)
    run = payload["run"]
    summary = run["summary"]
    records = payload["requests"]

    require(payload["schema_version"] == 2, "schema_version inesperada")
    require(run["test_id"] == args.test_id, "test_id incorreto")
    require(run["batch_id"] == args.batch_id, "batch_id incorreto")
    require(run["protocol"] == args.protocol, "protocolo incorreto")
    require(run["scenario"] == args.scenario, "cenario incorreto")
    require(run["workload"] == args.workload, "carga incorreta")
    require(run["connection_mode"] == args.mode, "modo incorreto")
    require(run["repetition"] == args.repetition, "repeticao incorreta")
    require(run["resource_count"] == args.requests, "resource_count incorreto")
    require(len(records) == args.requests, "quantidade de registros incorreta")
    require(summary["requests_scheduled"] == args.requests, "agenda incorreta")
    require(summary["successful_requests"] == args.requests, "ha falhas")
    require(summary["failed_requests"] == 0, "ha falhas")
    require(summary["bytes_valid"] is True, "total de bytes invalido")
    require(
        summary["total_bytes_received"] == args.requests * args.expected_bytes,
        "total de bytes inesperado",
    )
    require(summary["rps"] is not None and summary["rps"] > 0, "RPS invalido")
    require(
        summary["throughput_mbps"] is not None
        and summary["throughput_mbps"] > 0,
        "throughput invalido",
    )

    for record in records:
        require(record["success"] is True, "requisicao com falha")
        require(record["status_code"] == 200, "status diferente de 200")
        require(
            record["negotiated_protocol"] == NEGOTIATED[args.protocol],
            "protocolo negociado incorreto",
        )
        require(record["bytes_received"] == args.expected_bytes, "bytes incorretos")
        require(record["bytes_valid"] is True, "validacao de bytes ausente")
        require(record["ttfb_us"] is not None, "TTFB ausente")
        require(record["total_time_us"] is not None, "tempo total ausente")
        require(record["ttfb_us"] <= record["total_time_us"], "tempos incoerentes")
        if args.protocol in ("http2", "http3"):
            require(record["tls_version"] == "TLSv1.3", "TLS 1.3 nao confirmado")

    connections = summary["connections_created"]
    if args.mode == "cold":
        require(connections == args.requests, "cold reutilizou conexao")
    elif args.workload == "B" and args.protocol == "http1":
        require(2 <= connections <= args.http1_concurrency, "pool HTTP/1.1 invalido")
    else:
        require(connections == 1, "warm deveria usar uma conexao")

    print(
        f"valid={path.name} requests={len(records)} "
        f"bytes={summary['total_bytes_received']} connections={connections}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
