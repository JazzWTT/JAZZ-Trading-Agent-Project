"""
JAZZ Trading United Nation - Base Agent Interface
Abstract foundational structure for each of the 5 team delegates.
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Optional
from core.message_bus import MessageBus
from config import SystemConfig, DEFAULT_CONFIG


class BaseAgent(ABC):
    def __init__(self, agent_id: str, role: str, bus: MessageBus, config: SystemConfig = DEFAULT_CONFIG):
        self.agent_id = agent_id
        self.role = role
        self.bus = bus
        self.config = config
        self.logger = logging.getLogger(f"Agent.{agent_id}")
        self.is_running = False
        self._tasks = []

    @abstractmethod
    async def start(self):
        """Start the agent background loops and subscriptions."""
        self.is_running = True
        self.logger.info(f"[{self.agent_id}] Initialized as '{self.role}'")

    async def stop(self):
        """Gracefully stop agent tasks."""
        self.is_running = False
        for task in self._tasks:
            if not task.done():
                task.cancel()
        self.logger.info(f"[{self.agent_id}] Stopped.")
