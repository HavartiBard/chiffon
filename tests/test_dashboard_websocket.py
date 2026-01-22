"""Unit tests for the dashboard Socket.IO manager."""
from __future__ import annotations

from typing import Any, Dict, List

import pytest

from src.dashboard.websocket import WebSocketManager


class DummySocketServer:
    def __init__(self):
        self.emitted: List[Dict[str, Any]] = []

    async def emit(self, event: str, data: Dict[str, Any], to: str | None = None):
        self.emitted.append({"event": event, "data": data, "to": to})


@pytest.fixture
def dummy_server() -> DummySocketServer:
    return DummySocketServer()


@pytest.fixture
def manager(dummy_server: DummySocketServer) -> WebSocketManager:
    return WebSocketManager(server=dummy_server)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_subscription_lifecycle(manager: WebSocketManager, dummy_server: DummySocketServer) -> None:
    await manager.handle_connect("sid-1", {})
    await manager.handle_subscribe("sid-1", {"plan_id": "plan-1", "request_id": "req-1"})

    assert manager.get_plan_subscriber_count("plan-1") == 1
    assert dummy_server.emitted[-1]["event"] == "subscription_ack"

    await manager.handle_unsubscribe("sid-1", {"subscription_id": list(manager.subscription_to_plan)[0]})
    assert manager.get_plan_subscriber_count("plan-1") == 0
    assert dummy_server.emitted[-1]["event"] == "unsubscribed"


@pytest.mark.asyncio
async def test_disconnect_cleans_subscriptions(manager: WebSocketManager, dummy_server: DummySocketServer) -> None:
    await manager.handle_connect("sid-2", {})
    await manager.handle_subscribe("sid-2", {"plan_id": "plan-2"})
    assert manager.sid_metadata["sid-2"]["subscriptions"]
    await manager.handle_disconnect("sid-2")
    assert manager.get_plan_subscriber_count("plan-2") == 0
    assert "sid-2" not in manager.sid_metadata


@pytest.mark.asyncio
async def test_ping_returns_pong(manager: WebSocketManager, dummy_server: DummySocketServer) -> None:
    await manager.handle_connect("sid-3", {})
    await manager.handle_ping("sid-3", {})
    assert dummy_server.emitted[-1]["event"] == "pong"


@pytest.mark.asyncio
async def test_broadcast_emits_plan_event(manager: WebSocketManager, dummy_server: DummySocketServer) -> None:
    await manager.handle_connect("sid-4", {})
    await manager.handle_subscribe("sid-4", {"plan_id": "plan-3", "request_id": "req-3"})
    await manager.broadcast_event("plan-3", "execution_started", {"foo": "bar"})

    assert any(call["event"] == "plan_event" for call in dummy_server.emitted)

