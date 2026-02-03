"""Registry for managing executor skills with metadata."""

import yaml
from pathlib import Path
from typing import Dict, List, Optional


class SkillsRegistry:
    """Manages skills registry and intelligent skill selection."""

    def __init__(self, skills_dir: Path):
        """Initialize registry from skills directory.

        Args:
            skills_dir: Path to directory containing skills/ with registry.yaml
        """
        self.skills_dir = Path(skills_dir)
        self.registry_file = self.skills_dir / "registry.yaml"
        self._skills = self._load_registry()

    def _load_registry(self) -> Dict:
        """Load skills registry from YAML."""
        if not self.registry_file.exists():
            return {}

        with open(self.registry_file) as f:
            data = yaml.safe_load(f)
        return data.get("skills", {})

    def get_all_skills(self) -> Dict:
        """Get all registered skills."""
        return self._skills

    def get_skill_metadata(self, skill_name: str) -> Optional[Dict]:
        """Get metadata for a specific skill."""
        return self._skills.get(skill_name)

    def get_skill_content(self, skill_name: str) -> Optional[str]:
        """Load full skill content from markdown file."""
        skill_file = self.skills_dir / f"{skill_name}.md"
        if not skill_file.exists():
            return None
        return skill_file.read_text()

    def select_skills(
        self,
        domains: Optional[List[str]] = None,
        languages: Optional[List[str]] = None,
        max_tokens: int = 2000,
    ) -> List[str]:
        """Intelligently select relevant skills based on constraints.

        Args:
            domains: Filter by domain (e.g., ["testing", "implementation"])
            languages: Filter by language (e.g., ["python"])
            max_tokens: Maximum total tokens for injected skills

        Returns:
            List of skill names to inject, ordered by relevance
        """
        selected = []
        token_budget = max_tokens

        for skill_name, meta in self._skills.items():
            # Check domain match
            if domains and not any(d in meta.get("domains", []) for d in domains):
                continue

            # Check language match
            if languages and not any(l in meta.get("languages", []) for l in languages):
                continue

            # Check token budget
            skill_tokens = meta.get("tokens", 0)
            if skill_tokens <= token_budget:
                selected.append(skill_name)
                token_budget -= skill_tokens

        return selected
