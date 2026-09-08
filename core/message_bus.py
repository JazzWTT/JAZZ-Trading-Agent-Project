"""
JAZZ Trading United Nation - Asynchronous Message Bus
Facilitates non-blocking event-driven communication between all 5 team agents.
"""

import asyncio
from typing import Dict, List, Callable, Any
import logging

logger = logging.getLogger("MessageBus")


class MessageBus:
    def __init__(self):
        self._subscribers: Dict[str, List[Callable[[Any], Any]]] = {}
        self._queues: Dict[str, asyncio.Queue] = {}
        self._lock = asyncio.Lock()

    def subscribe(self, topic: str, callback: Callable[[Any], Any]):
        """Subscribe a synchronous or asynchronous callback to a topic."""
        if topic not in self._subscribers:
            self._subscribers[topic] = []
        self._subscribers[topic].append(callback)

    def get_queue(self, topic: str) -> asyncio.Queue:
        """Get or create an asyncio.Queue for a specific topic."""
        if topic not in self._queues:
            self._queues[topic] = asyncio.Queue()
        return self._queues[topic]

    async def publish(self, topic: str, message: Any):
        """Publish a message to all subscribers and the topic queue."""
        # Push to queue if someone is awaiting it
        if topic in self._queues:
            await self._queues[topic].put(message)

        # Call registered callbacks
        if topic in self._subscribers:
            for callback in self._subscribers[topic]:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        asyncio.create_task(callback(message))
                    else:
                        callback(message)
                except Exception as e:
                    logger.error(f"Error executing callback for topic {topic}: {e}")
