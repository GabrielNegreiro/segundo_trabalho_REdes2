from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from time import perf_counter_ns


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def elapsed_us(start_ns: int, end_ns: int) -> float:
    return round((end_ns - start_ns) / 1_000, 3)


@dataclass
class RequestRecord:
    run_id: str
    request_id: str
    timestamp_start_utc: str
    protocol: str
    negotiated_protocol: str | None
    transport: str
    tls_version: str | None
    connection_mode: str
    server_url: str
    resource: str
    status_code: int | None
    headers_time_us: float | None
    ttfb_us: float | None
    total_time_us: float | None
    bytes_received: int
    success: bool
    error: str | None
    expected_bytes: int | None = None
    bytes_valid: bool | None = None
    connection_id: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def error_record(
    *,
    run_id: str,
    request_id: str,
    timestamp_start_utc: str,
    protocol: str,
    transport: str,
    tls_version: str | None,
    mode: str,
    server_url: str,
    resource: str,
    start_ns: int,
    error: Exception | str,
) -> RequestRecord:
    return RequestRecord(
        run_id=run_id,
        request_id=request_id,
        timestamp_start_utc=timestamp_start_utc,
        protocol=protocol,
        negotiated_protocol=None,
        transport=transport,
        tls_version=tls_version,
        connection_mode=mode,
        server_url=server_url,
        resource=resource,
        status_code=None,
        headers_time_us=None,
        ttfb_us=None,
        total_time_us=elapsed_us(start_ns, perf_counter_ns()),
        bytes_received=0,
        success=False,
        error=f"{type(error).__name__}: {error}" if isinstance(error, Exception) else error,
    )
