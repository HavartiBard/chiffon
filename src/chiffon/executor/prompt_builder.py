"""Build prompts for local LLM with injected skills."""

from typing import List, Optional

from chiffon.skills.registry import SkillsRegistry


class PromptBuilder:
    """Builds structured prompts for local LLM inference."""

    SYSTEM_MESSAGE = """You are an infrastructure file generator for a homelab Ansible codebase.
Given a task, output the exact file content requested — complete, production-ready YAML or Jinja2.

Respond using exactly these three Markdown headers in order:

## Plan
Write 1-3 sentences describing what you are generating.

## Code
Write the COMPLETE file content starting with a comment line showing the target path:
# File: ansible/roles/example/defaults/main.yml
---
variable_one: value
variable_two: "{{ vault_variable }}"

Include every value from the task spec. No placeholders. No truncation.

## Verification
Write one ansible command to verify the file, e.g.:
ansible-playbook playbooks/deploy.yml --syntax-check
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
        prompt += """Now generate the file. Start with ## Plan, then ## Code, then ## Verification.
"""

        return prompt
