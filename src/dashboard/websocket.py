"""Socket.IO layer for real-time dashboard execution events."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Iterable, Optional, Set
from uuid import uuid4

import socketio

logger = logging.getLogger("dashboard.websocket")


class WebSocketManager:
    """Manages Socket.IO subscriptions for dashboard clients."""

    def __init__(self, server: Optional[socketio.AsyncServer] = None):
        self.server = server or self._build_server()
        self.asgi_app = socketio.ASGIApp(self.server, socketio_path="/socket.io")
        self.plan_subscriptions: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self.sid_metadata: Dict[str, Dict[str, Any]] = {}
        self.subscription_to_plan: Dict[str, str] = {}
        self.logger = logging.getLogger("dashboard.websocket")
        self._register_handlers()

    def _build_server(self) -> socketio.AsyncServer:
        return socketio.AsyncServer(
            async_mode="asgi",
            cors_allowed_origins="*",
            ping_interval=30,
            ping_timeout=60,
        )

    def _register_handlers(self) -> None:
        if not hasattr(self.server, "on"):
            return

        self.server.on("connect")(self.handle_connect)
        self.server.on("disconnect")(self.handle_disconnect)
        self.server.on("subscribe")(self.handle_subscribe)
        self.server.on("unsubscribe")(self.handle_unsubscribe)
        self.server.on("ping")(self.handle_ping)

    async def handle_connect(self, sid: str, environ: Dict[str, Any]) -> None:
        self.logger.info("Socket connected: %s", sid)
        self.sid_metadata.setdefault(sid, {"subscriptions": set(), "connected_at": datetime.utcnow()})

    async def handle_disconnect(self, sid: str) -> None:
        self.logger.info("Socket disconnect: %s", sid)
        subscriptions = list(self.sid_metadata.get(sid, {}).get("subscriptions", []))
        for subscription_id in subscriptions:
            await self._remove_subscription(subscription_id)
        self.sid_metadata.pop(sid, None)

    async def handle_subscribe(self, sid: str, payload: Dict[str, Any]) -> None:
        plan_id = payload.get("plan_id")
        if not plan_id:
            await self.server.emit("error", {"message": "plan_id required"}, to=sid)
            return

        subscription_id = payload.get("subscription_id") or str(uuid4())
        metadata = {
            "sid": sid,
            "request_id": payload.get("request_id"),
            "execution_id": payload.get("execution_id"),
            "created_at": datetime.utcnow(),
        }

        self.plan_subscriptions.setdefault(plan_id, {})[subscription_id] = metadata
        self.subscription_to_plan[subscription_id] = plan_id
        self.sid_metadata.setdefault(sid, {"subscriptions": set()})["subscriptions"].add(subscription_id)

        await self.server.emit(
            "subscription_ack",
            {"subscription_id": subscription_id, "plan_id": plan_id},
            to=sid,
        )
        self.logger.debug("Subscribed %s to plan %s", sid, plan_id)

    async def handle_unsubscribe(self, sid: str, payload: Dict[str, Any]) -> None:
        subscription_id = payload.get("subscription_id")
        plan_id = payload.get("plan_id")

        if subscription_id:
            await self._remove_subscription(subscription_id)
            await self.server.emit(
                "unsubscribed",
                {"subscription_id": subscription_id},
                to=sid,
            )
            return

        if plan_id:
            plan_subs = list(self.plan_subscriptions.get(plan_id, {}).keys())
            for sub_id in plan_subs:
                await self._remove_subscription(sub_id)
            await self.server.emit(
                "unsubscribed",
                {"plan_id": plan_id},
                to=sid,
            )

    async def handle_ping(self, sid: str, payload: Dict[str, Any]) -> None:
        await self.server.emit("pong", {"timestamp": datetime.utcnow().isoformat()}, to=sid)

    async def _remove_subscription(self, subscription_id: str) -> None:
        plan_id = self.subscription_to_plan.pop(subscription_id, None)
        if not plan_id:
            return
        plan_subs = self.plan_subscriptions.get(plan_id)
        if plan_subs and subscription_id in plan_subs:
            sid = plan_subs[subscription_id].get("sid")
            self.sid_metadata.get(sid, {}).get("subscriptions", set()).discard(subscription_id)
            plan_subs.pop(subscription_id, None)
            if not plan_subs:
                self.plan_subscriptions.pop(plan_id, None)

    async def broadcast_event(
        self,
        plan_id: str,
        event: str,
        data: Dict[str, Any],
        target_subscriptions: Optional[Iterable[str]] = None,
    ) -> None:
        subscribers = self.plan_subscriptions.get(plan_id, {})
        for subscription_id, metadata in subscribers.items():
            if target_subscriptions and subscription_id not in target_subscriptions:
                continue
            sid = metadata.get("sid")
            if not sid:
                continue
            payload = {
                "event": event,
                "subscription_id": subscription_id,
                "data": data,
            }
            try:
                await self.server.emit("plan_event", payload, to=sid)
            except Exception as exc:
                self.logger.warning("Failed to emit to %s: %s", sid, exc)

    def get_plan_subscriber_count(self, plan_id: str) -> int:
        return len(self.plan_subscriptions.get(plan_id, {}))

    def get_connection_count(self) -> int:
        return len(self.sid_metadata)


ws_manager = WebSocketManager()


async def broadcast_plan_approved(plan_id: str, request_id: str) -> None:
    await ws_manager.broadcast_event(
        plan_id,
        "plan_approved",
        {"request_id": request_id},
    )


async def broadcast_execution_started(plan_id: str, execution_id: str) -> None:
    await ws_manager.broadcast_event(
        plan_id,
        "execution_started",
        {"execution_id": execution_id},
    )


async def broadcast_step_completed(plan_id: str, step_index: int, result: Dict[str, Any]) -> None:
    await ws_manager.broadcast_event(
        plan_id,
        "step_completed",
        {"step_index": step_index, "result": result},
    )


async def broadcast_execution_done(plan_id: str, summary: Dict[str, Any]) -> None:
    await ws_manager.broadcast_event(
        plan_id,
        "execution_done",
        {"summary": summary},
    )
