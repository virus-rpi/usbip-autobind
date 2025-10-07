import asyncio
import logging

from src.server.client_manager import ClientManager


class TcpServer:
    def __init__(self, socket_host, socket_port, client_manager: ClientManager):
        self.socket_host = socket_host
        self.socket_port = socket_port
        self.client_manager: ClientManager = client_manager
        self.logger = logging.getLogger("usbip-host-autobind")

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        peer = writer.get_extra_info('peername')
        self.logger.info(f"Client connected from {peer}")

        try:
            first = await reader.readuntil(separator=b'\n')
        except asyncio.IncompleteReadError:
            first = await reader.read(100)
        raw = (first or b'').decode(errors='ignore').strip()
        client_id = None
        if raw.startswith("CLIENT_ID:"):
            client_id = raw.split(":", 1)[1].strip()
        if not client_id:
            client_id = f"{peer[0]}:{peer[1]}"

        await self.client_manager.register_client(client_id, writer)

        try:
            while True:
                data = await reader.read(256)
                if not data:
                    self.logger.info(f"Client disconnected: {client_id}")
                    break
        except (ConnectionResetError, OSError):
            self.logger.info(f"Client connection reset: {client_id}")
        except asyncio.CancelledError:
            self.logger.info(f"Client handler cancelled: {client_id}")
        finally:
            self.client_manager.unregister_client(client_id)

    async def start_server(self):
        server = await asyncio.start_server(
            self.handle_client,
            self.socket_host,
            self.socket_port,
        )
        self.logger.info(f"USBIP control socket listening on {self.socket_host}:{self.socket_port}")
        return asyncio.create_task(server.serve_forever())
