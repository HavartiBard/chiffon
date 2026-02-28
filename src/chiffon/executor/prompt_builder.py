"""Build prompts for local LLM with injected skills."""

from typing import List, Optional

from chiffon.skills.registry import SkillsRegistry


class PromptBuilder:
    """Builds structured prompts for local LLM inference."""

    SYSTEM_MESSAGE = """You are an infrastructure file generator for a homelab Ansible codebase.
Your job is to generate the exact file content specified in the task — complete,
production-ready YAML, Jinja2 templates, or other config files.

Always structure your response with EXACTLY these three section headers:

## Plan
[Brief description of what you are generating and any key decisions]

## Code
[The complete file content — YAML, Jinja2, shell, etc. — ready to write to disk.
 Start with a comment line showing the target filepath, e.g.:
   # File: ansible/roles/komodo-core/defaults/main.yml
 Then output the full file content. No placeholders. No truncation.]

## Verification
[One or two commands that confirm the file is correct, e.g. ansible --syntax-check]
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
        prompt += """## Instructions

1. Read the task carefully — note the exact target filepath and every variable/value to include
2. Think through what the file should contain (## Plan)
3. Output the COMPLETE file content under ## Code — no placeholders, no truncation
4. Suggest a quick verification command under ## Verification

Start your response with ## Plan
"""

        return prompt
