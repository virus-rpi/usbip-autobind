import asyncio
import logging

from . import dispatcher
from .assignment_manager import AssignmentManager
from .device_manager import DeviceManager


class ClientManager:
    def __init__(self, device_manager: DeviceManager, assignment_manager: AssignmentManager):
        self.logger = logging.getLogger("usbip-host-autobind")
        self.clients: dict[str, asyncio.StreamWriter] = {}  # client_id -> writer
        self.writer_to_id: dict[asyncio.StreamWriter, str] = {}  # writer -> client_id
        self.device_manager: DeviceManager = device_manager
        self.assignment_manager: AssignmentManager = assignment_manager

        dispatcher.subscribe("force_free", self.force_free)
        dispatcher.subscribe("device_added", self.device_added)
        dispatcher.subscribe("device_removed", self.device_removed)

    async def register_client(self, client_id, writer):
        self.clients[client_id] = writer
        self.writer_to_id[writer] = client_id
        self.logger.info(f"Registered client ID: {client_id}")

        for bus_id in sorted(self.device_manager.device_bind_set):
            if self.assignment_manager.get_assignment(bus_id) == client_id and not self.device_manager.is_device_in_use(
                    bus_id):
                try:
                    writer.write(f"Device {bus_id} bound\n".encode())
                    self.device_manager.mark_device_in_use(bus_id, client_id)
                    await writer.drain()
                    self.logger.info(f"Assigned {bus_id} to {client_id}")
                except (ConnectionResetError, OSError):
                    self.device_manager.free_device(bus_id)
                    self.logger.info(
                        f"Could not assign {bus_id} to {client_id} (the client probably disconnected unexpectedly)")
        if not self.assignment_manager.assign_all_client_id:
            for bus_id in sorted(self.device_manager.device_bind_set):
                if bus_id not in self.assignment_manager.device_assignments:
                    self.assignment_manager.set_assignment(bus_id, client_id)
                    try:
                        writer.write(f"Device {bus_id} bound\n".encode())
                        self.device_manager.mark_device_in_use(bus_id, client_id)
                        await writer.drain()
                        self.logger.info(f"Auto-assigned {bus_id} to {client_id} (new client)")
                    except (ConnectionResetError, OSError):
                        self.assignment_manager.remove_assignment(bus_id)
                        self.device_manager.free_device(bus_id)
                        self.logger.info(
                            f"Could not auto-assign {bus_id} to {client_id} (the client probably disconnected unexpectedly)")

        try:
            await writer.drain()
        except (ConnectionResetError, OSError):
            pass

    def unregister_client(self, client_id):
        freed = [b for b, cid in list(self.device_manager.device_in_use.items()) if cid == client_id]
        for b in freed:
            self.device_manager.free_device(b)
        writer = self.clients.pop(client_id, None)
        if writer:
            self.writer_to_id.pop(writer, None)
            try:
                writer.close()
            except Exception as e:
                self.logger.warning(f"Failed to close writer for client {client_id}: {e}")
        self.logger.info(f"Unregistered client ID: {client_id}")

    async def send_to_client(self, client_id, message):
        writer = self.clients.get(client_id)
        if not writer:
            self.logger.info(f"Client {client_id} not connected (cannot send '{message.strip()}').")
            return False
        try:
            writer.write(message.encode())
            await writer.drain()
            return True
        except (ConnectionResetError, asyncio.IncompleteReadError, OSError) as e:
            self.logger.warning(f"Send to {client_id} failed: {e}")
            self.unregister_client(client_id)
            return False

    def get_connected_clients(self):
        return list(self.clients.keys())

    def force_free(self, data):
        bus_id, client_id = data
        return self.send_to_client(client_id, f"Device {bus_id} unbound\n")

    async def notify_bound_to_assigned(self, bus_id):
        target = self.assignment_manager.device_assignments.get(bus_id)
        if not target or target == "none":
            return False
        return await self.send_to_client(target, f"Device {bus_id} bound\n")

    def device_removed(self, bus_id):
        for client_id in list(self.clients.keys()):
            self.send_to_client(client_id, f"Device {bus_id} removed\n")

    def device_added(self, bus_id):
        if self.assignment_manager.assign_all_client_id and self.assignment_manager.assign_all_client_id in self.clients:
            self.assignment_manager.set_assignment(bus_id, self.assignment_manager.assign_all_client_id)
        return self.notify_bound_to_assigned(bus_id)