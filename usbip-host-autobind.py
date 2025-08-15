#!/usr/bin/python3
import json
import os
import asyncio
import subprocess
import time
from typing import Dict, Set
import logging

from pyudev import Context, Monitor, MonitorObserver
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse
import uvicorn
from contextlib import asynccontextmanager

# --- Logging setup ---
logger = logging.getLogger("usbip-host-autobind")
logger.setLevel(logging.INFO)
if not logger.hasHandlers():
    handler = logging.StreamHandler()
    formatter = logging.Formatter('[%(asctime)s] %(levelname)s: %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    handler.setFormatter(formatter)
    logger.addHandler(handler)

# ------------------ Persistence support ------------------

class PersistentDict(dict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.loaded = False
    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        save_assignments()
    def __delitem__(self, key):
        super().__delitem__(key)
        save_assignments()
    def update(self, *args, **kwargs):
        if args:
            super().update(args[0], **kwargs)
        else:
            super().update(**kwargs)
        save_assignments()
    def pop(self, *args, **kwargs):
        result = super().pop(*args, **kwargs)
        save_assignments()
        return result
    def clear(self):
        super().clear()
        save_assignments()


# --- Network & Web config ---
SOCKET_HOST = '0.0.0.0'
SOCKET_PORT = 65432
WEB_HOST = '0.0.0.0'
WEB_PORT = 8080

# --- USB ports to watch (adjust with `lsusb -t` if needed) ---
PHYSICAL_PORTS = ["1-1", "3-1", "1-2", "3-2"]

ASSIGNMENTS_FILE = os.path.join(os.path.dirname(__file__), "assignments.json")

# --- State ---
deviceBindSet: Set[str] = set()  # Devices currently bound to usbip-host (exported)
CLIENTS: Dict[str, asyncio.StreamWriter] = {}  # client_id -> writer
WRITER_TO_ID: Dict[asyncio.StreamWriter, str] = {}
DEVICE_ASSIGNMENTS: Dict[str, str] = PersistentDict()  # busid -> target client_id (desired owner)
DEVICE_IN_USE: Dict[str, str] = {}  # busid -> client_id currently using it
DEVICE_NAMES: Dict[str, str] = {}  # busid -> device name
ASSIGN_ALL_CLIENT_ID: str = "none"  # If set, all devices are assigned to this client

def save_assignments():
    try:
        tmpfile = ASSIGNMENTS_FILE + ".tmp"
        with open(tmpfile, "w") as f:
            json.dump({
                "assign_all_client_id": ASSIGN_ALL_CLIENT_ID,
                "device_assignments": DEVICE_ASSIGNMENTS
            }, f)
        os.replace(tmpfile, ASSIGNMENTS_FILE)
    except Exception as e:
        logger.warning(f"Failed to save assignments: {e}")

def load_assignments():
    global ASSIGN_ALL_CLIENT_ID, DEVICE_ASSIGNMENTS
    try:
        with open(ASSIGNMENTS_FILE, "r") as f:
            data = json.load(f)
            ASSIGN_ALL_CLIENT_ID = data.get("assign_all_client_id")
            DEVICE_ASSIGNMENTS.clear()
            DEVICE_ASSIGNMENTS.update(data.get("device_assignments", {}))
        logger.info(f"Loaded assignments from {ASSIGNMENTS_FILE}")
    except FileNotFoundError:
        pass
    except Exception as e:
        logger.warning(f"Failed to load assignments: {e}")

# --- asyncio loop reference ---
main_loop = asyncio.get_event_loop()

# --- udev monitor setup ---
context = Context()
monitor = Monitor.from_netlink(context)
monitor.filter_by(subsystem='usb')


# ------------------ USB helpers ------------------

def get_device_name(busid: str) -> str:
    """Try to read product name from sysfs."""
    path = f"/sys/bus/usb/devices/{busid}/product"
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return f.read().strip()
        except (OSError, PermissionError):
            return busid
    return busid


def unbind_current_driver(busid: str):
    driver_path = f"/sys/bus/usb/devices/{busid}/driver"
    if os.path.islink(driver_path):
        driver_name = os.path.basename(os.readlink(driver_path))
        try:
            with open(f"/sys/bus/usb/drivers/{driver_name}/unbind", "w") as f:
                f.write(busid)
            logger.info(f"Unbound {busid} from {driver_name}")
        except subprocess.CalledProcessError as e:
            logger.warning(f"Failed to unbind {busid} from {driver_name}: {e}")
    else:
        logger.info(f"No driver bound for {busid}")


def usbip_bind(busid: str) -> bool:
    driver_path = f"/sys/bus/usb/devices/{busid}/driver"
    if os.path.islink(driver_path) and os.path.basename(os.readlink(driver_path)) == 'usbip-host':
        logger.info(f"Already bound {busid} to usbip-host")
        return True
    try:
        subprocess.run(["usbip", "bind", "-b", busid], capture_output=True, text=True, check=True)
        logger.info(f"Bound {busid} to usbip-host")
        return True
    except subprocess.CalledProcessError as e:
        logger.warning(f"usbip bind failed for {busid}: {e.stderr.strip() or e.stdout.strip()}")
        return False
    except FileNotFoundError:
        logger.error("usbip command not found. Is the usbip-tools package installed?")
        return False


def usbip_unbind(busid: str):
    res = subprocess.run(["usbip", "unbind", "-b", busid], capture_output=True, text=True)
    if res.returncode != 0:
        logger.info(f"usbip unbind for {busid}: {res.stderr.strip() or res.stdout.strip()}")


def ensure_bound(busid: str):
    if busid in deviceBindSet:
        return
    if usbip_bind(busid):
        deviceBindSet.add(busid)
        DEVICE_NAMES[busid] = get_device_name(busid)


def force_free(busid: str):
    prev = DEVICE_IN_USE.pop(busid, None)
    if prev:
        logger.info(f"Forcing {busid} free from client {prev}")
        main_loop.call_soon_threadsafe(asyncio.create_task, send_to_client(prev, f"Device {busid} unbound\n"))
    usbip_unbind(busid)
    time.sleep(0.2)
    if usbip_bind(busid):
        deviceBindSet.add(busid)
        DEVICE_NAMES[busid] = get_device_name(busid)
    else:
        deviceBindSet.discard(busid)


# ------------------ Socket helpers ------------------

async def send_to_client(client_id: str, message: str) -> bool:
    writer = CLIENTS.get(client_id)
    if not writer:
        logger.info(f"Client {client_id} not connected (cannot send '{message.strip()}').")
        return False
    try:
        writer.write(message.encode())
        await writer.drain()
        return True
    except (ConnectionResetError, asyncio.IncompleteReadError, OSError) as e:
        logger.warning(f"Send to {client_id} failed: {e}")
        try:
            writer.close()
        except OSError:
            pass
        CLIENTS.pop(client_id, None)
        WRITER_TO_ID.pop(writer, None)
        return False


async def notify_bound_to_assigned(busid: str):
    target = DEVICE_ASSIGNMENTS.get(busid)
    if not target or target == "none":
        return
    delivered = await send_to_client(target, f"Device {busid} binded\n")
    if delivered:
        DEVICE_IN_USE[busid] = target
        logger.info(f"Notified {target} to attach {busid} (marked in use).")


# ------------------ Binding logic entrypoints ------------------

def scan_existing_devices():
    logger.info("Scanning for already connected devices...")
    try:
        entries = os.listdir("/sys/bus/usb/devices")
    except FileNotFoundError:
        logger.warning("USB sysfs not found; is this Linux with USBIP installed?")
        return
    for dev in entries:
        if ':' in dev: # skip interfaces
            continue
        if any(dev.startswith(port) for port in PHYSICAL_PORTS):
            logger.info(f"Found existing device on {dev}, ensuring bound and notifying assignment...")
            ensure_bound(dev)
            main_loop.call_soon_threadsafe(asyncio.create_task, notify_bound_to_assigned(dev))


def print_device_event(device):
    device_path = device.device_path
    action = device.action
    if ':' in device_path:
        return
    busid = os.path.basename(device_path)

    if not any(busid.startswith(port) for port in PHYSICAL_PORTS):
        return

    logger.info(f"Device event: {device_path} {action}")

    if action == 'add':
        logger.info(f"New device on {busid}: binding & notifying...")
        ensure_bound(busid)
        if ASSIGN_ALL_CLIENT_ID and ASSIGN_ALL_CLIENT_ID in CLIENTS:
            DEVICE_ASSIGNMENTS[busid] = ASSIGN_ALL_CLIENT_ID
            main_loop.call_soon_threadsafe(lambda: asyncio.create_task(notify_bound_to_assigned(busid)))
        else:
            main_loop.call_soon_threadsafe(lambda: asyncio.create_task(notify_bound_to_assigned(busid)))
    elif action == 'remove':
        if busid in deviceBindSet:
            logger.info(f"Device {busid} removed")
            deviceBindSet.discard(busid)
        DEVICE_ASSIGNMENTS.pop(busid, None)
        DEVICE_IN_USE.pop(busid, None)
        for cid in list(CLIENTS.keys()):
            main_loop.call_soon_threadsafe(asyncio.create_task, send_to_client(cid, f"Device {busid} removed\n"))

def cleanup():
    """Unbind all exported USBIP devices."""
    logger.info("Starting cleanup: unbinding all devices...")
    for busid in list(deviceBindSet):
        usbip_unbind(busid)
        deviceBindSet.discard(busid)
    logger.info("Cleanup complete.")

observer = MonitorObserver(monitor, callback=print_device_event)
observer.start()


# ------------------ TCP Server ------------------

async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    peer = writer.get_extra_info('peername')
    logger.info(f"Client connected from {peer}")

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

    CLIENTS[client_id] = writer
    WRITER_TO_ID[writer] = client_id
    logger.info(f"Registered client ID: {client_id}")

    for busid in sorted(deviceBindSet):
        if DEVICE_ASSIGNMENTS.get(busid) == client_id and not DEVICE_IN_USE.get(busid):
            try:
                writer.write(f"Device {busid} binded\n".encode())
                DEVICE_IN_USE[busid] = client_id
                await writer.drain()
                logger.info(f"Assigned {busid} to {client_id}")
            except (ConnectionResetError, OSError):
                pass
    if not ASSIGN_ALL_CLIENT_ID:
        for busid in sorted(deviceBindSet):
            if busid not in DEVICE_ASSIGNMENTS:
                DEVICE_ASSIGNMENTS[busid] = client_id
                try:
                    writer.write(f"Device {busid} binded\n".encode())
                    DEVICE_IN_USE[busid] = client_id
                    await writer.drain()
                    logger.info(f"Auto-assigned {busid} to {client_id} (new client)")
                except (ConnectionResetError, OSError):
                    pass
    try:
        await writer.drain()
    except (ConnectionResetError, OSError):
        pass

    try:
        while True:
            data = await reader.read(256)
            if not data:
                logger.info(f"Client disconnected: {client_id}")
                break
    except (ConnectionResetError, asyncio.IncompleteReadError):
        logger.info(f"Client connection reset: {client_id}")
    finally:
        freed = [b for b, cid in list(DEVICE_IN_USE.items()) if cid == client_id]
        for b in freed:
            DEVICE_IN_USE.pop(b, None)
            logger.info(f"Freed {b} (client {client_id} disconnected)")
        try:
            writer.close()
        except OSError:
            pass
        CLIENTS.pop(client_id, None)
        WRITER_TO_ID.pop(writer, None)


async def run_socket_server():
    server = await asyncio.start_server(handle_client, SOCKET_HOST, SOCKET_PORT)
    logger.info(f"USBIP control socket listening on {SOCKET_HOST}:{SOCKET_PORT}")
    return server


# ------------------ Lifespan event handler ------------------

@asynccontextmanager
async def lifespan(_: FastAPI):
    """
    Handles startup and shutdown events for the FastAPI application.
    """
    logger.info("Application starting up...")

    yield

    logger.info("Application shutting down...")
    observer.stop()
    cleanup()
    logger.info("Shutdown complete.")

# ------------------ Web UI ------------------

app = FastAPI(lifespan=lifespan)


@app.get("/", response_class=HTMLResponse)
async def index():
    client_list = "".join(
        f"<li><code>{cid}</code></li>" for cid in sorted(CLIENTS.keys())
    )

    def device_row(busid: str) -> str:
        assigned = DEVICE_ASSIGNMENTS.get(busid, "none")
        in_use = DEVICE_IN_USE.get(busid)
        name = DEVICE_NAMES.get(busid, busid)
        opts = [f"<option value='none' {'selected' if assigned == 'none' else ''}>none</option>"]
        for cid in sorted(CLIENTS.keys()):
            selected = "selected" if cid == assigned else ""
            opts.append(f"<option value='{cid}' {selected}>{cid}</option>")
        options_html = "".join(opts)
        status = f"in use by <b>{in_use}</b>" if in_use else "free"
        return (
            f"<tr>"
            f"<td><code>{busid}</code> ({name})</td>"
            f"<td>{status}</td>"
            f"<td>"
            f"<select onchange='assign(\"{busid}\", this.value)' {'' if CLIENTS else 'disabled'}>"
            f"{options_html}"
            f"</select>"
            f"</td>"
            f"<td>"
            f"<button onclick='forceFree(\"{busid}\")'>Force free</button>"
            f"<button onclick='forceReattach(\"{busid}\")'>Force reattach</button>"
            f"</td>"
            f"</tr>"
        )

    device_rows = "".join(device_row(b) for b in sorted(deviceBindSet)) or "<tr><td colspan='4'>(no devices)</td></tr>"

    debug_output = f"""
        <h2>Debugging State</h2>
        <pre>
    **deviceBindSet**: {sorted(list(deviceBindSet))}

    **CLIENTS**:
    {json.dumps(list(CLIENTS.keys()), indent=2)}

    **DEVICE_ASSIGNMENTS**:
    {json.dumps(DEVICE_ASSIGNMENTS, indent=2)}

    **DEVICE_IN_USE**:
    {json.dumps(DEVICE_IN_USE, indent=2)}

    **DEVICE_NAMES**:
    {json.dumps(DEVICE_NAMES, indent=2)}
        </pre>
        """

    assign_all_controls = ""
    if CLIENTS:
        options = []
        selected_none = 'selected' if not ASSIGN_ALL_CLIENT_ID else ''
        options.append(f'<option value="none" {selected_none}>none</option>')
        for cid in sorted(CLIENTS.keys()):
            selected = 'selected' if ASSIGN_ALL_CLIENT_ID == cid else ''
            options.append(f'<option value="{cid}" {selected}>{cid}</option>')
        options_html = ''.join(options)
        assign_all_controls = f'''
        <h3>Assign All Devices</h3>
        <select id="assignAllClient">
            {options_html}
        </select>
        <button onclick="assignAll()">Assign All</button>
        <span style='margin-left:10px;color:#888;'>{'Current: ' + (ASSIGN_ALL_CLIENT_ID or 'none')}</span>
        '''

    html = f"""
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>USBIP Device Manager</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 24px; }}
table {{ border-collapse: collapse; width: 100%; max-width: 900px; }}
th, td {{ border: 1px solid #ddd; padding: 8px; }}
th {{ background: #f6f6f6; text-align: left; }}
code {{ background: #f3f3f3; padding: 2px 4px; border-radius: 4px; }}
button {{ padding: 6px 10px; }}
select {{ padding: 4px; }}
.badge {{ display:inline-block; padding:2px 6px; border-radius:10px; background:#eee; }}
</style>
</head>
<body>
<h1>USBIP Device Manager</h1>

{assign_all_controls}

<h2>Connected Clients <span class="badge">{len(CLIENTS)}</span></h2>
<ul>{client_list or "<li>(none)</li>"}</ul>

<h2>Exported Devices <span class="badge">{len(deviceBindSet)}</span></h2>
<table>
<thead><tr><th>Bus ID (Name)</th><th>Status</th><th>Assign to client</th><th>Actions</th></tr></thead>
<tbody>{device_rows}</tbody>
</table>

{debug_output}

<script>
async function assign(busid, client_id){{
  const r = await fetch(`/assign?busid=${{encodeURIComponent(busid)}}&client_id=${{encodeURIComponent(client_id)}}`);
  if(!r.ok) alert('Assign failed');
  location.reload();
}}
async function forceFree(busid){{
  const r = await fetch(`/force_free?busid=${{encodeURIComponent(busid)}}`);
  if(!r.ok) alert('Force free failed');
  location.reload();
}}
async function forceReattach(busid){{
  const r = await fetch(`/force_reattach?busid=${{encodeURIComponent(busid)}}`);
  if(!r.ok) alert('Force reattach failed');
  location.reload();
}}
async function assignAll(){{
  const client_id = document.getElementById('assignAllClient').value;
  const r = await fetch(`/assign_all?client_id=${{encodeURIComponent(client_id)}}`);
  if(!r.ok) alert('Assign all failed');
  location.reload();
}}
</script>
</body>
</html>
"""
    return HTMLResponse(html)


@app.get("/assign")
async def assign(busid: str = Query(...), client_id: str = Query(...)):
    if busid not in deviceBindSet:
        ensure_bound(busid)
    current = DEVICE_IN_USE.get(busid)
    if current == client_id:
        DEVICE_ASSIGNMENTS[busid] = client_id
        return JSONResponse({"status": "already-in-use"})
    if current and current != client_id:
        force_free(busid)
    if client_id == "none":
        DEVICE_IN_USE.pop(busid, None)
        DEVICE_ASSIGNMENTS.pop(busid, None)
        return JSONResponse({"status": "unassigned"})
    DEVICE_ASSIGNMENTS[busid] = client_id
    delivered = await send_to_client(client_id, f"Device {busid} binded\n")
    if delivered:
        DEVICE_IN_USE[busid] = client_id
        return JSONResponse({"status": "assigned"})
    else:
        DEVICE_IN_USE.pop(busid, None)
        return JSONResponse({"status": "queued-for-client"})


@app.get("/assign_all")
async def assign_all(client_id: str = Query(...)):
    global ASSIGN_ALL_CLIENT_ID
    if client_id == "none":
        ASSIGN_ALL_CLIENT_ID = None
        for busid in list(DEVICE_ASSIGNMENTS.keys()):
            force_free(busid)
            DEVICE_ASSIGNMENTS.pop(busid, None)
            DEVICE_IN_USE.pop(busid, None)
        return JSONResponse({"status": "cleared"})
    ASSIGN_ALL_CLIENT_ID = client_id

    for busid in list(deviceBindSet):
        if busid in DEVICE_ASSIGNMENTS and DEVICE_ASSIGNMENTS[busid] != client_id:
            force_free(busid)

    for busid in list(deviceBindSet):
        DEVICE_ASSIGNMENTS[busid] = client_id
        await send_to_client(client_id, f"Device {busid} binded\n")
        DEVICE_IN_USE[busid] = client_id
    return JSONResponse({"status": "assigned", "client_id": client_id})


@app.get("/force_free")
async def api_force_free(busid: str = Query(...)):
    if busid not in deviceBindSet:
        return JSONResponse({"status": "not-exported"})
    force_free(busid)
    DEVICE_IN_USE.pop(busid, None)
    return JSONResponse({"status": "freed"})


@app.get("/force_reattach")
async def api_force_reattach(busid: str = Query(...)):
    """Force reattach a device by busid if it is exported."""
    if busid not in deviceBindSet:
        return JSONResponse({"status": "not-exported"})
    force_free(busid)
    main_loop.call_soon_threadsafe(asyncio.create_task, notify_bound_to_assigned(busid))
    return JSONResponse({"status": "reattached"})

# ------------------ Main runner ------------------

async def main():
    """
    Runs the USBIP control socket and the web server.
    """
    load_assignments()
    scan_existing_devices()
    socket_server = await run_socket_server()
    socket_task = asyncio.create_task(socket_server.serve_forever())

    # noinspection HttpUrlsUsage
    logger.info(f"Web UI available at http://{WEB_HOST}:{WEB_PORT}")

    config = uvicorn.Config(app, host=WEB_HOST, port=WEB_PORT, log_level="info")
    server = uvicorn.Server(config)

    await server.serve()
    socket_task.cancel()
    await asyncio.gather(socket_task, return_exceptions=True)


def run_main():
    """Entrypoint for running the main async function."""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Script interrupted by user.")
    except SystemExit:
        logger.info("Script exiting.")
    finally:
        pass


if __name__ == "__main__":
    run_main()
