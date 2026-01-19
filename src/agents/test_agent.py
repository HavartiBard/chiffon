"""Test agent for validation and local development.

Provides simple work types (echo, slow_echo, fail) for integration testing
without depending on real infrastructure (Ansible, Docker, etc).
"""

import asyncio
import logging
import time
from typing import Any
from uuid import uuid4

from src.agents.base import BaseAgent
from src.common.config import Config
from src.common.protocol import WorkRequest, WorkResult

logger = logging.getLogger(__name__)


class TestAgent(BaseAgent):
    """Simple test agent for development and validation.

    Supports work types:
    - echo: Return the input as output (immediate, trivial)
    - slow_echo: Sleep 5 seconds, then return input (test timeouts/long work)
    - fail: Raise an exception (test error handling)
    """

    def __init__(self, config: Config, agent_id: str = "test-agent-001"):
        """Initialize test agent.

        Args:
            config: Configuration object with RabbitMQ connection details
            agent_id: Unique agent identifier (default: test-agent-001)
        """
        super().__init__(
            agent_id=agent_id,
            agent_type="infra",  # Pretend to be infra for testing
            config=config,
        )

    def get_agent_capabilities(self) -> dict[str, Any]:
        """Report what work types this test agent can handle.

        Returns:
            Dict mapping work type to boolean support
        """
        return {
            "test": True,
            "echo": True,
            "slow_echo": True,
            "fail": True,
        }

    async def execute_work(self, work_request: WorkRequest) -> WorkResult:
        """Execute test work request.

        Handles three work types:
        - echo: Return parameters as output
        - slow_echo: Sleep 5 seconds, return parameters
        - fail: Raise an exception

        Args:
            work_request: Work request with task_id, work_type, parameters

        Returns:
            WorkResult with status, output, exit_code, duration_ms
        """
        start_time = time.time()
        work_type = work_request.work_type
        parameters = work_request.parameters
        output = ""
        status = "completed"
        exit_code = 0
        error_message = None

        try:
            if work_type == "echo":
                # Trivial: return input as output
                output = f"Echo: {parameters.get('message', 'no message')}"
                self.logger.info(f"Echo work completed: {output}")

            elif work_type == "slow_echo":
                # Sleep 5 seconds, then echo
                self.logger.info("Starting slow echo work (sleeping 5 seconds)")
                await asyncio.sleep(5)
                output = f"Slow echo (after 5s): {parameters.get('message', 'no message')}"
                self.logger.info(f"Slow echo work completed: {output}")

            elif work_type == "fail":
                # Intentional failure for testing error handling
                error_msg = parameters.get("error_message", "Test failure")
                self.logger.error(f"Simulating work failure: {error_msg}")
                raise RuntimeError(error_msg)

            else:
                # Unknown work type
                status = "failed"
                exit_code = 1
                error_message = f"Unknown work type: {work_type}"
                output = error_message
                self.logger.warning(output)

        except Exception as e:
            # Catch exceptions and convert to error result
            status = "failed"
            exit_code = 1
            error_message = str(e)
            output = f"Error executing {work_type}: {e}"
            self.logger.error(f"Work execution error: {e}", exc_info=True)

        # Calculate duration
        duration_seconds = time.time() - start_time
        duration_ms = int(duration_seconds * 1000)

        # Return result
        result = WorkResult(
            task_id=work_request.task_id,
            status=status,
            exit_code=exit_code,
            output=output,
            error_message=error_message,
            duration_ms=duration_ms,
            agent_id=uuid4(),
            resources_used={
                "cpu_time_ms": int(duration_seconds * 1000),
                "memory_peak_mb": 0,  # Not tracked for test agent
                "gpu_memory_used_mb": 0,
            },
        )

        return result


async def main():
    """Main entry point for running test agent standalone.

    Usage:
        poetry run python -m src.agents.test_agent

    The agent will connect to RabbitMQ and listen for work requests.
    """
    config = Config()
    agent = TestAgent(config)

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    logger.info(f"Starting test agent: {agent.agent_id}")
    try:
        await agent.run()
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received, stopping agent")


if __name__ == "__main__":
    asyncio.run(main())
