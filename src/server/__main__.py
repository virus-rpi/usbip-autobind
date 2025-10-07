import asyncio

from .web_server import WebServer
from .assignment_manager import AssignmentManager
from .client_manager import ClientManager
from .device_manager import DeviceManager
from .tcp_server import TcpServer
from . import ASSIGNMENTS_FILE, PHYSICAL_PORTS, SOCKET_HOST, SOCKET_PORT, dispatcher, logger, WEB_HOST, WEB_PORT


async def main():
    main_loop = asyncio.get_event_loop()

    assignment_manager = AssignmentManager(ASSIGNMENTS_FILE)
    device_manager = DeviceManager(PHYSICAL_PORTS, main_loop, assignment_manager)
    client_manager = ClientManager(device_manager, assignment_manager)
    tcp_server = TcpServer(SOCKET_HOST, SOCKET_PORT, client_manager)

    device_manager.scan_existing_devices()
    device_manager.start_monitoring()
    socket_task = await tcp_server.start_server()

    dispatcher.subscribe("webui_start", lambda: logger.info("Application starting up..."))
    web_server = WebServer(WEB_HOST, WEB_PORT, device_manager, assignment_manager, client_manager)
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
