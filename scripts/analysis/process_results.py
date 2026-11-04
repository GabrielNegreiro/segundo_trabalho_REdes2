import argparse
import csv
import hashlib
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import fmean, median, stdev

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BATCH = "20261030T185905Z"
T_CRITICAL_975_DF9 = 2.2621571627409915

MATRIX = {
    "T01": ("A", "http1", "LAN"),
    "T02": ("A", "http2", "LAN"),
    "T03": ("A", "http3", "LAN"),
    "T04": ("A", "http1", "WAN"),
    "T05": ("A", "http2", "WAN"),
    "T06": ("A", "http3", "WAN"),
    "T07": ("B", "http1", "LAN"),
    "T08": ("B", "http2", "LAN"),
    "T09": ("B", "http3", "LAN"),
    "T10": ("B", "http1", "WAN"),
    "T11": ("B", "http2", "WAN"),
    "T12": ("B", "http3", "WAN"),
}
PROTOCOL_LABELS = {
    "http1": "HTTP/1.1",
    "http2": "HTTP/2",
    "http3": "HTTP/3",
}
NEGOTIATED = {
    "http1": "HTTP/1.1",
    "http2": "HTTP/2",
    "http3": "HTTP/3",
}
PROTOCOL_COLORS = {
    "http1": "#4C78A8",
    "http2": "#F58518",
    "http3": "#54A24B",
}
PROTOCOLS = ("http1", "http2", "http3")
SCENARIOS = ("LAN", "WAN")
MODES = ("cold", "warm")


@dataclass
class Sample:
    source_file: str
    batch_id: str
    test_id: str
    repetition: int
    workload: str
    protocol: str
    scenario: str
    mode: str
    request_count: int
    successful_requests: int
    failed_requests: int
    bytes_received: int
    connections_created: int
    request_ttfb_mean_ms: float
    request_total_mean_ms: float
    request_latency_p50_ms: float
    request_latency_p99_ms: float
    batch_duration_s: float
    rps: float
    throughput_mbps: float


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def finite(value, label: str) -> float:
    number = float(value)
    require(math.isfinite(number), f"{label} nao e finito")
    return number


def percentile(values: list[float], probability: float) -> float:
    require(bool(values), "percentil exige pelo menos um valor")
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def describe(values: list[float]) -> dict[str, float | int]:
    require(len(values) == 10, f"esperadas 10 repeticoes, recebidas {len(values)}")
    for value in values:
        finite(value, "amostra")
    mean_value = fmean(values)
    std_value = stdev(values)
    half_width = T_CRITICAL_975_DF9 * std_value / math.sqrt(len(values))
    return {
        "n": len(values),
        "mean": mean_value,
        "median": median(values),
        "sample_std": std_value,
        "p50": percentile(values, 0.50),
        "p99": percentile(values, 0.99),
        "ci95_lower": mean_value - half_width,
        "ci95_upper": mean_value + half_width,
        "ci95_half_width": half_width,
    }


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def manifest_hashes(raw_dir: Path, batch_id: str) -> dict[str, str]:
    path = raw_dir / f"{batch_id}_official_manifest.txt"
    require(path.is_file(), f"manifesto oficial ausente: {path}")
    entries: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        parts = line.split()
        if len(parts) == 5 and len(parts[0]) == 64 and parts[0].isalnum():
            entries[parts[4]] = parts[0].lower()
    require(len(entries) == 240, f"manifesto possui {len(entries)} entradas")
    return entries


