import logging
import os

from .events import EventDispatcher

SOCKET_HOST = '0.0.0.0'
SOCKET_PORT = 65432
WEB_HOST = '0.0.0.0'
WEB_PORT = 8080
PHYSICAL_PORTS = ["1-1", "3-1", "1-2", "3-2"]
ASSIGNMENTS_FILE = os.path.join(os.path.dirname(__file__), "assignments.json")

logger = logging.getLogger("usbip-host-autobind")
logger.setLevel(logging.INFO)
if not logger.hasHandlers():
    handler = logging.StreamHandler()
    formatter = logging.Formatter('[%(asctime)s] %(levelname)s: %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    handler.setFormatter(formatter)
    logger.addHandler(handler)

dispatcher = EventDispatcher()
