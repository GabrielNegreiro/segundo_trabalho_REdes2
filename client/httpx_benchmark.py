import asyncio
import ssl
from time import perf_counter_ns

import httpx

from .models import RequestRecord, elapsed_us, error_record, utc_now


def _request_url(base_url: str, resource: str, nonce: str) -> str:
    url = f"{base_url.rstrip('/')}/{resource.lstrip('/')}"
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}benchmark_nonce={nonce}"


def _tls_context(ca_cert: str) -> ssl.SSLContext:
    context = ssl.create_default_context(cafile=ca_cert)
    context.minimum_version = ssl.TLSVersion.TLSv1_3
    context.maximum_version = ssl.TLSVersion.TLSv1_3
    return context


def _actual_tls_version(response: httpx.Response) -> str | None:
    stream = response.extensions.get("network_stream")
    get_extra_info = getattr(stream, "get_extra_info", None)
    if get_extra_info is None:
        return None
    ssl_object = get_extra_info("ssl_object")
    return ssl_object.version() if ssl_object is not None else None


async def _perform_request(
    *,
    client: httpx.AsyncClient,
    run_id: str,
    request_id: str,
    protocol: str,
    mode: str,
    base_url: str,
    resource: str,
    connection_ids: set[str] | None = None,
) -> RequestRecord:
    expected_version = "HTTP/1.1" if protocol == "http1" else "HTTP/2"
    protocol_label = expected_version
    transport = "TCP"
    timestamp = utc_now()
    start_ns = perf_counter_ns()
    url = _request_url(base_url, resource, f"{run_id}-{request_id}")

    try:
        async with client.stream(
            "GET",
            url,
            headers={
                "accept-encoding": "identity",
                "cache-control": "no-cache, no-store",
                "pragma": "no-cache",
            },
        ) as response:
            headers_ns = perf_counter_ns()
            tls_version = _actual_tls_version(response)
            network_stream = response.extensions.get("network_stream")
            connection_id = (
                f"tcp-{id(network_stream):x}" if network_stream is not None else None
            )
            if connection_id is not None and connection_ids is not None:
                connection_ids.add(connection_id)
            first_byte_ns: int | None = None
            bytes_received = 0

            async for chunk in response.aiter_raw():
                if chunk and first_byte_ns is None:
                    first_byte_ns = perf_counter_ns()
                bytes_received += len(chunk)

            end_ns = perf_counter_ns()
            errors: list[str] = []
            if response.http_version != expected_version:
                errors.append(
                    f"protocolo negociado {response.http_version}, esperado {expected_version}"
                )
            if response.status_code != 200:
                errors.append(f"status HTTP inesperado: {response.status_code}")
            if protocol == "http2" and tls_version != "TLSv1.3":
                errors.append(f"TLS negociado {tls_version}, esperado TLSv1.3")
            content_encoding = response.headers.get("content-encoding")
            if content_encoding and content_encoding.lower() != "identity":
                errors.append(f"compressao HTTP inesperada: {content_encoding}")

            return RequestRecord(
                run_id=run_id,
                request_id=request_id,
                timestamp_start_utc=timestamp,
                protocol=protocol_label,
                negotiated_protocol=response.http_version,
                transport=transport,
                tls_version=tls_version,
                connection_mode=mode,
                server_url=base_url,
                resource=resource,
                status_code=response.status_code,
                headers_time_us=elapsed_us(start_ns, headers_ns),
                ttfb_us=elapsed_us(start_ns, first_byte_ns)
                if first_byte_ns is not None
                else None,
                total_time_us=elapsed_us(start_ns, end_ns),
                bytes_received=bytes_received,
                success=not errors,
                error="; ".join(errors) if errors else None,
                connection_id=connection_id,
            )
    except Exception as exc:
        return error_record(
            run_id=run_id,
            request_id=request_id,
            timestamp_start_utc=timestamp,
            protocol=protocol_label,
            transport=transport,
            tls_version="TLSv1.3" if protocol == "http2" else None,
            mode=mode,
            server_url=base_url,
            resource=resource,
            start_ns=start_ns,
            error=exc,
        )


def _client(
    protocol: str, ca_cert: str, timeout_seconds: float, max_connections: int
) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        http1=True,
        http2=protocol == "http2",
        verify=_tls_context(ca_cert) if protocol == "http2" else True,
        timeout=httpx.Timeout(timeout_seconds),
        limits=httpx.Limits(
            max_connections=max_connections,
            max_keepalive_connections=max_connections,
        ),
        trust_env=False,
    )


async def run_httpx_benchmark(
    *,
    run_id: str,
    protocol: str,
    mode: str,
    resources: list[str],
    base_url: str,
    resource: str,
    ca_cert: str,
    timeout_seconds: float,
    http1_concurrency: int = 1,
) -> tuple[list[RequestRecord], float, int]:
    records: list[RequestRecord] = []

    if mode == "cold":
        window_start_ns = perf_counter_ns()
        for index, request_resource in enumerate(resources):
            async with _client(protocol, ca_cert, timeout_seconds, 1) as client:
                records.append(
                    await _perform_request(
                        client=client,
                        run_id=run_id,
                        request_id=f"req-{index + 1:04d}",
                        protocol=protocol,
                        mode=mode,
                        base_url=base_url,
                        resource=request_resource,
                    )
                )
        window_end_ns = perf_counter_ns()
        return records, (window_end_ns - window_start_ns) / 1_000_000_000, len(resources)

    max_connections = http1_concurrency if protocol == "http1" else 1
    connection_ids: set[str] = set()
    async with _client(protocol, ca_cert, timeout_seconds, max_connections) as client:
        await _perform_request(
            client=client,
            run_id=run_id,
            request_id="warmup",
            protocol=protocol,
            mode=mode,
            base_url=base_url,
            resource=resource,
            connection_ids=connection_ids,
        )

        window_start_ns = perf_counter_ns()
        if protocol == "http1" and http1_concurrency == 1:
            for index, request_resource in enumerate(resources):
                records.append(
                    await _perform_request(
                        client=client,
                        run_id=run_id,
                        request_id=f"req-{index + 1:04d}",
                        protocol=protocol,
                        mode=mode,
                        base_url=base_url,
                        resource=request_resource,
                        connection_ids=connection_ids,
                    )
                )
        else:
            records = list(
                await asyncio.gather(
                    *[
                        _perform_request(
                            client=client,
                            run_id=run_id,
                            request_id=f"req-{index + 1:04d}",
                            protocol=protocol,
                            mode=mode,
                            base_url=base_url,
                            resource=request_resource,
                            connection_ids=connection_ids,
                        )
                        for index, request_resource in enumerate(resources)
                    ]
                )
            )
        window_end_ns = perf_counter_ns()

    return (
        records,
        (window_end_ns - window_start_ns) / 1_000_000_000,
        len(connection_ids),
    )