def validate_and_convert(path: Path, payload: dict, batch_id: str) -> Sample:
    require(payload.get("schema_version") == 2, "schema_version inesperada")
    run = payload["run"]
    summary = run["summary"]
    requests = payload["requests"]
    test_id = run["test_id"]
    require(test_id in MATRIX, f"test_id inesperado: {test_id}")
    workload, protocol, scenario = MATRIX[test_id]
    mode = run["connection_mode"]
    repetition = int(run["repetition"])

    require(run["batch_id"] == batch_id, "batch_id incorreto")
    require(run["run_kind"] == "official", "run_kind nao oficial")
    require(
        (run["workload"], run["protocol"], run["scenario"])
        == (workload, protocol, scenario),
        "combinacao da matriz incorreta",
    )
    require(mode in MODES, f"modo inesperado: {mode}")
    require(1 <= repetition <= 10, f"repeticao inesperada: {repetition}")

    expected_count = 100 if workload == "B" and mode == "warm" else 1
    expected_bytes_each = 52_428_800 if workload == "A" else 10_240
    expected_total = expected_count * expected_bytes_each
    require(len(requests) == expected_count, "quantidade de requisicoes incorreta")
    require(run["resource_count"] == expected_count, "resource_count incorreto")
    require(summary["requests_scheduled"] == expected_count, "agenda incorreta")
    require(summary["successful_requests"] == expected_count, "ha requisicoes falhas")
    require(summary["failed_requests"] == 0, "ha requisicoes falhas")
    require(summary["total_bytes_received"] == expected_total, "bytes totais incorretos")
    require(summary["bytes_valid"] is True, "bytes_valid nao confirmado")

    ttfb_us: list[float] = []
    total_us: list[float] = []
    resources: set[str] = set()
    for request in requests:
        require(request["success"] is True and request["error"] is None, "requisicao falha")
        require(request["status_code"] == 200, "status HTTP incorreto")
        require(request["negotiated_protocol"] == NEGOTIATED[protocol], "protocolo incorreto")
        if protocol in ("http2", "http3"):
            require(request["tls_version"] == "TLSv1.3", "TLS 1.3 nao confirmado")
        require(request["bytes_received"] == expected_bytes_each, "bytes individuais incorretos")
        require(request["bytes_valid"] is True, "bytes individuais nao validados")
        current_ttfb = finite(request["ttfb_us"], "TTFB")
        current_total = finite(request["total_time_us"], "tempo total")
        headers = finite(request["headers_time_us"], "tempo de cabecalhos")
        require(0 <= headers <= current_ttfb <= current_total, "ordem temporal invalida")
        ttfb_us.append(current_ttfb)
        total_us.append(current_total)
        resources.add(request["resource"])

    if workload == "B" and mode == "warm":
        require(len(resources) == 100, "Carga B nao possui 100 recursos distintos")

    window = finite(summary["measurement_window_seconds"], "janela")
    rps = finite(summary["rps"], "RPS")
    throughput = finite(summary["throughput_mbps"], "throughput")
    require(window > 0 and rps > 0 and throughput > 0, "metrica nao positiva")
    require(abs(rps - round(expected_count / window, 6)) <= 1.1e-6, "RPS inconsistente")
    require(
        abs(throughput - round(expected_total * 8 / window / 1_000_000, 6))
        <= 1.1e-6,
        "throughput inconsistente",
    )

    connections = int(summary["connections_created"])
    if mode == "cold":
        require(connections == expected_count, "cold reutilizou conexoes")
    elif workload == "B" and protocol == "http1":
        require(connections == 6, "pool HTTP/1.1 diferente de seis conexoes")
    else:
        require(connections == 1, "warm deveria usar uma conexao")

    return Sample(
        source_file=path.name,
        batch_id=batch_id,
        test_id=test_id,
        repetition=repetition,
        workload=workload,
        protocol=protocol,
        scenario=scenario,
        mode=mode,
        request_count=expected_count,
        successful_requests=expected_count,
        failed_requests=0,
        bytes_received=expected_total,
        connections_created=connections,
        request_ttfb_mean_ms=fmean(ttfb_us) / 1_000,
        request_total_mean_ms=fmean(total_us) / 1_000,
        request_latency_p50_ms=percentile(total_us, 0.50) / 1_000,
        request_latency_p99_ms=percentile(total_us, 0.99) / 1_000,
        batch_duration_s=window,
        rps=rps,
        throughput_mbps=throughput,
    )


