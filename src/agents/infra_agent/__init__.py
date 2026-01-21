"""Infrastructure agent for Ansible playbook orchestration.

Provides:
- InfraAgent: Main agent class for infrastructure task execution
- PlaybookDiscovery: Service for discovering and cataloging Ansible playbooks
- PlaybookMetadata: Data model for playbook metadata
"""

from .agent import InfraAgent

__all__ = ["InfraAgent"]
