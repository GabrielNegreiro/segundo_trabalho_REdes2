import asyncio
import ssl
from dataclasses import dataclass, field
from time import perf_counter_ns
from urllib.parse import urlsplit

from aioquic.asyncio import connect
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.h3.connection import H3_ALPN, H3Connection
from aioquic.h3.events import DataReceived, HeadersReceived
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import ConnectionTerminated, ProtocolNegotiated, QuicEvent

from .models import RequestRecord, elapsed_us, error_record, utc_now


@dataclass
class _PendingRequest:
    run_id: str
    request_id: str
    timestamp_start_utc: str
    mode: str
    server_url: str
    resource: str
    start_ns: int
    future: asyncio.Future[RequestRecord]
    headers: list[tuple[bytes, bytes]] = field(default_factory=list)
    headers_ns: int | None = None
    first_byte_ns: int | None = None
    bytes_received: int = 0


class Http3BenchmarkProtocol(QuicConnectionProtocol):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.http: H3Connection | None = None
        self.alpn: str | None = None
        self.pending: dict[int, _PendingRequest] = {}

    def quic_event_received(self, event: QuicEvent) -> None:
        if isinstance(event, ProtocolNegotiated):
            self.alpn = event.alpn_protocol
            self.http = H3Connection(self._quic)

        if isinstance(event, ConnectionTerminated):
            for pending in self.pending.values():
                if not pending.future.done():
                    pending.future.set_exception(
                        ConnectionError(
                            f"conexão QUIC encerrada: código={event.error_code}"
                        )
                    )
            self.pending.clear()
            return

        if self.http is None:
            return

        for http_event in self.http.handle_event(event):
            if not isinstance(http_event, (HeadersReceived, DataReceived)):
                continue
            pending = self.pending.get(http_event.stream_id)
            if pending is None:
                continue

            event_ns = perf_counter_ns()
            if isinstance(http_event, HeadersReceived):
                if pending.headers_ns is None:
                    pending.headers_ns = event_ns
                pending.headers.extend(http_event.headers)
            else:
                if http_event.data and pending.first_byte_ns is None:
                    pending.first_byte_ns = event_ns
                pending.bytes_received += len(http_event.data)

            if http_event.stream_ended:
                self._finish(http_event.stream_id, event_ns)

    def _finish(self, stream_id: int, end_ns: int) -> None:
        pending = self.pending.pop(stream_id)
        headers = dict(pending.headers)
        status_bytes = headers.get(b":status")
        status_code = int(status_bytes) if status_bytes is not None else None
        errors: list[str] = []
        if self.alpn != "h3":
            errors.append(f"ALPN negociado {self.alpn}, esperado h3")
        if status_code != 200:
            errors.append(f"status HTTP inesperado: {status_code}")
        content_encoding = headers.get(b"content-encoding")
        if content_encoding and content_encoding.lower() != b"identity":
            errors.append(
                "compressao HTTP inesperada: "
                + content_encoding.decode(errors="replace")
            )

        record = RequestRecord(
            run_id=pending.run_id,
            request_id=pending.request_id,
            timestamp_start_utc=pending.timestamp_start_utc,
            protocol="HTTP/3",
            negotiated_protocol="HTTP/3" if self.alpn == "h3" else self.alpn,
            transport="QUIC/UDP",
            tls_version="TLSv1.3",
            connection_mode=pending.mode,
            server_url=pending.server_url,
            resource=pending.resource,
            status_code=status_code,
            headers_time_us=elapsed_us(pending.start_ns, pending.headers_ns)
            if pending.headers_ns is not None
            else None,
            ttfb_us=elapsed_us(pending.start_ns, pending.first_byte_ns)
            if pending.first_byte_ns is not None
            else None,
            total_time_us=elapsed_us(pending.start_ns, end_ns),
            bytes_received=pending.bytes_received,
            success=not errors,
            error="; ".join(errors) if errors else None,
            connection_id="quic-1",
        )
        if not pending.future.done():
            pending.future.set_result(record)

    async def get(
        self,
        *,
        run_id: str,
        request_id: str,
        mode: str,
        server_url: str,
        resource: str,
        start_ns: int | None = None,
        timestamp_start_utc: str | None = None,
    ) -> RequestRecord:
        if self.http is None or self.alpn != "h3":
            raise RuntimeError("HTTP/3 com ALPN h3 não foi negociado")

        parsed = urlsplit(server_url)
        authority = parsed.netloc
        separator = "&" if "?" in resource else "?"
        request_target = (
            f"{resource}{separator}benchmark_nonce={run_id}-{request_id}"
        )
        stream_id = self._quic.get_next_available_stream_id()
        future = asyncio.get_running_loop().create_future()
        pending = _PendingRequest(
            run_id=run_id,
            request_id=request_id,
            timestamp_start_utc=timestamp_start_utc or utc_now(),
            mode=mode,
            server_url=server_url,
            resource=resource,
            start_ns=start_ns or perf_counter_ns(),
            future=future,
        )
        self.pending[stream_id] = pending
        self.http.send_headers(
            stream_id=stream_id,
            headers=[
                (b":method", b"GET"),
                (b":scheme", b"https"),
                (b":authority", authority.encode()),
                (b":path", request_target.encode()),
                (b"cache-control", b"no-cache, no-store"),
                (b"accept-encoding", b"identity"),
                (b"pragma", b"no-cache"),
                (b"user-agent", b"redes2-benchmark"),
            ],
            end_stream=True,
        )
        self.transmit()
        return await future