def load_samples(raw_dir: Path, batch_id: str) -> tuple[list[Sample], dict]:
    expected_hashes = manifest_hashes(raw_dir, batch_id)
    paths = sorted(raw_dir.glob(f"{batch_id}_*.json"))
    require(len(paths) == 240, f"esperados 240 JSONs, encontrados {len(paths)}")
    require({path.name for path in paths} == set(expected_hashes), "manifesto e JSONs divergem")

    samples: list[Sample] = []
    keys: set[tuple[str, int, str]] = set()
    run_ids: set[str] = set()
    total_requests = 0
    total_bytes = 0
    for path in paths:
        require(sha256(path) == expected_hashes[path.name], f"hash divergente: {path.name}")
        with path.open(encoding="utf-8") as source:
            payload = json.load(source)
        run_id = payload["run"]["run_id"]
        require(run_id not in run_ids, f"run_id duplicado: {run_id}")
        run_ids.add(run_id)
        sample = validate_and_convert(path, payload, batch_id)
        key = (sample.test_id, sample.repetition, sample.mode)
        require(key not in keys, f"medicao duplicada: {key}")
        keys.add(key)
        samples.append(sample)
        total_requests += sample.successful_requests
        total_bytes += sample.bytes_received

    for test_id in MATRIX:
        for mode in MODES:
            repetitions = {
                sample.repetition
                for sample in samples
                if sample.test_id == test_id and sample.mode == mode
            }
            require(repetitions == set(range(1, 11)), f"{test_id}/{mode} incompleto")
    require(total_requests == 6_180, f"total de requisicoes inesperado: {total_requests}")
    require(total_bytes == 6_353_510_400, f"total de bytes inesperado: {total_bytes}")
    return samples, {
        "manifest_verified": True,
        "input_files": len(paths),
        "valid_measurements": len(samples),
        "invalid_measurements": 0,
        "successful_requests": total_requests,
        "failed_requests": 0,
        "total_bytes_received": total_bytes,
    }


def grouped(samples: list[Sample]) -> dict[tuple[str, str], list[Sample]]:
    result: dict[tuple[str, str], list[Sample]] = defaultdict(list)
    for sample in samples:
        result[(sample.test_id, sample.mode)].append(sample)
    for values in result.values():
        values.sort(key=lambda sample: sample.repetition)
    return result


def stats_row(sample: Sample, metric_scope: str, unit: str, values: list[float]) -> dict:
    return {
        "batch_id": sample.batch_id,
        "test_id": sample.test_id,
        "workload": sample.workload,
        "protocol": PROTOCOL_LABELS[sample.protocol],
        "scenario": sample.scenario,
        "mode": sample.mode,
        "metric_scope": metric_scope,
        "unit": unit,
        **describe(values),
    }


def format_cell(value):
    if isinstance(value, float):
        return f"{value:.9f}".rstrip("0").rstrip(".")
    return value


def write_csv(path: Path, rows: list[dict], fieldnames: list[str] | None = None) -> None:
    require(bool(rows) or fieldnames is not None, f"CSV sem estrutura: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = fieldnames or list(rows[0])
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: format_cell(row.get(column)) for column in columns})


def repetition_rows(samples: list[Sample]) -> list[dict]:
    rows = []
    for sample in sorted(samples, key=lambda item: (item.test_id, item.mode, item.repetition)):
        rows.append(
            {
                "batch_id": sample.batch_id,
                "test_id": sample.test_id,
                "repetition": sample.repetition,
                "workload": sample.workload,
                "protocol": PROTOCOL_LABELS[sample.protocol],
                "scenario": sample.scenario,
                "mode": sample.mode,
                "request_count": sample.request_count,
                "successful_requests": sample.successful_requests,
                "failed_requests": sample.failed_requests,
                "bytes_received": sample.bytes_received,
                "connections_created": sample.connections_created,
                "request_ttfb_mean_ms": sample.request_ttfb_mean_ms,
                "request_total_mean_ms": sample.request_total_mean_ms,
                "request_latency_p50_ms": sample.request_latency_p50_ms,
                "request_latency_p99_ms": sample.request_latency_p99_ms,
                "batch_duration_s": sample.batch_duration_s,
                "rps": sample.rps,
                "throughput_mbps": sample.throughput_mbps,
                "source_file": sample.source_file,
            }
        )
    return rows


