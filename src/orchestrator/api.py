"""REST API endpoints for orchestrator operations.

Provides:
- POST /api/v1/dispatch: Submit work requests
- GET /api/v1/status/{task_id}: Query task status
- GET /api/v1/agents: List connected agents
- POST /api/v1/cancel/{task_id}: Cancel in-flight tasks

All responses use consistent JSON format with error codes for correlation.
"""

import logging
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.orchestrator.service import OrchestratorService

logger = logging.getLogger(__name__)

# Create router
router = APIRouter(prefix="/api/v1", tags=["orchestration"])


# Pydantic Models for REST API
class RequestSubmissionRequest(BaseModel):
    """Request to submit a natural language request."""

    request: str = Field(description="Natural language request")
    user_id: str = Field(description="User ID")


class RequestSubmissionResponse(BaseModel):
    """Response from request submission."""

    request_id: str = Field(description="Unique request ID")
    status: str = Field(description="Status: parsing_complete|requires_clarification|parsing_failed")
    decomposed_request: Optional[dict] = Field(default=None, description="Decomposed request if successful")
    ambiguities: Optional[list] = Field(default=None, description="Ambiguities found")
    out_of_scope: Optional[list] = Field(default=None, description="Out-of-scope items")
    error: Optional[str] = Field(default=None, description="Error message if failed")


class PlanGenerationResponse(BaseModel):
    """Response from plan generation."""

    plan_id: str = Field(description="Unique plan ID")
    request_id: str = Field(description="Request ID this plan is for")
    status: str = Field(description="Status: pending_approval|planning_failed")
    tasks: list = Field(default_factory=list, description="Tasks in plan")
    human_readable_summary: str = Field(description="Human-readable plan summary")
    complexity_level: str = Field(description="simple|medium|complex")
    will_use_external_ai: bool = Field(description="Whether Claude will be used")
    error: Optional[str] = Field(default=None, description="Error if planning failed")


class ApprovalRequest(BaseModel):
    """Request to approve or reject a plan."""

    approved: bool = Field(description="True to approve, False to reject")
    user_id: str = Field(description="User approving")
    notes: Optional[str] = Field(default=None, description="Optional approval notes")


class ApprovalResponse(BaseModel):
    """Response from plan approval."""

    plan_id: str = Field(description="Plan ID")
    status: str = Field(description="approved|rejected")
    dispatch_started: Optional[bool] = Field(default=None, description="True if dispatch started")
    error: Optional[str] = Field(default=None, description="Error if approval failed")


class PlanStatusResponse(BaseModel):
    """Response from plan status query."""

    plan_id: str = Field(description="Plan ID")
    request_id: str = Field(description="Request ID")
    status: str = Field(description="pending|approved|executing|completed|failed")
    complexity_level: str = Field(description="Plan complexity")
    will_use_external_ai: bool = Field(description="Whether Claude is/was used")
    tasks: list = Field(description="Task list")
    created_at: Optional[str] = Field(default=None, description="Created timestamp")
    approved_at: Optional[str] = Field(default=None, description="Approved timestamp")


class DispatchRequest(BaseModel):
    """Request to dispatch work to agents."""

    task_id: UUID = Field(description="Task ID")
    work_type: str = Field(description="Type of work (e.g., ansible, shell_script)")
    parameters: dict = Field(default_factory=dict, description="Work parameters")
    priority: int = Field(default=3, ge=1, le=5, description="Priority 1-5")


class DispatchResponse(BaseModel):
    """Response from work dispatch."""

    trace_id: UUID = Field(description="Trace ID for correlation")
    request_id: UUID = Field(description="Request ID for idempotency")
    task_id: UUID = Field(description="Task ID")
    status: str = Field(default="pending", description="Initial status")


class TaskStatus(BaseModel):
    """Task status response."""

    task_id: UUID
    status: str
    progress: str = Field(default="", description="Human-readable progress")
    output: str = Field(default="", description="Work output")
    error_message: Optional[str] = None
    exit_code: Optional[int] = None
    duration_ms: Optional[int] = None
    trace_id: Optional[UUID] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class Agent(BaseModel):
    """Agent status response."""

    agent_id: UUID
    agent_type: str
    status: str
    resources: dict = Field(description="Resource metrics")
    last_heartbeat_at: datetime


