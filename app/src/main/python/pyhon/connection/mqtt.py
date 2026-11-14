"""Android build: the push channel is disabled.

pyhOn's real client depends on awscrt, which has no Android wheel. The app
runs stateless HTTP queries, so setup() gets a no-op client instead of a
connection. Nothing here talks to the appliance.
"""

from __future__ import annotations


class MQTTClient:
    def __init__(self, hon, mobile_id: str) -> None:
        self._hon = hon
        self._mobile_id = mobile_id

    async def create(self) -> "MQTTClient":
        return self
