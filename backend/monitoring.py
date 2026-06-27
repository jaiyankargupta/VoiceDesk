import asyncio
import json
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


class EventType(str, Enum):
    TRANSCRIPT = "transcript"
    AGENT_STATE = "agent_state"
    INTENT = "intent_detected"
    ACTION = "action_update"
    CALL_STATUS = "call_status"
    APPOINTMENT_DATA = "appointment_data"
    CALL_SUMMARY = "call_summary"


@dataclass
class MonitorEvent:
    type: EventType
    data: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_json(self) -> str:
        return json.dumps({"type": self.type.value, "data": self.data, "ts": self.timestamp})


class EventBus:
    """Broadcasts monitoring events to all connected WebSocket clients."""

    def __init__(self):
        self._subscribers: list[asyncio.Queue] = []
        self._history: list[MonitorEvent] = []

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=256)
        for event in self._history:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                break
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue):
        self._subscribers = [s for s in self._subscribers if s is not q]

    async def publish(self, event: MonitorEvent):
        self._history.append(event)
        if len(self._history) > 100:
            self._history.pop(0)
        dead = []
        for q in self._subscribers:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self._subscribers.remove(q)

    async def emit(self, event_type: EventType, data: dict | None = None):
        await self.publish(MonitorEvent(type=event_type, data=data or {}))
        try:
            import aiohttp
            async with aiohttp.ClientSession() as s:
                await s.post(
                    "http://127.0.0.1:8080/api/events",
                    json={"type": event_type.value, "data": data or {}},
                    timeout=aiohttp.ClientTimeout(total=0.5),
                )
        except Exception:
            pass


event_bus = EventBus()
