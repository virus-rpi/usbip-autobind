from nicegui import ui, app
import httpx
import asyncio
from typing import Callable
from . import WEB_HOST, WEB_PORT, dispatcher

# noinspection HttpUrlsUsage
API_URL = f'http://{WEB_HOST}:{WEB_PORT}'

# ──────────────── API Calls ────────────────

async def fetch_devices():
    async with httpx.AsyncClient() as client:
        resp = await client.get(f'{API_URL}/devices')
        return resp.json().get('devices', [])

async def fetch_clients():
    async with httpx.AsyncClient() as client:
        resp = await client.get(f'{API_URL}/clients')
        return resp.json().get('clients', [])

async def fetch_debug():
    async with httpx.AsyncClient() as client:
        resp = await client.get(f'{API_URL}/debug')
        return resp.json()

async def assign_device(bus_id, client_id):
    async with httpx.AsyncClient() as client:
        resp = await client.post(f'{API_URL}/devices/{bus_id}/assign', json={'client_id': client_id})
        return resp.json()

async def unassign_device(bus_id):
    async with httpx.AsyncClient() as client:
        resp = await client.post(f'{API_URL}/devices/{bus_id}/assign', json={'client_id': "none"})
        return resp.json()

async def force_free_device(bus_id):
    async with httpx.AsyncClient() as client:
        resp = await client.post(f'{API_URL}/devices/{bus_id}/force_free')
        return resp.json()

async def force_reattach_device(bus_id):
    async with httpx.AsyncClient() as client:
        resp = await client.post(f'{API_URL}/devices/{bus_id}/force_reattach')
        return resp.json()

async def assign_all_devices(client_id):
    async with httpx.AsyncClient() as client:
        resp = await client.post(f'{API_URL}/assign_all', json={'client_id': client_id})
        return resp.json()

async def unassign_all_devices():
    async with httpx.AsyncClient() as client:
        resp = await client.post(f'{API_URL}/assign_all', json={'client_id': "none"})
        return resp.json()

# ──────────────── Utilities ───────────────────

def get_device_status(device):
    if device['assigned_to'] and not device['in_use']:
        return 'Assigned but not in use'
    elif device['assigned_to'] and device['in_use']:
        return 'In use by assigned client'
    elif not device['assigned_to'] and not device['in_use']:
        return 'Is available'
    else:
        return 'Not a valid state'


# ──────────────── UI Components ────────────────

def assign_dialog(device, clients, refresh_callback, force_dialog=False):
    def do_assign(client_id):
        ui.notify(f'Assigning {device["bus_id"]} to {client_id}')
        asyncio.create_task(assign_device(device['bus_id'], client_id))
        asyncio.create_task(refresh_callback())
        if dialog:
            dialog.close()

    if device['assigned_to'] and not force_dialog:
        do_assign(device['assigned_to'])

    with ui.dialog() as dialog:
        with ui.card():
            ui.label(f"Assign {device['bus_id']} to:")
            for client in clients:
                ui.button(client, on_click=lambda c=client: do_assign(c))
            ui.button('Cancel', on_click=dialog.close)
        dialog.open()

def unassign_action(device, refresh_callback):
    ui.notify(f'Unassigning {device["bus_id"]}')
    asyncio.create_task(unassign_device(device["bus_id"]))
    asyncio.create_task(refresh_callback())

def force_free_action(device, refresh_callback):
    ui.notify(f'Force freeing {device["bus_id"]}')
    asyncio.create_task(force_free_device(device['bus_id']))
    asyncio.create_task(refresh_callback())

def force_reattach_action(device, refresh_callback):
    ui.notify(f'Reattaching {device["bus_id"]}')
    asyncio.create_task(force_reattach_device(device['bus_id']))
    asyncio.create_task(refresh_callback())

def assign_all_dialog(clients, refresh_callback):
    def do_assign_all(client_id):
        ui.notify(f'Assigning all devices to {client_id}')
        asyncio.create_task(assign_all_devices(client_id))
        asyncio.create_task(refresh_callback())
        dialog.close()

    with ui.dialog() as dialog:
        with ui.card():
            ui.label("Assign all devices to:")
            for client in clients:
                ui.button(client, on_click=lambda c=client: do_assign_all(c))
            ui.button('Cancel', on_click=dialog.close)
        dialog.open()

def device_card(device, clients, refresh_callback):
    with ui.card().classes('m-2 p-4'):
        ui.label(f"{device['bus_id']} — {device['name']}").classes('text-lg font-bold')
        ui.label(f"Status: {get_device_status(device)}")
        assigned = device['assigned_to'] or 'None'
        color = 'blue' if assigned.lower() != 'none' else 'grey'
        ui.row().classes('items-center')
        ui.label('Assigned to:').classes('font-bold mr-2')
        ui.chip(assigned, color=color).classes(f'text-white text-lg font-bold px-4 py-2')
        with ui.row().classes('gap-2 mt-2'):
            ui.button('Assign', icon='person_add', on_click=lambda: assign_dialog(device, clients, refresh_callback))
            if device['assigned_to']:
                ui.button('Assign to other client', icon='person_add', color='positive', on_click=lambda: assign_dialog(device, clients, refresh_callback, force_dialog=True))
            ui.button('Unassign', icon='person_remove', color='warning', on_click=lambda: unassign_action(device, refresh_callback))
            ui.button('Force Free', icon='lock_open', color='negative', on_click=lambda: force_free_action(device, refresh_callback))
            ui.button('Reattach', icon='sync', color='secondary', on_click=lambda: force_reattach_action(device, refresh_callback))