def build_tables(samples: list[Sample]) -> dict[str, list[dict]]:
    groups = grouped(samples)
    ttfb_rows: list[dict] = []
    total_rows: list[dict] = []
    rps_rows: list[dict] = []
    throughput_rows: list[dict] = []
    latency_rows: list[dict] = []
    quality_rows: list[dict] = []

    for test_id in sorted(MATRIX):
        for mode in MODES:
            values = groups[(test_id, mode)]
            first = values[0]
            ttfb_rows.append(
                stats_row(
                    first,
                    "mean_request_ttfb_per_repetition",
                    "ms",
                    [sample.request_ttfb_mean_ms for sample in values],
                )
            )
            total_rows.append(
                stats_row(
                    first,
                    "mean_individual_request_total_time_per_repetition",
                    "ms",
                    [sample.request_total_mean_ms for sample in values],
                )
            )
            total_rows.append(
                stats_row(
                    first,
                    "complete_batch_duration_per_repetition",
                    "s",
                    [sample.batch_duration_s for sample in values],
                )
            )
            if first.workload == "A":
                throughput_rows.append(
                    stats_row(
                        first,
                        "complete_50_mib_transfer",
                        "Mbps",
                        [sample.throughput_mbps for sample in values],
                    )
                )
            if first.workload == "B" and mode == "warm":
                rps_rows.append(
                    stats_row(
                        first,
                        "complete_battery_100_objects",
                        "requests/s",
                        [sample.rps for sample in values],
                    )
                )
                latency_rows.append(
                    stats_row(
                        first,
                        "within_battery_request_latency_p50",
                        "ms",
                        [sample.request_latency_p50_ms for sample in values],
                    )
                )
                latency_rows.append(
                    stats_row(
                        first,
                        "within_battery_request_latency_p99",
                        "ms",
                        [sample.request_latency_p99_ms for sample in values],
                    )
                )

            scheduled = sum(sample.request_count for sample in values)
            successful = sum(sample.successful_requests for sample in values)
            failed = sum(sample.failed_requests for sample in values)
            total_bytes = sum(sample.bytes_received for sample in values)
            quality_rows.append(
                {
                    "batch_id": first.batch_id,
                    "test_id": first.test_id,
                    "workload": first.workload,
                    "protocol": PROTOCOL_LABELS[first.protocol],
                    "scenario": first.scenario,
                    "mode": first.mode,
                    "repetitions": len(values),
                    "requests_scheduled": scheduled,
                    "successful_requests": successful,
                    "failed_requests": failed,
                    "success_rate_percent": successful / scheduled * 100,
                    "total_bytes_received": total_bytes,
                    "mean_bytes_per_repetition": total_bytes / len(values),
                }
            )

    return {
        "repetition_metrics.csv": repetition_rows(samples),
        "ttfb_statistics.csv": ttfb_rows,
        "total_time_statistics.csv": total_rows,
        "rps_statistics.csv": rps_rows,
        "throughput_statistics.csv": throughput_rows,
        "request_latency_percentiles.csv": latency_rows,
        "execution_quality.csv": quality_rows,
    }


def detect_outliers(samples: list[Sample]) -> list[dict]:
    groups = grouped(samples)
    definitions = [
        ("request_ttfb_mean_ms", "ms"),
        ("request_total_mean_ms", "ms"),
        ("batch_duration_s", "s"),
    ]
    rows: list[dict] = []
    for (test_id, mode), values in groups.items():
        local_definitions = list(definitions)
        if values[0].workload == "A":
            local_definitions.append(("throughput_mbps", "Mbps"))
        if values[0].workload == "B" and mode == "warm":
            local_definitions.extend(
                [
                    ("rps", "requests/s"),
                    ("request_latency_p50_ms", "ms"),
                    ("request_latency_p99_ms", "ms"),
                ]
            )
        for metric, unit in local_definitions:
            series = [float(getattr(sample, metric)) for sample in values]
            q1 = percentile(series, 0.25)
            q3 = percentile(series, 0.75)
            iqr = q3 - q1
            lower = q1 - 1.5 * iqr
            upper = q3 + 1.5 * iqr
            for sample, value in zip(values, series):
                if value < lower or value > upper:
                    rows.append(
                        {
                            "batch_id": sample.batch_id,
                            "test_id": test_id,
                            "workload": sample.workload,
                            "protocol": PROTOCOL_LABELS[sample.protocol],
                            "scenario": sample.scenario,
                            "mode": mode,
                            "repetition": sample.repetition,
                            "metric": metric,
                            "unit": unit,
                            "value": value,
                            "q1": q1,
                            "q3": q3,
                            "lower_fence": lower,
                            "upper_fence": upper,
                            "action": "preserved; not excluded",
                            "source_file": sample.source_file,
                        }
                    )
    rows.sort(key=lambda row: (row["test_id"], row["mode"], row["metric"], row["repetition"]))
    return rows


def set_style() -> None:
    plt.style.use("seaborn-v0_8-whitegrid")
    plt.rcParams.update(
        {
            "font.size": 10,
            "axes.titlesize": 12,
            "axes.labelsize": 10,
            "legend.fontsize": 9,
            "figure.titlesize": 14,
        }
    )


