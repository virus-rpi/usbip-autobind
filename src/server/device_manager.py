import asyncio
import logging
import os
import subprocess
import time
from asyncio import AbstractEventLoop

from pyudev import Context, Monitor, MonitorObserver

from . import dispatcher
from .assignment_manager import AssignmentManager


def get_device_name(bus_id):
    """Try to read the product name from sysfs."""
    path = f"/sys/bus/usb/devices/{bus_id}/product"
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return f.read().strip()
        except (OSError, PermissionError):
            return bus_id
    return bus_id


class DeviceManager:
    def __init__(self, physical_ports, main_loop: AbstractEventLoop, assignment_manager: AssignmentManager):
        self.physical_ports = physical_ports
        self.main_loop = main_loop
        self.assignment_manager = assignment_manager
        self.device_bind_set = set()
        self.device_names: dict[str, str] = {}  # bus_id -> device name
        self.device_in_use: dict[str, str] = {}  # bus_id -> client_id currently using it
        self.logger = logging.getLogger("usbip-host-autobind")
        self.context = Context()
        self.monitor = Monitor.from_netlink(self.context)
        self.monitor.filter_by(subsystem='usb')
        self.observer = MonitorObserver(self.monitor, callback=self.handle_device_event)

        dispatcher.subscribe("webui_end", self.cleanup)

    def start_monitoring(self):
        self.observer.start()

    def stop_monitoring(self):
        self.observer.stop()

    def unbind_current_driver(self, bus_id):
        driver_path = f"/sys/bus/usb/devices/{bus_id}/driver"
        if os.path.islink(driver_path):
            driver_name = os.path.basename(os.readlink(driver_path))
            try:
                with open(f"/sys/bus/usb/drivers/{driver_name}/unbind", "w") as f:
                    f.write(bus_id)
                self.logger.info(f"Unbound {bus_id} from {driver_name}")
            except subprocess.CalledProcessError as e:
                self.logger.warning(f"Failed to unbind {bus_id} from {driver_name}: {e}")
        else:
            self.logger.info(f"No driver bound for {bus_id}")

    def usbip_bind(self, bus_id):
        driver_path = f"/sys/bus/usb/devices/{bus_id}/driver"
        if os.path.islink(driver_path) and os.path.basename(os.readlink(driver_path)) == 'usbip-host':
            self.logger.info(f"Already bound {bus_id} to usbip-host")
            return True
        try:
            subprocess.run(["usbip", "bind", "-b", bus_id], capture_output=True, text=True, check=True)
            self.logger.info(f"Bound {bus_id} to usbip-host")
            return True
        except subprocess.CalledProcessError as e:
            self.logger.warning(f"usbip bind failed for {bus_id}: {e.stderr.strip() or e.stdout.strip()}")
            return False
        except FileNotFoundError:
            self.logger.error("usbip command not found. Is the usbip-tools package installed?")
            return False

    def usbip_unbind(self, bus_id):
        res = subprocess.run(["usbip", "unbind", "-b", bus_id], capture_output=True, text=True)
        if res.returncode != 0:
            self.logger.info(f"usbip unbind for {bus_id}: {res.stderr.strip() or res.stdout.strip()}")

    def ensure_bound(self, bus_id):
        if bus_id in self.device_bind_set:
            return
        if self.usbip_bind(bus_id):
            self.device_bind_set.add(bus_id)
            self.device_names[bus_id] = get_device_name(bus_id)

    async def force_free(self, bus_id):
        prev = self.device_in_use.pop(bus_id, None)
        if prev:
            self.logger.info(f"Forcing {bus_id} free from client {prev}")
            await dispatcher.emit("force_free", (bus_id, prev))
        self.usbip_unbind(bus_id)
        time.sleep(0.2)
        if self.usbip_bind(bus_id):
            self.device_bind_set.add(bus_id)
            self.device_names[bus_id] = get_device_name(bus_id)
        else:
            self.device_bind_set.discard(bus_id)

    def scan_existing_devices(self):
        self.logger.info("Scanning for already connected devices...")
        try:
            entries = os.listdir("/sys/bus/usb/devices")
        except FileNotFoundError:
            self.logger.warning("USB sysfs not found; is this Linux with USBIP installed?")
            return
        for dev in entries:
            if ':' in dev:  # skip interfaces
                continue
            if any(dev.startswith(port) for port in self.physical_ports):
                self.logger.info(f"Found existing device on {dev}, ensuring bound...")
                self.ensure_bound(dev)
                self.main_loop.call_soon_threadsafe(asyncio.create_task, self.notify_bound_to_assigned(dev))

    async def notify_bound_to_assigned(self, bus_id):
        result = await dispatcher.emit("device_added", bus_id)
        if result:
            target = self.assignment_manager.device_assignments.get(bus_id)
            self.device_in_use[bus_id] = target
            self.logger.info(f"Notified {target} to attach {bus_id} (marked in use).")

    def handle_device_event(self, device):
        device_path = device.device_path
        action = device.action
        if ':' in device_path:
            return
        bus_id = os.path.basename(device_path)
        if not any(bus_id.startswith(port) for port in self.physical_ports):
            return
        self.logger.info(f"Device event: {device_path} {action}")
        if action == 'add':
            self.logger.info(f"New device on {bus_id}: binding...")
            self.ensure_bound(bus_id)
            self.main_loop.call_soon_threadsafe(asyncio.create_task, self.notify_bound_to_assigned(bus_id))
            self.main_loop.call_soon_threadsafe(asyncio.create_task, dispatcher.emit("updated", bus_id))
        elif action == 'remove':
            if bus_id in self.device_bind_set:
                self.logger.info(f"Device {bus_id} removed")
                self.device_bind_set.discard(bus_id)
            self.device_names.pop(bus_id, None)
            self.device_in_use.pop(bus_id, None)
            self.main_loop.call_soon_threadsafe(asyncio.create_task, dispatcher.emit("device_removed", bus_id))
            self.main_loop.call_soon_threadsafe(asyncio.create_task, dispatcher.emit("updated", bus_id))

    def cleanup(self):
        self.logger.info("Starting cleanup: unbinding all devices...")
        self.stop_monitoring()
        for bus_id in list(self.device_bind_set):
            self.usbip_unbind(bus_id)
            self.device_bind_set.discard(bus_id)
        self.logger.info("Cleanup complete.")

    def mark_device_in_use(self, bus_id, client_id):
        self.device_in_use[bus_id] = client_id
        self.logger.info(f"Marked {bus_id} in use by {client_id}")

    def free_device(self, bus_id):
        self.device_in_use.pop(bus_id, None)
        self.logger.info(f"Freed device {bus_id}")

    def get_device_in_use(self):
        return dict(self.device_in_use)

    def is_device_in_use(self, bus_id):
        return self.device_in_use.get(bus_id, "none") != "none"
