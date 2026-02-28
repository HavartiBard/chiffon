"""Build prompts for local LLM with injected skills."""

from typing import List, Optional, Tuple

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
        self.registry = registry

    def build_prompt(
        self,
        task_yaml: str,
        skills: Optional[List[str]] = None,
        max_context_tokens: int = 4000,
    ) -> Tuple[str, str]:
        """Build system and user messages for the LLM.

        Returns:
            (system_message, user_message) tuple for use in the messages array.
        """
        if skills is None:
            skills = []

        user_message = ""

        # Inject skills into the user message, gated by token budget.
        if skills:
            tokens_used = 0
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
                user_message += "## REFERENCE PATTERNS\n\n"
                user_message += skills_block

        user_message += "## YOUR TASK\n\n"
        user_message += "```yaml\n"
        user_message += task_yaml
        user_message += "\n```\n\n"
        user_message += "Now generate the file. Start with ## Plan, then ## Code, then ## Verification.\n"

        return self.SYSTEM_MESSAGE.strip(), user_message
