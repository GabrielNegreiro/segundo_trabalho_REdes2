from statistics import fmean

from .models import RequestRecord


def percentile(values: list[float], probability: float) -> float | None:
    if not values:
        return None

    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * fraction, 3)


def metric_summary(values: list[float]) -> dict:
    if not values:
        return {"mean_us": None, "p50_us": None, "p99_us": None}
    return {
        "mean_us": round(fmean(values), 3),
        "p50_us": percentile(values, 0.50),
        "p99_us": percentile(values, 0.99),
    }


def summarize(
    records: list[RequestRecord],
    measurement_window_seconds: float,
    connections_created: int,
    expected_total_bytes: int | None = None,
) -> dict:
    successful = [record for record in records if record.success]
    total_times = [
        record.total_time_us
        for record in successful
        if record.total_time_us is not None
    ]
    ttfb_times = [
        record.ttfb_us for record in successful if record.ttfb_us is not None
    ]

    total_bytes_received = sum(record.bytes_received for record in records)
    bits_per_second = (
        total_bytes_received * 8 / measurement_window_seconds
        if measurement_window_seconds > 0
        else None
    )

    return {
        "requests_scheduled": len(records),
        "successful_requests": len(successful),
        "failed_requests": len(records) - len(successful),
        "measurement_window_seconds": round(measurement_window_seconds, 9),
        "rps": round(len(successful) / measurement_window_seconds, 6)
        if measurement_window_seconds > 0
        else None,
        "connections_created": connections_created,
        "total_bytes_received": total_bytes_received,
        "expected_total_bytes": expected_total_bytes,
        "bytes_valid": (
            total_bytes_received == expected_total_bytes
            and len(successful) == len(records)
            if expected_total_bytes is not None
            else None
        ),
        "throughput_mbps": round(bits_per_second / 1_000_000, 6)
        if bits_per_second is not None
        else None,
        "throughput_mib_s": round(
            total_bytes_received / measurement_window_seconds / (1024 * 1024), 6
        )
        if measurement_window_seconds > 0
        else None,
        "total_load_time": metric_summary(total_times),
        "ttfb": metric_summary(ttfb_times),
    }
