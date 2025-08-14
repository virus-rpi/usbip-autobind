#!/usr/bin/env python3
import asyncio
import subprocess
import re
import sys

SOCKET_HOST = 'chikaraNeko.fritz.box'
SOCKET_PORT = 65432
RECONNECT_DELAY = 5  # seconds


def parse_busids(usbip_output: str):
    """Extract bus IDs from usbip list output for both Linux and Windows formats."""
    busids = []
    for line in usbip_output.splitlines():
        m1 = re.search(r'busid\s+([\d-]+)', line)
        if m1:
            busids.append(m1.group(1))
            continue
        m2 = re.match(r'\s*([\d-]+)\s*:', line)
        if m2:
            busids.append(m2.group(1))
    return busids


def list_bound_devices():
    """Run `usbip list -r` and return all bound device busids."""
    try:
        result = subprocess.run(
            ["usbip", "list", "-r", SOCKET_HOST],
            capture_output=True, text=True
        )
    except FileNotFoundError:
        print("Error: `usbip` command not found. Make sure it's installed and in PATH.")
        sys.exit(1)

    if result.returncode != 0:
        print("usbip list failed:", result.stderr.strip())
        return []

    return parse_busids(result.stdout)


def attach_device(busid):
    """Attach to a device via USBIP."""
    print(f"Attaching to {busid}...")
    result = subprocess.run(
        ["usbip", "attach", "-r", SOCKET_HOST, "-b", busid],
        capture_output=True, text=True
    )
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.stderr.strip():
        print(result.stderr.strip())


class UsbipClient(asyncio.Protocol):
    def __init__(self, on_disconnect):
        super().__init__()
        self.transport = None
        self.on_disconnect = on_disconnect

    def connection_made(self, transport):
        self.transport = transport
        print(f"Connected to {SOCKET_HOST}:{SOCKET_PORT}")
        transport.write(b"CLIENT_ID:raion\n")
        transport.write(b'Client Echo')

    def data_received(self, data):
        message = data.decode().strip()
        print(f"Data received: {message}")
        if 'binded' in message:
            parts = message.split()
            if len(parts) >= 2:
                deviceId = parts[-2]
                print(f"Newly bound device: {deviceId}")
                if deviceId in list_bound_devices():
                    attach_device(deviceId)

    def connection_lost(self, exc):
        print('Connection lost, will retry...')
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
            print(f"Server not available, retrying in {RECONNECT_DELAY}s...")

        await asyncio.sleep(RECONNECT_DELAY)


if __name__ == "__main__":
    asyncio.run(main())