class ErrorResponse(BaseModel):
    """Standard error response."""

    error_code: int = Field(ge=1000, le=9999, description="Error code")
    error_message: str = Field(description="Error message")
    trace_id: Optional[UUID] = None


class CancelResponse(BaseModel):
    """Response from cancel request."""

    task_id: UUID
    status: str = Field(default="cancelled")


# Dependency injection for orchestrator service
def get_orchestrator_service() -> OrchestratorService:
    """Get orchestrator service from app state.

    This is set by main.py during app startup.
    Actual implementation is injected in main.py via app.dependency_overrides.
    """
    raise RuntimeError("Orchestrator service not initialized")


@router.post("/dispatch", response_model=DispatchResponse)
async def dispatch_work(
    req: DispatchRequest,
    service: OrchestratorService = Depends(get_orchestrator_service),
) -> dict:
    """Submit new work request for dispatch to agents.

    Creates a task, publishes to RabbitMQ, returns trace/request IDs.

    Args:
        req: DispatchRequest with task_id, work_type, parameters, priority
        service: Orchestrator service

    Returns:
        DispatchResponse with trace_id, request_id, task_id, status

    Raises:
        HTTPException: On validation or dispatch error
    """
    try:
        # Validate priority
        if not (1 <= req.priority <= 5):
            logger.error(f"Invalid priority: {req.priority}")
            raise ValueError("Priority must be 1-5")

        # Dispatch work
        result = await service.dispatch_work(
            task_id=req.task_id,
            work_type=req.work_type,
            parameters=req.parameters,
            priority=req.priority,
        )

        logger.info(
            "Work dispatch successful",
            extra={
                "trace_id": result["trace_id"],
                "task_id": result["task_id"],
                "work_type": req.work_type,
            },
        )
        return result

    except ValueError as e:
        error_msg = str(e)
        logger.error(f"Validation error: {error_msg}")
        raise HTTPException(status_code=400, detail=error_msg)
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Dispatch error: {error_msg}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal error: {error_msg}")


@router.get("/status/{task_id}", response_model=TaskStatus)
async def get_status(
    task_id: UUID,
    service: OrchestratorService = Depends(get_orchestrator_service),
) -> dict:
    """Query task status and progress.

    Args:
        task_id: Task to query
        service: Orchestrator service

    Returns:
        TaskStatus with current state

    Raises:
        HTTPException: If task not found or query fails
    """
    try:
        result = await service.get_task_status(task_id)
        logger.info(f"Status query: {task_id} -> {result['status']}")
        return result

    except ValueError as e:
        logger.warning(f"Task not found: {task_id}")
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Status query error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal error: {e}")


@router.get("/agents", response_model=list[Agent])
async def list_agents(
    agent_type: Optional[str] = None,
    status: Optional[str] = None,
    service: OrchestratorService = Depends(get_orchestrator_service),
) -> list[dict]:
    """List connected agents with resource status.

    Args:
        agent_type: Filter by agent type (optional)
        status: Filter by status online/offline/busy (optional)
        service: Orchestrator service

    Returns:
        List of Agent dicts

    Raises:
        HTTPException: On query error
    """
    try:
        agents = await service.list_agents(agent_type=agent_type, status=status)
        logger.info(f"Listed agents: {len(agents)} agents")
        return agents

    except Exception as e:
        logger.error(f"Agent list error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal error: {e}")


