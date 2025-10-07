import asyncio
import argparse

from .web_server import WebServer
from .assignment_manager import AssignmentManager
from .client_manager import ClientManager
from .device_manager import DeviceManager
from .tcp_server import TcpServer
from . import ASSIGNMENTS_FILE, PHYSICAL_PORTS, SOCKET_HOST, SOCKET_PORT, dispatcher, logger, WEB_HOST, WEB_PORT


def parse_args():
    parser = argparse.ArgumentParser(description="USBIP Autobind Server")
    parser.add_argument('--socket-host', type=str, default=SOCKET_HOST, help='Host for TCP server')
    parser.add_argument('--socket-port', type=int, default=SOCKET_PORT, help='Port for TCP server')
    parser.add_argument('--web-host', type=str, default=WEB_HOST, help='Host for web server')
    parser.add_argument('--web-port', type=int, default=WEB_PORT, help='Port for web server')
    parser.add_argument('--physical-ports', type=str, default=','.join(PHYSICAL_PORTS), help='Comma-separated list of physical ports')
    parser.add_argument('--assignments-file', type=str, default=ASSIGNMENTS_FILE, help='Path to assignments file')
    return parser.parse_args()


async def main():
    args = parse_args()
    main_loop = asyncio.get_event_loop()

    assignment_manager = AssignmentManager(args.assignments_file)
    device_manager = DeviceManager(args.physical_ports.split(','), main_loop, assignment_manager)
    client_manager = ClientManager(device_manager, assignment_manager)
    tcp_server = TcpServer(args.socket_host, args.socket_port, client_manager)

    device_manager.scan_existing_devices()
    device_manager.start_monitoring()
    socket_task = await tcp_server.start_server()

    dispatcher.subscribe("webui_start", lambda: logger.info("Application starting up..."))
    web_server = WebServer(args.web_host, args.web_port, device_manager, assignment_manager, client_manager)
    await web_server.run()
    socket_task.cancel()
    await asyncio.gather(socket_task, return_exceptions=True)

    print("Managers initialized. Ready to start servers.")


def run_server():
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Script interrupted by user.")
        exit(0)
    except SystemExit:
        print("Script exiting.")
        exit(0)


if __name__ == "__main__":
    run_server()