def save_figure(fig, path: Path) -> None:
    fig.text(
        0.5,
        0.01,
        "Barras de erro: intervalo de confiança de 95% (t de Student, n=10).",
        ha="center",
        fontsize=8,
    )
    fig.tight_layout(rect=(0, 0.04, 1, 0.94))
    fig.savefig(path, dpi=300, bbox_inches="tight")
    plt.close(fig)


def samples_for(
    samples: list[Sample],
    *,
    workload: str,
    scenario: str,
    protocol: str,
    mode: str,
) -> list[Sample]:
    values = [
        sample
        for sample in samples
        if sample.workload == workload
        and sample.scenario == scenario
        and sample.protocol == protocol
        and sample.mode == mode
    ]
    require(len(values) == 10, "serie grafica incompleta")
    return sorted(values, key=lambda sample: sample.repetition)


def protocol_bars(
    ax,
    samples: list[Sample],
    *,
    workload: str,
    scenario: str,
    mode: str,
    attribute: str,
    title: str,
    ylabel: str,
) -> None:
    means = []
    errors = []
    for protocol in PROTOCOLS:
        values = [
            float(getattr(sample, attribute))
            for sample in samples_for(
                samples,
                workload=workload,
                scenario=scenario,
                protocol=protocol,
                mode=mode,
            )
        ]
        summary = describe(values)
        means.append(summary["mean"])
        errors.append(summary["ci95_half_width"])
    x = list(range(len(PROTOCOLS)))
    ax.bar(
        x,
        means,
        yerr=errors,
        capsize=5,
        color=[PROTOCOL_COLORS[protocol] for protocol in PROTOCOLS],
        edgecolor="#333333",
        linewidth=0.6,
        error_kw={"elinewidth": 1.2, "capthick": 1.2},
    )
    ax.set_xticks(x, [PROTOCOL_LABELS[protocol] for protocol in PROTOCOLS])
    ax.set_title(title)
    ax.set_ylabel(ylabel)
    ax.grid(axis="y", alpha=0.35)


def graph_ttfb_cold(samples: list[Sample], path: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(11, 5.5))
    width = 0.36
    x = list(range(len(PROTOCOLS)))
    for ax, workload in zip(axes, ("A", "B")):
        for index, scenario in enumerate(SCENARIOS):
            means = []
            errors = []
            for protocol in PROTOCOLS:
                values = [
                    sample.request_ttfb_mean_ms
                    for sample in samples_for(
                        samples,
                        workload=workload,
                        scenario=scenario,
                        protocol=protocol,
                        mode="cold",
                    )
                ]
                summary = describe(values)
                means.append(summary["mean"])
                errors.append(summary["ci95_half_width"])
            ax.bar(
                [position + (index - 0.5) * width for position in x],
                means,
                width,
                yerr=errors,
                capsize=4,
                color=[PROTOCOL_COLORS[protocol] for protocol in PROTOCOLS],
                hatch="" if scenario == "LAN" else "//",
                alpha=1.0 if scenario == "LAN" else 0.72,
                edgecolor="#333333",
                error_kw={"elinewidth": 1.1, "capthick": 1.1},
            )
        ax.set_xticks(x, [PROTOCOL_LABELS[p] for p in PROTOCOLS])
        ax.set_title(f"Carga {workload}")
        ax.set_ylabel("TTFB médio por repetição (ms)")
        ax.grid(axis="y", alpha=0.35)
    axes[1].legend(
        handles=[
            Patch(facecolor="#777777", label="LAN"),
            Patch(facecolor="#AAAAAA", hatch="//", label="WAN"),
        ],
        title="Cenário",
    )
    fig.suptitle("TTFB cold por protocolo, cenário e carga")
    save_figure(fig, path)


def graph_load_a_total(samples: list[Sample], path: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(11, 5.5))
    for ax, scenario in zip(axes, SCENARIOS):
        protocol_bars(
            ax,
            samples,
            workload="A",
            scenario=scenario,
            mode="warm",
            attribute="batch_duration_s",
            title=scenario,
            ylabel="Duração completa da transferência (s)",
        )
    fig.suptitle("Tempo total warm da Carga A (50 MiB)")
    save_figure(fig, path)


def graph_load_a_throughput(samples: list[Sample], path: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(11, 5.5))
    for ax, scenario in zip(axes, SCENARIOS):
        protocol_bars(
            ax,
            samples,
            workload="A",
            scenario=scenario,
            mode="warm",
            attribute="throughput_mbps",
            title=scenario,
            ylabel="Throughput útil (Mbps)",
        )
    fig.suptitle("Throughput warm da Carga A (50 MiB)")
    save_figure(fig, path)


