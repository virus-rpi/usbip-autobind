import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Path, Body
from starlette.responses import JSONResponse

from . import dispatcher
from .assignment_manager import AssignmentManager
from .client_manager import ClientManager
from .device_manager import DeviceManager
from .webui import run as run_webui


@asynccontextmanager
async def lifespan(_: FastAPI):
    """
    Handles startup and shutdown events for the FastAPI application.
    """
    await dispatcher.emit("webui_start")
    yield
    await dispatcher.emit("webui_end")

app = FastAPI(lifespan=lifespan)

device_manager: DeviceManager = None
assignment_manager: AssignmentManager = None
client_manager: ClientManager = None

@app.post("/devices/{bus_id}/assign")
async def assign_device(bus_id: str = Path(...), body: dict = Body(...)):
    client_id = body.get("client_id")
    if bus_id not in device_manager.device_bind_set:
        device_manager.ensure_bound(bus_id)
    current = device_manager.device_in_use.get(bus_id)
    if current == client_id:
        assignment_manager.device_assignments[bus_id] = client_id
        return JSONResponse({"status": "already-in-use"})
    if current and current != client_id:
        await device_manager.force_free(bus_id)
    if client_id == "none":
        device_manager.free_device(bus_id)
        assignment_manager.remove_assignment(bus_id)
        return JSONResponse({"status": "unassigned"})
    assignment_manager.device_assignments[bus_id] = client_id
    delivered = await client_manager.send_to_client(client_id, f"Device {bus_id} bound\n")
    if delivered:
        device_manager.device_in_use[bus_id] = client_id
        return JSONResponse({"status": "assigned"})
    else:
        device_manager.device_in_use.pop(bus_id, None)
        return JSONResponse({"status": "queued-for-client"})

@app.post("/devices/{bus_id}/force_free")
async def force_free_device(bus_id: str = Path(...)):
    if bus_id not in device_manager.device_bind_set:
        return JSONResponse({"status": "not-exported"})
    await device_manager.force_free(bus_id)
    device_manager.device_in_use.pop(bus_id, None)
    return JSONResponse({"status": "freed"})

@app.post("/devices/{bus_id}/force_reattach")
async def force_reattach_device(bus_id: str = Path(...)):
    if bus_id not in device_manager.device_bind_set:
        return JSONResponse({"status": "not-exported"})
    await device_manager.force_free(bus_id)
    await device_manager.notify_bound_to_assigned(bus_id)
    return JSONResponse({"status": "reattached"})

@app.get("/devices")
async def list_devices():
    devices = []
    for bus_id in device_manager.device_bind_set:
        devices.append({
            "bus_id": bus_id,
            "assigned_to": assignment_manager.device_assignments.get(bus_id),
            "in_use": device_manager.device_in_use.get(bus_id),
            "name": device_manager.device_names.get(bus_id, "Unknown Device")
        })
    return JSONResponse({"devices": devices})

@app.get("/devices/{bus_id}")
async def get_device(bus_id: str = Path(...)):
    device = {
        "bus_id": bus_id,
        "assigned_to": assignment_manager.device_assignments.get(bus_id),
        "in_use": device_manager.device_in_use.get(bus_id)
    }
    return JSONResponse(device)

@app.post("/assign_all")
async def assign_all(body: dict = Body(...)):
    client_id = body.get("client_id")
    if client_id == "none":
        assignment_manager.assign_all_client_id = "none"
        for bus_id in list(assignment_manager.device_assignments.keys()):
            await device_manager.force_free(bus_id)
            assignment_manager.device_assignments.pop(bus_id, None)
            device_manager.device_in_use.pop(bus_id, None)
        return JSONResponse({"status": "cleared"})
    assignment_manager.assign_all_client_id = client_id
    for bus_id in list(device_manager.device_bind_set):
        if bus_id in assignment_manager.device_assignments and assignment_manager.device_assignments[bus_id] != client_id:
            await device_manager.force_free(bus_id)
    for bus_id in list(device_manager.device_bind_set):
        assignment_manager.device_assignments[bus_id] = client_id
        await client_manager.send_to_client(client_id, f"Device {bus_id} bound\n")
        device_manager.device_in_use[bus_id] = client_id
    return JSONResponse({"status": "assigned", "client_id": client_id})

@app.get("/clients")
async def list_clients():
    clients = list(client_manager.clients.keys())
    return JSONResponse({"clients": clients})

@app.get("/debug")
async def debug():
    debug_info = {
        "device_assignments": assignment_manager.device_assignments,
        "device_in_use": device_manager.device_in_use,
        "device_bind_set": list(device_manager.device_bind_set),
        "clients": list(client_manager.clients.keys()),
        "assign_all_client_id": getattr(assignment_manager, "assign_all_client_id", None)
    }
    return JSONResponse(debug_info)

class WebServer:
    def __init__(self, host, port, device_manager_: DeviceManager, assignment_manager_: AssignmentManager, client_manager_: ClientManager):
        global device_manager, assignment_manager, client_manager
        self.logger = logging.getLogger("usbip-host-autobind")
        self.host = host
        self.port = port
        device_manager = device_manager_  # set global for route handlers
        assignment_manager = assignment_manager_  # set global for route handlers
        client_manager = client_manager_  # set global for route handlers

    async def run(self):
        run_webui(app)
        config = uvicorn.Config(app, host=self.host, port=self.port, log_level="info")
        server = uvicorn.Server(config)
        # noinspection HttpUrlsUsage
        self.logger.info(f"Web UI available at http://{self.host}:8081/")
        # noinspection HttpUrlsUsage
        self.logger.info(f"API available at http://{self.host}:{self.port}")
        await server.serve()