@router.post("/cancel/{task_id}", response_model=CancelResponse)
async def cancel_task(
    task_id: UUID,
    service: OrchestratorService = Depends(get_orchestrator_service),
) -> dict:
    """Cancel an in-flight task.

    Args:
        task_id: Task to cancel
        service: Orchestrator service

    Returns:
        CancelResponse with task_id and status

    Raises:
        HTTPException: If task not found or cannot be cancelled
    """
    try:
        result = await service.cancel_task(task_id)
        logger.info(f"Task cancelled: {task_id}")
        return result

    except ValueError as e:
        error_msg = str(e)
        if "not found" in error_msg.lower():
            logger.warning(f"Cancel: task not found: {task_id}")
            raise HTTPException(status_code=404, detail=error_msg)
        else:
            logger.warning(f"Cancel: invalid state: {error_msg}")
            raise HTTPException(status_code=400, detail=error_msg)
    except Exception as e:
        logger.error(f"Cancel error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal error: {e}")


# ==================== Phase 3: Orchestration Workflow ====================


@router.post("/request", response_model=dict)
async def submit_request(
    req: RequestSubmissionRequest,
    service: OrchestratorService = Depends(get_orchestrator_service),
) -> dict:
    """Submit a natural language request to the orchestrator.

    Request body:
        - request (str): Natural language request
        - user_id (str): User submitting the request

    Returns:
        - request_id: Unique request identifier
        - status: parsing_complete|requires_clarification|parsing_failed
        - decomposed_request (optional): If parsing succeeded
        - ambiguities (optional): If clarification needed
        - out_of_scope (optional): If items out of scope
        - error (optional): If parsing failed
    """
    try:
        result = await service.submit_request(req.request, req.user_id)
        logger.info(f"Request submitted: {result.get('request_id')}")
        return result

    except ValueError as e:
        logger.error(f"Invalid request: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Request submission failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal error: {e}")


@router.get("/plan/{request_id}", response_model=dict)
async def get_plan(
    request_id: str,
    service: OrchestratorService = Depends(get_orchestrator_service),
) -> dict:
    """Generate a plan for a submitted request.

    Args:
        request_id: ID of previously submitted request

    Returns:
        - plan_id: Unique plan identifier
        - request_id: Request this plan is for
        - tasks: List of tasks in plan
        - human_readable_summary: Summary for user review
        - complexity_level: simple|medium|complex
        - will_use_external_ai: Whether Claude will be used
        - status: pending_approval|planning_failed
    """
    try:
        result = await service.generate_plan(request_id)
        logger.info(f"Plan generated: {result.get('plan_id')}")
        return result

    except ValueError as e:
        logger.error(f"Plan not found: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Plan generation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal error: {e}")


@router.post("/plan/{plan_id}/approve", response_model=dict)
async def approve_plan(
    plan_id: str,
    req: ApprovalRequest,
    service: OrchestratorService = Depends(get_orchestrator_service),
) -> dict:
    """Approve or reject a generated plan.

    Args:
        plan_id: ID of plan to approve/reject
        req: ApprovalRequest with approved flag and user_id

    Returns:
        - plan_id: Plan ID
        - status: approved|rejected
        - dispatch_started (optional): True if dispatch started
        - error (optional): Error message if failed
    """
    try:
        result = await service.approve_plan(plan_id, req.approved)
        logger.info(f"Plan approval result: {plan_id} -> {result.get('status')}")
        return result

    except ValueError as e:
        logger.error(f"Invalid plan: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Plan approval failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal error: {e}")


@router.get("/plan/{plan_id}/status", response_model=dict)
async def get_plan_status(
    plan_id: str,
    service: OrchestratorService = Depends(get_orchestrator_service),
) -> dict:
    """Get execution status of a plan.

    Args:
        plan_id: ID of plan to query

    Returns:
        - plan_id: Plan ID
        - request_id: Request ID
        - status: pending|approved|executing|completed|failed
        - complexity_level: Plan complexity
        - will_use_external_ai: Whether Claude is/was used
        - tasks: List of tasks
        - created_at: Creation timestamp
        - approved_at: Approval timestamp
    """
    try:
        result = await service.get_plan_status(plan_id)
        logger.info(f"Plan status: {plan_id} -> {result.get('status')}")
        return result

    except ValueError as e:
        logger.error(f"Plan not found: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Status query failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal error: {e}")
