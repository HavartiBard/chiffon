"""Entry point for the Chiffon dashboard FastAPI service."""
from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager
from typing import Iterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import router as dashboard_router, session_store
from .websocket import ws_manager

logger = logging.getLogger("dashboard.main")


@asynccontextmanager
async def lifespan(app: FastAPI) -> Iterator[None]:
    logger.info("Starting session cleanup worker")
    stop_event = threading.Event()
    cleanup_thread = threading.Thread(
        target=_session_cleanup_worker,
        args=(stop_event,),
        name="session-cleanup",
        daemon=True,
    )
    cleanup_thread.start()
    try:
        yield
    finally:
        stop_event.set()
        cleanup_thread.join()


app = FastAPI(title="Chiffon Dashboard", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

app.include_router(dashboard_router)
app.mount("/ws", ws_manager.asgi_app)
app.state.ws_manager = ws_manager


def _session_cleanup_worker(stop_event: threading.Event, interval: int = 300) -> None:
    while not stop_event.wait(interval):
        cleaned = session_store.cleanup_expired()
        if cleaned:
            logger.info("Expired sessions cleaned", extra={"removed": cleaned})


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