clients_table_refresh: Callable | None = None
devices_table_refresh: Callable | None = None
debug_panel_refresh: Callable | None = None

def show_clients_table():
    container = ui.column().classes('w-full')
    async def refresh():
        clients = await fetch_clients()
        with container:
            container.clear()
            ui.label('Connected Clients').classes('text-xl font-bold mb-2')
            if clients:
                with ui.list().props('dense separator'):
                    for client in clients:
                        ui.item(client)
            else:
                ui.label('No clients connected').classes('text-lg')
    global clients_table_refresh
    clients_table_refresh = refresh
    asyncio.create_task(refresh())
    return container

def show_device_groups():
    container = ui.column().classes('w-full')
    async def refresh():
        devices = await fetch_devices()
        clients = await fetch_clients()
        debug = await fetch_debug()
        assign_all_client_id = debug.get('assign_all_client_id', None)
        with container:
            container.clear()
            ui.label('Devices').classes('text-xl font-bold mb-2')
            assigned_client = assign_all_client_id if assign_all_client_id and assign_all_client_id != "none" else None
            if assigned_client:
                ui.label(f"All devices assigned to: {assigned_client}").classes('font-bold text-lg')
            with ui.row().classes('mt-4 gap-2'):
                if assigned_client:
                    ui.button('Assign All', icon='group', on_click=lambda: (asyncio.create_task(assign_all_devices(assigned_client)), asyncio.create_task(refresh())))
                    ui.button('Assign All to Other Client', icon='group', color='positive', on_click=lambda: assign_all_dialog(clients, refresh))
                else:
                    ui.button('Assign All', icon='group', on_click=lambda: assign_all_dialog(clients, refresh))
                ui.button('Unassign All', icon='person_remove', color='warning',
                          on_click=lambda: asyncio.create_task(unassign_all_devices()) or asyncio.create_task(refresh())).classes('mb-4')
                ui.button('Refresh', icon='refresh', on_click=lambda: asyncio.create_task(refresh()))
            if not devices:
                ui.label('No devices found').classes('text-xl font-bold')
            for device in devices:
                device_card(device, clients, refresh)
    global devices_table_refresh
    devices_table_refresh = refresh
    asyncio.create_task(refresh())
    return container

def show_debug_panel():
    panel = ui.column().classes('w-full')
    async def refresh(collapsed=True):
        debug = await fetch_debug()
        with panel:
            panel.clear()
            with ui.expansion('Debug Info', value=not collapsed).classes('w-full'):
                ui.json_editor({'content': {'json': debug, 'readOnly': True}})
                ui.button('Refresh', icon='bug_report', on_click=lambda: asyncio.create_task(refresh(collapsed=False)))
    global debug_panel_refresh
    debug_panel_refresh = refresh
    asyncio.create_task(refresh())
    return panel

def _on_update(*_):
    loop = asyncio.get_event_loop()
    if clients_table_refresh is not None:
        loop.call_soon_threadsafe(asyncio.create_task, clients_table_refresh())
    if devices_table_refresh is not None:
        loop.call_soon_threadsafe(asyncio.create_task, devices_table_refresh())
    if debug_panel_refresh is not None:
        loop.call_soon_threadsafe(asyncio.create_task, debug_panel_refresh())


dispatcher.subscribe("updated", _on_update)

class DarkModeToggle(ui.button):
    def __init__(self, dark, *args, **kwargs) -> None:
        self._state = True
        self._icon = 'dark_mode' if self._state else 'light_mode'
        dark.bind_value_from(self, '_state')
        super().__init__(*args, **kwargs)
        self.bind_icon_from(self, '_icon')
        self.on('click', self.toggle)

    def toggle(self) -> None:
        """Toggle the button state."""
        self._state = not self._state
        self.update()

    def update(self) -> None:
        with self.props.suspend_updates():
            self.props(f'flat round color={"yellow" if self._state else "black"}')
            self._icon = 'dark_mode' if self._state else 'light_mode'
        super().update()


# ──────────────── Main Page ────────────────

@ui.page('/')
def main_page():
    with ui.header().classes('justify-between items-center'):
        ui.label('USBIP Device Manager').classes('text-2xl font-bold self-center')
        dark = ui.dark_mode()
        dark.enable()
        DarkModeToggle(dark)
    show_clients_table()
    show_device_groups()
    show_debug_panel()

def run(fastapi_app):
    ui.run_with(fastapi_app, mount_path='/')