def graph_load_b_rps(samples: list[Sample], path: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(11, 5.5))
    for ax, scenario in zip(axes, SCENARIOS):
        protocol_bars(
            ax,
            samples,
            workload="B",
            scenario=scenario,
            mode="warm",
            attribute="rps",
            title=scenario,
            ylabel="Requisições por segundo",
        )
    fig.suptitle("RPS warm da Carga B (100 × 10 KiB)")
    save_figure(fig, path)


def graph_load_b_latency(samples: list[Sample], path: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(11, 5.5))
    width = 0.36
    x = list(range(len(PROTOCOLS)))
    for ax, scenario in zip(axes, SCENARIOS):
        for index, (attribute, label, hatch) in enumerate(
            (
                ("request_latency_p50_ms", "p50", ""),
                ("request_latency_p99_ms", "p99", "//"),
            )
        ):
            means = []
            errors = []
            for protocol in PROTOCOLS:
                values = [
                    float(getattr(sample, attribute))
                    for sample in samples_for(
                        samples,
                        workload="B",
                        scenario=scenario,
                        protocol=protocol,
                        mode="warm",
                    )
                ]
                summary = describe(values)
                means.append(summary["mean"])
                errors.append(summary["ci95_half_width"])
            ax.bar(
                [position + (index - 0.5) * width for position in x],
                means,
                width,
                yerr=errors,
                capsize=4,
                color=[PROTOCOL_COLORS[protocol] for protocol in PROTOCOLS],
                hatch=hatch,
                alpha=1.0 if label == "p50" else 0.72,
                edgecolor="#333333",
                error_kw={"elinewidth": 1.1, "capthick": 1.1},
            )
        ax.set_xticks(x, [PROTOCOL_LABELS[p] for p in PROTOCOLS])
        ax.tick_params(axis="x", labelsize=8, labelrotation=10)
        ax.set_title(scenario)
        ax.set_ylabel("Latência individual (ms)")
        ax.grid(axis="y", alpha=0.35)
    axes[1].legend(
        handles=[
            Patch(facecolor="#888888", label="p50"),
            Patch(facecolor="#AAAAAA", hatch="//", label="p99"),
        ],
        title="Percentil interno",
    )
    fig.suptitle("Latência p50 e p99 das requisições — Carga B warm")
    save_figure(fig, path)


def graph_network_degradation(samples: list[Sample], path: Path) -> None:
    fig, ax = plt.subplots(figsize=(9.5, 5.8))
    width = 0.36
    x = list(range(len(PROTOCOLS)))
    for index, scenario in enumerate(SCENARIOS):
        means = []
        errors = []
        for protocol in PROTOCOLS:
            values = [
                sample.batch_duration_s
                for sample in samples_for(
                    samples,
                    workload="B",
                    scenario=scenario,
                    protocol=protocol,
                    mode="warm",
                )
            ]
            summary = describe(values)
            means.append(summary["mean"])
            errors.append(summary["ci95_half_width"])
        ax.bar(
            [position + (index - 0.5) * width for position in x],
            means,
            width,
            yerr=errors,
            capsize=4,
            color=[PROTOCOL_COLORS[protocol] for protocol in PROTOCOLS],
            hatch="" if scenario == "LAN" else "//",
            alpha=1.0 if scenario == "LAN" else 0.72,
            edgecolor="#333333",
            error_kw={"elinewidth": 1.1, "capthick": 1.1},
        )
    ax.set_xticks(x, [PROTOCOL_LABELS[p] for p in PROTOCOLS])
    ax.set_ylabel("Duração completa da bateria (s, escala log)")
    ax.set_yscale("log")
    ax.set_title("Impacto de LAN para WAN — Carga B warm")
    ax.legend(
        handles=[
            Patch(facecolor="#777777", label="LAN"),
            Patch(facecolor="#AAAAAA", hatch="//", label="WAN"),
        ],
        title="Cenário",
    )
    ax.grid(axis="y", which="both", alpha=0.35)
    save_figure(fig, path)


