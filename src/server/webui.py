from nicegui import ui, app
import httpx
import asyncio
import json

from . import WEB_HOST, WEB_PORT

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

async def detach_device(bus_id, client_id=None):
    async with httpx.AsyncClient() as client:
        resp = await client.post(f'{API_URL}/devices/{bus_id}/detach', json={'client_id': client_id})
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

# ──────────────── Utilities ───────────────────

def get_device_status(device):
    if device['assigned_to']:
        return 'assigned'
    elif device['in_use']:
        return 'in use'
    else:
        return 'available'


# ──────────────── UI Components ────────────────

def assign_dialog(device, clients, refresh_callback):
    def do_assign(client_id):
        ui.notify(f'Assigning {device["bus_id"]} to {client_id}')
        asyncio.create_task(assign_device(device['bus_id'], client_id))
        refresh_callback()
        dialog.close()

    with ui.dialog() as dialog:
        with ui.card():
            ui.label(f"Assign {device['bus_id']} to:")
            for client in clients:
                ui.button(client, on_click=lambda c=client: do_assign(c))
            ui.button('Cancel', on_click=dialog.close)
        dialog.open()

def detach_action(device, refresh_callback):
    ui.notify(f'Detaching {device["bus_id"]}')
    asyncio.create_task(detach_device(device['bus_id']))
    refresh_callback()

def force_free_action(device, refresh_callback):
    ui.notify(f'Force freeing {device["bus_id"]}')
    asyncio.create_task(force_free_device(device['bus_id']))
    refresh_callback()

def force_reattach_action(device, refresh_callback):
    ui.notify(f'Reattaching {device["bus_id"]}')
    asyncio.create_task(force_reattach_device(device['bus_id']))
    refresh_callback()

def assign_all_dialog(clients, refresh_callback):
    def do_assign_all(client_id):
        ui.notify(f'Assigning all devices to {client_id}')
        asyncio.create_task(assign_all_devices(client_id))
        refresh_callback()
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
        ui.label(f"Assigned to: {device['assigned_to'] or 'None'}")
        with ui.row().classes('gap-2 mt-2'):
            ui.button('Assign', icon='person_add', on_click=lambda: assign_dialog(device, clients, refresh_callback))
            ui.button('Detach', icon='person_remove', color='warning', on_click=lambda: detach_action(device, refresh_callback))
            ui.button('Force Free', icon='lock_open', color='negative', on_click=lambda: force_free_action(device, refresh_callback))
            ui.button('Reattach', icon='sync', color='secondary', on_click=lambda: force_reattach_action(device, refresh_callback))

def show_device_groups():
    container = ui.column().classes('w-full')
    async def refresh():
        devices = await fetch_devices()
        clients = await fetch_clients()
        with container:
            container.clear()
            for label, status in [('Assigned Devices', 'assigned'), ('Available Devices', 'available'), ('Disconnected Devices', 'disconnected')]:
                with ui.expansion(label).classes('w-full'):
                    for device in devices:
                        device_status = get_device_status(device)
                        if device_status == status:
                            device_card(device, clients, refresh)
            with ui.row().classes('mt-4 gap-2'):
                ui.button('Refresh', icon='refresh', on_click=lambda: asyncio.create_task(refresh()))
                ui.button('Assign All', icon='group', on_click=lambda: assign_all_dialog(clients, refresh))
    asyncio.create_task(refresh())
    return container

def show_client_sidebar():
    sidebar = ui.column().classes('fixed top-20 right-0 w-64 p-4')
    async def refresh():
        clients = await fetch_clients()
        with sidebar:
            sidebar.clear()
            ui.label('Connected Clients').classes('text-xl font-bold mb-2')
            for client in clients:
                ui.label(client).classes('font-semibold')
    asyncio.create_task(refresh())

def show_debug_panel():
    panel = ui.column().classes('w-full')
    async def refresh():
        debug = await fetch_debug()
        with panel:
            panel.clear()
            with ui.expansion('Debug Info').classes('w-full'):
                ui.json_editor({'content': {'json': debug, 'readOnly': True}})
                ui.button('Refresh', icon='bug_report', on_click=lambda: asyncio.create_task(refresh()))
    asyncio.create_task(refresh())
    return panel

# ──────────────── Main Page ────────────────

@ui.page('/')
def main_page():
    with ui.header().classes('justify-between'):
        ui.label('USBIP Device Manager').classes('text-2xl font-bold')
        ui.dark_mode()

    show_client_sidebar()
    show_device_groups()
    show_debug_panel()

def run(fastapi_app):
    ui.run_with(fastapi_app, mount_path='/')
