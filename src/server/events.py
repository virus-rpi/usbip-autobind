import asyncio
from typing import Any, Callable


class EventDispatcher:
    def __init__(self):
        self.listeners: dict[str, list[Callable]] = {}

    def subscribe(self, event_type: str, callback: Callable):
        """Register a callback (sync or async) for an event type."""
        self.listeners.setdefault(event_type, []).append(callback)

    async def emit(self, event_type: str, *args, **kwargs) -> list[Any]:
        """Emit an event and await all listeners, returning their results."""
        results = []
        for cb in self.listeners.get(event_type, []):
            if asyncio.iscoroutinefunction(cb):
                results.append(await cb(*args, **kwargs))
            else:
                results.append(cb(*args, **kwargs))
        return results