def generate_figures(samples: list[Sample], figures_dir: Path) -> list[dict]:
    figures_dir.mkdir(parents=True, exist_ok=True)
    set_style()
    definitions = [
        (
            "01_ttfb_cold.png",
            "TTFB cold por protocolo, cenário e carga",
            "mean request TTFB per repetition",
            graph_ttfb_cold,
        ),
        (
            "02_total_time_load_a_warm.png",
            "Tempo total warm da Carga A",
            "complete 50 MiB transfer per repetition",
            graph_load_a_total,
        ),
        (
            "03_throughput_load_a_warm.png",
            "Throughput warm da Carga A",
            "complete 50 MiB transfer per repetition",
            graph_load_a_throughput,
        ),
        (
            "04_rps_load_b_warm.png",
            "RPS warm da Carga B",
            "complete 100-object battery per repetition",
            graph_load_b_rps,
        ),
        (
            "05_latency_p50_p99_load_b_warm.png",
            "p50 e p99 internos das requisições da Carga B",
            "one within-battery percentile per repetition",
            graph_load_b_latency,
        ),
        (
            "06_network_degradation_load_b_warm.png",
            "Impacto LAN/WAN no tempo da Carga B warm",
            "complete 100-object battery per repetition",
            graph_network_degradation,
        ),
    ]
    manifest = []
    for filename, description, sample_unit, function in definitions:
        destination = figures_dir / filename
        function(samples, destination)
        require(destination.is_file() and destination.stat().st_size > 0, f"PNG ausente: {filename}")
        manifest.append(
            {
                "figure": filename,
                "description": description,
                "sample_unit": sample_unit,
                "error_bars": True,
                "error_bar_method": "95% confidence interval; Student t; df=9; n=10",
                "dpi": 300,
            }
        )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Processa o lote oficial e gera tabelas e gráficos da Etapa 7"
    )
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--raw-dir", type=Path, default=PROJECT_ROOT / "results" / "raw")
    parser.add_argument(
        "--output-dir", type=Path, default=PROJECT_ROOT / "results" / "processed"
    )
    args = parser.parse_args()

    raw_dir = args.raw_dir.resolve()
    output_dir = args.output_dir.resolve()
    samples, validation = load_samples(raw_dir, args.batch_id)
    tables = build_tables(samples)
    for filename, rows in tables.items():
        write_csv(output_dir / filename, rows)

    outlier_fields = [
        "batch_id",
        "test_id",
        "workload",
        "protocol",
        "scenario",
        "mode",
        "repetition",
        "metric",
        "unit",
        "value",
        "q1",
        "q3",
        "lower_fence",
        "upper_fence",
        "action",
        "source_file",
    ]
    outliers = detect_outliers(samples)
    write_csv(output_dir / "outlier_observations.csv", outliers, outlier_fields)

    figure_manifest = generate_figures(samples, output_dir / "figures")
    write_csv(output_dir / "figures_manifest.csv", figure_manifest)

    summary = {
        "schema_version": 1,
        "batch_id": args.batch_id,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "validation": validation,
        "statistics": {
            "experimental_sample": "one repetition-level value; n=10 per combination",
            "mean": "arithmetic mean across 10 independent repetitions",
            "median": "median across 10 independent repetitions",
            "sample_standard_deviation": "statistics.stdev; denominator n-1",
            "percentiles": "linear interpolation over the 10 repetition-level values",
            "confidence_interval_95": (
                "mean +/- t(0.975, df=9) * sample_std / sqrt(10); "
                f"t={T_CRITICAL_975_DF9}"
            ),
            "load_b_internal_percentiles": (
                "p50/p99 calculated inside each 100-request battery, then summarized "
                "across the 10 independent repetitions"
            ),
            "missing_values": "not replaced by zero",
        },
        "outliers": {
            "method": "Tukey fences: Q1 - 1.5*IQR and Q3 + 1.5*IQR",
            "observations_flagged": len(outliers),
            "excluded": 0,
            "policy": "all original observations preserved",
        },
        "tables": list(tables) + [
            "outlier_observations.csv",
            "figures_manifest.csv",
        ],
        "figures": figure_manifest,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "analysis_summary.json").open("w", encoding="utf-8") as output:
        json.dump(summary, output, ensure_ascii=False, indent=2)
        output.write("\n")

    print(f"batch_id={args.batch_id}")
    print(
        f"files={validation['input_files']} valid={validation['valid_measurements']} "
        f"invalid={validation['invalid_measurements']}"
    )
    print(f"tables={len(summary['tables'])} figures={len(figure_manifest)}")
    print(f"outliers_flagged={len(outliers)} excluded=0")
    print(f"output={output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
