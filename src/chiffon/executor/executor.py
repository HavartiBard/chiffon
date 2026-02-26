"""Main task executor with LLM integration."""

import logging
from pathlib import Path
from typing import Optional

from chiffon.executor.llm_client import LlamaClient
from chiffon.executor.prompt_builder import PromptBuilder
from chiffon.queue.file_queue import Task
from chiffon.skills.registry import SkillsRegistry


logger = logging.getLogger(__name__)


class TaskExecutor:
    """Executes tasks using local LLM with injected skills.

    Wires together :class:`SkillsRegistry`, :class:`PromptBuilder`, and
    :class:`LlamaClient` to provide a single :meth:`execute_task` entry
    point that turns a :class:`Task` into a structured result dict.
    """

    def __init__(
        self,
        repo_path: Path,
        queue_path: Path,
        llm_server_url: Optional[str] = None,
        skills_dir: Optional[Path] = None,
    ) -> None:
        """Initialize executor.

        Args:
            repo_path: Path to the git repository being operated on.
            queue_path: Path to the task queue directory.
            llm_server_url: URL for the llama.cpp server.  When omitted the
                            ``LLAMA_SERVER_URL`` env var (or the LlamaClient
                            default) is used.
            skills_dir: Path to the skills directory.  Defaults to the
                        ``skills/`` package that lives alongside this module.
        """
        self.repo_path = Path(repo_path)
        self.queue_path = Path(queue_path)

        # Initialize LLM client
        self.llm = LlamaClient(base_url=llm_server_url)

        # Initialize skills registry and prompt builder
        if skills_dir is None:
            skills_dir = Path(__file__).parent.parent / "skills"
        self.registry = SkillsRegistry(skills_dir)
        self.prompt_builder = PromptBuilder(self.registry)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_health(self) -> bool:
        """Verify the LLM server is reachable before executing tasks.

        Returns:
            ``True`` when the server responds healthy.

        Raises:
            RuntimeError: If the LLM server cannot be reached.
        """
        if not self.llm.health_check():
            raise RuntimeError(
                f"LLM server unreachable at {self.llm.base_url}. "
                "Ensure llama.cpp is running and LLAMA_SERVER_URL is correct."
            )
        logger.info("LLM health check passed: %s", self.llm.base_url)
        return True

    def build_execution_prompt(self, task: Task) -> str:
        """Build the full prompt for a task.

        Converts *task* to an inline YAML snippet and delegates to
        :class:`PromptBuilder` with the task's ``applicable_skills``.

        Args:
            task: Task whose details and skills will be embedded.

        Returns:
            Complete prompt string ready to send to the LLM.
        """
        task_yaml = (
            f"id: {task.id}\n"
            f"goal: {task.goal}\n"
            f"description: {task.description}\n"
            "\n"
            "scope:\n"
            f"  allowed_write_globs: {task.scope.get('allowed_write_globs', [])}\n"
            f"  allowed_read_globs: {task.scope.get('allowed_read_globs', [])}\n"
            "\n"
            "constraints:\n"
            f"  max_files_changed: {task.constraints.get('max_files_changed', 10)}\n"
            f"  max_diff_bytes: {task.constraints.get('max_diff_bytes', 50000)}\n"
            f"  timeout_seconds: {task.constraints.get('timeout_seconds', 300)}\n"
        )

        # Cap to 5 skills to keep prompt size reasonable
        skills = task.applicable_skills[:5]

        return self.prompt_builder.build_prompt(task_yaml=task_yaml, skills=skills)

    def parse_llm_response(self, response: str) -> dict:
        """Parse the raw LLM response into labelled sections.

        Splits on ``## <SECTION>`` headings (level-2 Markdown headers).
        Section names are lower-cased so callers can use ``result["plan"]``.
        Missing sections resolve to an empty string.

        Args:
            response: Raw text returned by :class:`LlamaClient`.

        Returns:
            Dict mapping section names (lowercase) to their text content.
            An empty or headerless response returns ``{}``.
        """
        sections: dict = {}
        current_section: Optional[str] = None
        current_lines: list = []

        for line in response.split("\n"):
            if line.startswith("## "):
                # Flush the previous section
                if current_section is not None:
                    sections[current_section] = "\n".join(current_lines).strip()
                current_section = line[3:].strip().lower()
                current_lines = []
            else:
                current_lines.append(line)

        # Flush the final section
        if current_section is not None:
            sections[current_section] = "\n".join(current_lines).strip()

        return sections

    async def execute_task(self, task: Task) -> dict:
        """Execute a task via local LLM inference.

        Full flow:
        1. Build the execution prompt from the task and its applicable skills.
        2. Call the LLM to generate a response.
        3. Parse the structured sections from the response.
        4. Return a result dict.

        Note: :meth:`check_health` is **not** called here; the caller (e.g.
        the CLI) is responsible for performing the health check before
        invoking this method.

        Args:
            task: Task to execute.

        Returns:
            On success::

                {
                    "success": True,
                    "plan": "<plan text>",
                    "code": "<code text>",
                    "verification": "<verification text>",
                }

            On failure::

                {"success": False, "error": "<error message>"}
        """
        logger.info("Executing task: %s", task.id)

        try:
            prompt = self.build_execution_prompt(task)
            logger.debug("Prompt length: %d chars", len(prompt))

            logger.info("Calling LLM for task reasoning...")
            response = self.llm.generate(prompt)

            sections = self.parse_llm_response(response)
            logger.info("LLM response parsed successfully")
            logger.debug("Plan preview: %.200s...", sections.get("plan", ""))

            return {
                "success": True,
                "plan": sections.get("plan", ""),
                "code": sections.get("code", ""),
                "verification": sections.get("verification", ""),
            }

        except Exception as exc:
            logger.error("Task execution failed: %s", exc)
            return {
                "success": False,
                "error": str(exc),
            }
