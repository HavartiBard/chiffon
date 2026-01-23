"""Dashboard API endpoints that proxy to the orchestrator and add session logic."""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, get_args
from uuid import uuid4

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .models import (
    ChatMessage,
    ChatSession,
    DashboardPlanView,
    ExecutionUpdate,
    ModificationRequest,
    PlanStepView,
    SessionStore,
)

logger = logging.getLogger("dashboard.api")

ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_URL", "http://localhost:8000")
MAX_RETRIES = 3
TIMEOUT_SECONDS = 30

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

session_store = SessionStore()


class SessionCreateRequest(BaseModel):
    user_id: str


class ChatRequest(BaseModel):
    session_id: str
    message: str


class PlanActionRequest(BaseModel):
    session_id: str


async def _orchestrator_request(
    method: str,
    path: str,
    *,
    json: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    last_error: Optional[Exception] = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(
                base_url=ORCHESTRATOR_URL, timeout=TIMEOUT_SECONDS
            ) as client:
                response = await client.request(method, path, json=json, params=params)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            message = exc.response.text
            logger.error("Orchestrator HTTP error", exc_info=exc, extra={"path": path})
            raise HTTPException(
                status_code=exc.response.status_code, detail=message or "Orchestrator error"
            )
        except httpx.RequestError as exc:
            last_error = exc
            logger.warning("Orchestrator request failed", exc_info=exc, extra={"path": path})
            if attempt == MAX_RETRIES:
                logger.error("Orchestrator unreachable", exc_info=exc)
                raise HTTPException(status_code=502, detail="Orchestrator unavailable") from exc
            await asyncio.sleep(attempt * 0.1)
    raise HTTPException(status_code=502, detail="Orchestrator unavailable") from last_error


def _human_readable_duration(seconds: Optional[int]) -> str:
    if not seconds or seconds <= 0:
        return "Unknown duration"
    minutes, remainder = divmod(seconds, 60)
    if minutes >= 60:
        hours = minutes // 60
        minutes_remaining = minutes % 60
        if minutes_remaining:
            return f"~{hours}h {minutes_remaining}m"
        return f"~{hours}h"
    if minutes >= 1:
        return f"~{minutes} minute{'s' if minutes != 1 else ''}"
    return f"~{seconds} seconds"


def _risk_level_from_complexity(complexity: Optional[str]) -> str:
    return {
        "simple": "low",
        "medium": "medium",
        "complex": "high",
    }.get((complexity or "").lower(), "medium")


def _aggregate_resources(tasks: List[Dict[str, Any]]) -> Dict[str, Any]:
    acc: Dict[str, int] = {"cpu_cores": 0, "gpu_vram_mb": 0, "estimated_duration_seconds": 0}
    for task in tasks:
        req = task.get("resource_requirements", {})
        for key in acc:
            acc[key] += req.get(key, 0)
    return {k: v for k, v in acc.items() if v}


def _build_plan_steps(tasks: List[Dict[str, Any]]) -> List[PlanStepView]:
    if not tasks:
        return []

    steps: List[PlanStepView] = []
    status_field = PlanStepView.model_fields["status"]
    valid_statuses = get_args(status_field.annotation)
    for idx, task in enumerate(tasks):
        req = task.get("resource_requirements", {})
        duration_sec = req.get("estimated_duration_seconds")
        duration_ms = int(duration_sec * 1000) if duration_sec else None
        status = task.get("status") or "pending"
        steps.append(
            PlanStepView(
                index=idx,
                name=str(task.get("name") or f"Step {idx + 1}"),
                description=task.get("description")
                or task.get("parameters", {}).get("description")
                or task.get("work_type", ""),
                status=status if status in valid_statuses else "pending",
                duration_ms=duration_ms,
                completed=status == "completed",
                metadata={
                    "order": task.get("order"),
                    "work_type": task.get("work_type"),
                },
            )
        )
    return steps


def _format_plan_for_dashboard(plan: Dict[str, Any]) -> DashboardPlanView:
    tasks = plan.get("tasks", [])
    steps = _build_plan_steps(tasks)
    estimated_seconds = plan.get("estimated_duration_seconds")
    if estimated_seconds is None and steps:
        total_ms = sum(step.duration_ms or 0 for step in steps)
        estimated_seconds = total_ms // 1000
    resources = plan.get("resource_requirements") or _aggregate_resources(tasks)
    risk_level = _risk_level_from_complexity(plan.get("complexity_level"))
    status = plan.get("status", "pending_approval")

    return DashboardPlanView(
        plan_id=plan["plan_id"],
        request_id=plan["request_id"],
        summary=plan.get("human_readable_summary", "Plan ready for approval"),
        steps=steps,
        estimated_duration=_human_readable_duration(estimated_seconds),
        risk_level=risk_level,
        resource_requirements=resources,
        status=status,
        can_approve=status == "pending_approval",
        can_modify=status == "pending_approval",
        can_abort=status == "executing",
    )


def _create_chat_message(
    session_id: str,
    role: str,
    content: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> ChatMessage:
    return ChatMessage(
        id=str(uuid4()),
        session_id=session_id,
        role=role,
        content=content,
        timestamp=datetime.utcnow(),
        metadata=metadata or {},
    )


async def _prepare_plan_for_session(
    session: ChatSession, message: str, modification: bool = False
) -> DashboardPlanView:
    prompt = f"[Modify plan {session.current_plan_id}] {message}" if modification else message
    request_payload = {
        "request": prompt,
        "user_id": session.user_id,
    }

    request_result = await _orchestrator_request("POST", "/api/v1/request", json=request_payload)
    plan_data = await _orchestrator_request("GET", f"/api/v1/plan/{request_result['request_id']}")

    plan_view = _format_plan_for_dashboard(plan_data)
    session.current_request_id = request_result.get("request_id")
    session.current_plan_id = plan_view.plan_id
    session.status = "plan_ready"
    return plan_view


@router.post("/session", response_model=ChatSession)
async def create_session(payload: SessionCreateRequest) -> ChatSession:
    logger.info("create_session called for %s", payload.user_id)
    session = session_store.create_session(payload.user_id)
    return session


@router.get("/session/{session_id}", response_model=ChatSession)
async def get_session(session_id: str) -> ChatSession:
    session = session_store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.post("/chat")
async def chat(payload: ChatRequest) -> Dict[str, Any]:
    if not payload.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    session = session_store.get_session(payload.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    user_message = _create_chat_message(
        session.session_id,
        "user",
        payload.message.strip(),
    )
    session_store.add_message(session.session_id, user_message)
    session_store.update_session_status(session.session_id, "awaiting_plan")

    is_modification = bool(session.current_plan_id)
    try:
        plan_view = await _prepare_plan_for_session(
            session, payload.message, modification=is_modification
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=502, detail="Orchestrator request timed out")

    assistant_message = _create_chat_message(
        session.session_id,
        "assistant",
        plan_view.summary,
        metadata={
            "plan_id": plan_view.plan_id,
            "request_id": plan_view.request_id,
        },
    )
    session_store.add_message(session.session_id, assistant_message)

    return {
        "messages": [user_message, assistant_message],
        "plan": plan_view,
    }


@router.get("/plan/{plan_id}", response_model=DashboardPlanView)
async def get_plan(plan_id: str) -> DashboardPlanView:
    plan_data = await _orchestrator_request("GET", f"/api/v1/plan/{plan_id}/status")
    return _format_plan_for_dashboard(plan_data)


@router.post("/plan/{plan_id}/approve")
async def approve_plan(plan_id: str, payload: PlanActionRequest) -> Dict[str, Any]:
    session = session_store.get_session(payload.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    approval_payload = {"approved": True, "user_id": session.user_id}
    result = await _orchestrator_request(
        "POST", f"/api/v1/plan/{plan_id}/approve", json=approval_payload
    )
    session_store.update_session_status(session.session_id, "executing")
    session.current_plan_id = plan_id

    dispatch_result = result.get("dispatch_result", {})
    dispatched_tasks = (
        dispatch_result.get("dispatched_tasks", []) if isinstance(dispatch_result, dict) else []
    )
    session.active_task_ids = [task["task_id"] for task in dispatched_tasks if task.get("task_id")]

    return {
        "status": result.get("status"),
        "execution_started": result.get("dispatch_started", False),
    }


@router.post("/plan/{plan_id}/reject")
async def reject_plan(plan_id: str, payload: PlanActionRequest) -> Dict[str, Any]:
    session = session_store.get_session(payload.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    rejection_payload = {"approved": False, "user_id": session.user_id}
    result = await _orchestrator_request(
        "POST", f"/api/v1/plan/{plan_id}/approve", json=rejection_payload
    )
    session_store.update_session_status(session.session_id, "idle")
    session.current_plan_id = None

    rejection_message = _create_chat_message(
        session.session_id,
        "system",
        "Plan rejected. Start a new chat to generate another plan.",
        metadata={"plan_id": plan_id},
    )
    session_store.add_message(session.session_id, rejection_message)

    return {"status": result.get("status")}


@router.post("/plan/{plan_id}/modify")
async def modify_plan(plan_id: str, payload: ModificationRequest) -> Dict[str, Any]:
    session = session_store.get_session(payload.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    user_message = _create_chat_message(
        session.session_id,
        "user",
        payload.user_message.strip(),
        metadata={"plan_id": plan_id},
    )
    session_store.add_message(session.session_id, user_message)
    session_store.update_session_status(session.session_id, "awaiting_plan")

    plan_view = await _prepare_plan_for_session(session, payload.user_message, modification=True)
    assistant_message = _create_chat_message(
        session.session_id,
        "assistant",
        plan_view.summary,
        metadata={
            "plan_id": plan_view.plan_id,
            "request_id": plan_view.request_id,
        },
    )
    session_store.add_message(session.session_id, assistant_message)

    return {"new_plan": plan_view}


@router.get("/plan/{plan_id}/status")
async def plan_status(plan_id: str) -> Dict[str, Any]:
    data = await _orchestrator_request("GET", f"/api/v1/plan/{plan_id}/status")
    steps = []
    for idx, task in enumerate(data.get("tasks", [])):
        steps.append(
            ExecutionUpdate(
                plan_id=plan_id,
                step_index=idx,
                step_name=task.get("name", f"Step {idx + 1}"),
                status=task.get("status", "pending"),
                output=task.get("output"),
                error=task.get("error"),
            ).model_dump()
        )

    return {
        "status": data.get("status"),
        "steps": steps,
        "last_update": datetime.utcnow().isoformat(),
    }


@router.get("/plan/{plan_id}/poll")
async def poll_plan(plan_id: str) -> JSONResponse:
    data = await _orchestrator_request("GET", f"/api/v1/plan/{plan_id}/status")
    steps = []
    for idx, task in enumerate(data.get("tasks", [])):
        steps.append(
            ExecutionUpdate(
                plan_id=plan_id,
                step_index=idx,
                step_name=task.get("name", f"Step {idx + 1}"),
                status=task.get("status", "pending"),
                output=task.get("output"),
                error=task.get("error"),
            ).model_dump()
        )

    payload = {
        "overall_status": data.get("status"),
        "steps": steps,
        "last_update": datetime.utcnow().isoformat(),
    }
    response = JSONResponse(content=payload)
    response.headers["X-Poll-Interval"] = "2000"
    return response


@router.post("/plan/{plan_id}/abort")
async def abort_plan(plan_id: str, payload: PlanActionRequest) -> Dict[str, Any]:
    session = session_store.get_session(payload.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if not session.active_task_ids:
        raise HTTPException(status_code=400, detail="No running tasks to abort")

    cancelled = []
    for task_id in session.active_task_ids:
        result = await _orchestrator_request("POST", f"/api/v1/cancel/{task_id}")
        cancelled.append(result)

    session.active_task_ids = []
    session_store.update_session_status(session.session_id, "idle")
    session.current_plan_id = None

    return {"status": "aborted", "cancelled": len(cancelled)}