def _configuration(
    host: str, ca_cert: str, timeout_seconds: float
) -> QuicConfiguration:
    return QuicConfiguration(
        is_client=True,
        alpn_protocols=H3_ALPN,
        server_name=host,
        cafile=ca_cert,
        verify_mode=ssl.CERT_REQUIRED,
        idle_timeout=timeout_seconds,
    )


async def _cold_request(
    *,
    run_id: str,
    request_id: str,
    base_url: str,
    resource: str,
    ca_cert: str,
    timeout_seconds: float,
) -> RequestRecord:
    parsed = urlsplit(base_url)
    host = parsed.hostname
    if host is None:
        raise ValueError(f"URL HTTP/3 inválida: {base_url}")
    port = parsed.port or 443
    timestamp = utc_now()
    start_ns = perf_counter_ns()

    try:
        async with connect(
            host,
            port,
            configuration=_configuration(host, ca_cert, timeout_seconds),
            create_protocol=Http3BenchmarkProtocol,
        ) as protocol:
            if not isinstance(protocol, Http3BenchmarkProtocol):
                raise RuntimeError("protocolo HTTP/3 inesperado")
            return await asyncio.wait_for(
                protocol.get(
                    run_id=run_id,
                    request_id=request_id,
                    mode="cold",
                    server_url=base_url,
                    resource=resource,
                    start_ns=start_ns,
                    timestamp_start_utc=timestamp,
                ),
                timeout=timeout_seconds,
            )
    except Exception as exc:
        return error_record(
            run_id=run_id,
            request_id=request_id,
            timestamp_start_utc=timestamp,
            protocol="HTTP/3",
            transport="QUIC/UDP",
            tls_version="TLSv1.3",
            mode="cold",
            server_url=base_url,
            resource=resource,
            start_ns=start_ns,
            error=exc,
        )


async def _warm_request(
    *,
    protocol: Http3BenchmarkProtocol,
    run_id: str,
    request_id: str,
    base_url: str,
    resource: str,
    timeout_seconds: float,
) -> RequestRecord:
    timestamp = utc_now()
    start_ns = perf_counter_ns()
    try:
        return await asyncio.wait_for(
            protocol.get(
                run_id=run_id,
                request_id=request_id,
                mode="warm",
                server_url=base_url,
                resource=resource,
                start_ns=start_ns,
                timestamp_start_utc=timestamp,
            ),
            timeout=timeout_seconds,
        )
    except Exception as exc:
        return error_record(
            run_id=run_id,
            request_id=request_id,
            timestamp_start_utc=timestamp,
            protocol="HTTP/3",
            transport="QUIC/UDP",
            tls_version="TLSv1.3",
            mode="warm",
            server_url=base_url,
            resource=resource,
            start_ns=start_ns,
            error=exc,
        )


async def run_http3_benchmark(
    *,
    run_id: str,
    mode: str,
    resources: list[str],
    base_url: str,
    resource: str,
    ca_cert: str,
    timeout_seconds: float,
) -> tuple[list[RequestRecord], float, int]:
    parsed = urlsplit(base_url)
    host = parsed.hostname
    if host is None:
        raise ValueError(f"URL HTTP/3 inválida: {base_url}")
    port = parsed.port or 443

    if mode == "cold":
        records: list[RequestRecord] = []
        window_start_ns = perf_counter_ns()
        for index, request_resource in enumerate(resources):
            records.append(
                await _cold_request(
                    run_id=run_id,
                    request_id=f"req-{index + 1:04d}",
                    base_url=base_url,
                    resource=request_resource,
                    ca_cert=ca_cert,
                    timeout_seconds=timeout_seconds,
                )
            )
        window_end_ns = perf_counter_ns()
        return records, (window_end_ns - window_start_ns) / 1_000_000_000, len(resources)

    connection_start_ns = perf_counter_ns()
    connection_timestamp = utc_now()
    try:
        async with connect(
            host,
            port,
            configuration=_configuration(host, ca_cert, timeout_seconds),
            create_protocol=Http3BenchmarkProtocol,
        ) as protocol:
            if not isinstance(protocol, Http3BenchmarkProtocol):
                raise RuntimeError("protocolo HTTP/3 inesperado")

            await asyncio.wait_for(
                protocol.get(
                    run_id=run_id,
                    request_id="warmup",
                    mode="warm",
                    server_url=base_url,
                    resource=resource,
                ),
                timeout=timeout_seconds,
            )

            window_start_ns = perf_counter_ns()
            records = list(
                await asyncio.gather(
                    *[
                        _warm_request(
                            protocol=protocol,
                            run_id=run_id,
                            request_id=f"req-{index + 1:04d}",
                            base_url=base_url,
                            resource=request_resource,
                            timeout_seconds=timeout_seconds,
                        )
                        for index, request_resource in enumerate(resources)
                    ]
                )
            )
            window_end_ns = perf_counter_ns()
        return records, (window_end_ns - window_start_ns) / 1_000_000_000, 1
    except Exception as exc:
        window_end_ns = perf_counter_ns()
        records = [
            error_record(
                run_id=run_id,
                request_id=f"req-{index + 1:04d}",
                timestamp_start_utc=connection_timestamp,
                protocol="HTTP/3",
                transport="QUIC/UDP",
                tls_version="TLSv1.3",
                mode="warm",
                server_url=base_url,
                resource=request_resource,
                start_ns=connection_start_ns,
                error=exc,
            )
            for index, request_resource in enumerate(resources)
        ]
        return (
            records,
            (window_end_ns - connection_start_ns) / 1_000_000_000,
            1,
        )
