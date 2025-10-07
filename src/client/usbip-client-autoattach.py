#!/usr/bin/env python3
import asyncio
import logging
import re
import socket
import subprocess
import sys
import time
from asyncio import WriteTransport

logger = logging.getLogger("usbip-client")
logger.setLevel(logging.INFO)
if not logger.hasHandlers():
    handler = logging.StreamHandler()
    formatter = logging.Formatter('[%(asctime)s] %(levelname)s: %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    handler.setFormatter(formatter)
    logger.addHandler(handler)


SOCKET_HOST = 'chikaraNeko.fritz.box'
SOCKET_PORT = 65432
RECONNECT_DELAY = 5  # seconds

CLIENT_ID = socket.gethostname().strip().lower()
logger.info(f"Using hostname '{CLIENT_ID}' as client ID.")


def parse_bus_ids(usbip_output: str):
    """Extract bus IDs from usbip list output for both Linux and Windows formats."""
    bus_ids = []
    for line in usbip_output.splitlines():
        m1 = re.search(r'busid\s+([\d-]+(\.[\d-]+)*)', line)
        if m1:
            bus_ids.append(m1.group(1))
            continue
        m2 = re.match(r'\s*([\d-]+(\.[\d-]+)*)\s*:', line)
        if m2:
            bus_ids.append(m2.group(1))
    return bus_ids


def list_bound_devices():
    """Run `usbip list -r` and return all bound device bus ids."""
    try:
        result = subprocess.run(
            ["usbip", "list", "-r", SOCKET_HOST],
            capture_output=True, text=True
        )
    except FileNotFoundError:
        logger.error("`usbip` command not found. Make sure it's installed and in PATH.")
        sys.exit(1)

    if result.returncode != 0:
        logger.error(f"usbip list failed: {result.stderr.strip()}")
        return []

    return parse_bus_ids(result.stdout)


def get_attached_ports():
    """
    Get a mapping of port IDs to bus IDs for locally attached devices.
    """
    ports = {}
    try:
        result = subprocess.run(["usbip", "port"], capture_output=True, text=True, check=True)
        lines = result.stdout.splitlines()
        if "Imported USB devices" in result.stdout:
            current_port_id = None
            for line in lines:
                port_match = re.match(r'Port\s+(\d+):', line)
                if port_match:
                    current_port_id = port_match.group(1)
                    continue
                m = re.search(r'-> usbip://[^/]+/([\d-]+(\.[\d-]+)*)', line)
                if m and current_port_id:
                    bus_id = m.group(1)
                    ports[bus_id] = current_port_id
                    current_port_id = None
        else:
            for line in lines:
                m = re.search(r'port\s+(\d+):\s+<->\s+busid\s+([\d-]+(\.[\d-]+)*)', line)
                if m:
                    port_id = m.group(1)
                    bus_id = m.group(2)
                    ports[bus_id] = port_id
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass
    return ports


def attach_device(bus_id):
    """Attach to a device via USBIP."""
    logger.info(f"Attaching to {bus_id}...")
    result = subprocess.run(
        ["usbip", "attach", "-r", SOCKET_HOST, "-b", bus_id],
        capture_output=True, text=True
    )
    if result.stdout.strip():
        logger.info(result.stdout.strip())
    if result.stderr.strip():
        logger.error(result.stderr.strip())


def detach_device(bus_id):
    """Detach a device via USBIP."""
    attached_ports = get_attached_ports()
    if bus_id not in attached_ports:
        logger.info(f"Device {bus_id} is not attached.")
        return
    port_id = attached_ports[bus_id]
    logger.info(f"Detaching {bus_id} (Port {port_id})...")
    result = subprocess.run(
        ["usbip", "detach", "-p", port_id],
        capture_output=True, text=True
    )
    time.sleep(0.2)
    if result.stdout.strip():
        logger.info(result.stdout.strip())
    if result.stderr.strip():
        logger.error(result.stderr.strip())


class UsbipClient(asyncio.Protocol):
    def __init__(self, on_disconnect):
        super().__init__()
        self.transport = None
        self.on_disconnect = on_disconnect
        self.buffer = b''

    def connection_made(self, transport: WriteTransport):
        self.transport: WriteTransport = transport
        logger.info(f"Connected to {SOCKET_HOST}:{SOCKET_PORT}")
        transport.write(f"CLIENT_ID:{CLIENT_ID}\n".encode())
        transport.write(b'Client Echo\n')

    def data_received(self, data):
        self.buffer += data

        while b'\n' in self.buffer:
            line, self.buffer = self.buffer.split(b'\n', 1)
            message = line.decode().strip()

            if not message:
                continue

            logger.info(f"Data received: {message}")
            if 'bound' in message:
                parts = message.split()
                if len(parts) >= 2:
                    device_id = parts[-2]
                    logger.info(f"Binding {device_id}...")
                    attached_ports = get_attached_ports()
                    if device_id in attached_ports:
                        detach_device(device_id)
                    if device_id in list_bound_devices():
                        logger.info("Device available on server. Attaching...")
                        attach_device(device_id)
                    else:
                        logger.warning("Device not available on server or already attached elsewhere.")
            elif 'unbound' in message:
                parts = message.split()
                if len(parts) >= 2:
                    device_id = parts[-2]
                    logger.info(f"Unbinding {device_id}...")
                    detach_device(device_id)

    def connection_lost(self, exc):
        logger.warning('Connection lost, will retry...')
        self.on_disconnect()

async def main():
    while True:
        reconnect_event = asyncio.Event()

        def schedule_reconnect():
            reconnect_event.set()

        loop = asyncio.get_running_loop()
        try:
            await loop.create_connection(
                lambda: UsbipClient(on_disconnect=schedule_reconnect),
                SOCKET_HOST, SOCKET_PORT
            )
            await reconnect_event.wait()
        except (ConnectionRefusedError, OSError):
            logger.error(f"Server not available, retrying in {RECONNECT_DELAY}s...")

        await asyncio.sleep(RECONNECT_DELAY)

def run_client():
    asyncio.run(main())

if __name__ == "__main__":
    run_client()