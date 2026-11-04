"""Validação funcional mínima de HTTP/3; não realiza benchmark."""

import argparse
import asyncio
import ssl
from dataclasses import dataclass, field
from pathlib import Path

from aioquic.asyncio import connect
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.h3.connection import H3_ALPN, H3Connection
from aioquic.h3.events import DataReceived, HeadersReceived
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import ProtocolNegotiated, QuicEvent


@dataclass
class Response:
    headers: list[tuple[bytes, bytes]] = field(default_factory=list)
    body: bytearray = field(default_factory=bytearray)


class Http3ValidationClient(QuicConnectionProtocol):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.http: H3Connection | None = None
        self.alpn: str | None = None
        self.responses: dict[int, Response] = {}
        self.waiters: dict[int, asyncio.Future[Response]] = {}

    def quic_event_received(self, event: QuicEvent) -> None:
        if isinstance(event, ProtocolNegotiated):
            self.alpn = event.alpn_protocol
            self.http = H3Connection(self._quic)

        if self.http is None:
            return

        for http_event in self.http.handle_event(event):
            if not isinstance(http_event, (HeadersReceived, DataReceived)):
                continue

            response = self.responses[http_event.stream_id]
            if isinstance(http_event, HeadersReceived):
                response.headers.extend(http_event.headers)
            else:
                response.body.extend(http_event.data)

            if http_event.stream_ended:
                waiter = self.waiters.pop(http_event.stream_id)
                if not waiter.done():
                    waiter.set_result(response)

    async def get(self, authority: str, path: str) -> Response:
        if self.http is None:
            raise RuntimeError("HTTP/3 não foi negociado")

        stream_id = self._quic.get_next_available_stream_id()
        waiter = asyncio.get_running_loop().create_future()
        self.responses[stream_id] = Response()
        self.waiters[stream_id] = waiter
        self.http.send_headers(
            stream_id=stream_id,
            headers=[
                (b":method", b"GET"),
                (b":scheme", b"https"),
                (b":authority", authority.encode()),
                (b":path", path.encode()),
                (b"user-agent", b"redes2-http3-validator"),
            ],
            end_stream=True,
        )
        self.transmit()
        return await asyncio.wait_for(waiter, timeout=10)


async def validate(host: str, port: int, path: str, ca_cert: Path) -> None:
    configuration = QuicConfiguration(
        is_client=True,
        alpn_protocols=H3_ALPN,
        server_name=host,
        cafile=str(ca_cert),
        verify_mode=ssl.CERT_REQUIRED,
    )

    async with connect(
        host,
        port,
        configuration=configuration,
        create_protocol=Http3ValidationClient,
    ) as protocol:
        client = protocol
        if not isinstance(client, Http3ValidationClient):
            raise RuntimeError("Cliente HTTP/3 inesperado")
        response = await client.get(f"{host}:{port}", path)

        headers = dict(response.headers)
        print(f"protocol=HTTP/3 alpn={client.alpn} transport=QUIC/UDP tls=TLSv1.3")
        print(f"status={headers.get(b':status', b'?').decode()}")
        print(f"server={headers.get(b'server', b'?').decode()}")
        print(f"body={response.body.decode().strip()}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=9443)
    parser.add_argument("--path", default="/health.txt")
    parser.add_argument(
        "--ca-cert",
        type=Path,
        default=Path(__file__).resolve().parents[1]
        / "servers"
        / "certs"
        / "localhost.crt",
    )
    args = parser.parse_args()
    asyncio.run(validate(args.host, args.port, args.path, args.ca_cert))


if __name__ == "__main__":
    main()
