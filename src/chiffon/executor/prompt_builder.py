"""Build prompts for local LLM with injected skills."""

from typing import List, Optional

from chiffon.skills.registry import SkillsRegistry


class PromptBuilder:
    """Builds structured prompts for local LLM inference."""

    SYSTEM_MESSAGE = """You are a code executor assistant. Your job is to:
1. Understand the task requirements
2. Create a detailed execution plan
3. Generate code to accomplish the task
4. Follow the patterns and best practices in the provided skills

Always structure your response as:
## PLAN
[Step-by-step plan to accomplish task]

## CODE
[Python/shell code to execute the plan]

## VERIFICATION
[How to verify the code works]
"""

    def __init__(self, registry: SkillsRegistry):
        """Initialize prompt builder with skills registry.

        Args:
            registry: SkillsRegistry instance for loading skills
        """
        self.registry = registry

    def build_prompt(
        self,
        task_yaml: str,
        skills: Optional[List[str]] = None,
        max_context_tokens: int = 4000,
    ) -> str:
        """Build complete prompt with task and injected skills.

        Args:
            task_yaml: Task YAML content
            skills: List of skill names to inject
            max_context_tokens: Maximum tokens for skill injection

        Returns:
            Complete prompt for LLM
        """
        if skills is None:
            skills = []

        prompt = self.SYSTEM_MESSAGE + "\n\n"

        # Inject skills with headers, gated by the token budget.
        # The system message and task YAML are always included; only skill
        # content is subject to the limit.  Approximation: 4 chars ≈ 1 token.
        if skills:
            tokens_used = len(prompt) // 4  # chars already committed
            skills_block = ""
            for skill_name in skills:
                content = self.registry.get_skill_content(skill_name)
                if not content:
                    continue
                header = f"### Pattern: {skill_name.replace('-', ' ').title()} ({skill_name})\n"
                skill_chunk = header + content + "\n\n"
                skill_tokens = len(skill_chunk) // 4
                if tokens_used + skill_tokens > max_context_tokens:
                    continue
                skills_block += skill_chunk
                tokens_used += skill_tokens
            if skills_block:
                prompt += "## REFERENCE PATTERNS\n\n"
                prompt += skills_block

        # Add task
        prompt += "## YOUR TASK\n\n"
        prompt += "```yaml\n"
        prompt += task_yaml
        prompt += "\n```\n\n"

        # Add execution instructions
        prompt += """## EXECUTION INSTRUCTIONS

1. Read the task YAML carefully
2. Reference the patterns provided above
3. Create your execution plan (think step-by-step)
4. Write the code to accomplish it
5. Describe how to verify it works

Start your response with ## PLAN
"""

        return prompt
