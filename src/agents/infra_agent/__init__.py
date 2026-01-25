"""Infrastructure agent for Ansible playbook orchestration.

Provides:
- InfraAgent: Main agent class for infrastructure task execution
- PlaybookDiscovery: Service for discovering and cataloging Ansible playbooks
- PlaybookMetadata: Data model for playbook metadata
- TaskMapper: Service for mapping task intents to playbooks
- MappingResult: Result of task-to-playbook mapping
- PlaybookExecutor: Service for executing Ansible playbooks
- ExecutionSummary: Structured summary of playbook execution
- PlaybookAnalyzer: Service for analyzing playbooks with ansible-lint
- Suggestion: Individual improvement suggestion from analysis
- AnalysisResult: Complete analysis result with categorized suggestions
- TemplateGenerator: Service for generating Ansible playbook templates
- GeneratedTemplate: Generated playbook template with role structure
"""

from .agent import InfraAgent
from .analyzer import AnalysisResult, PlaybookAnalyzer, Suggestion
from .executor import ExecutionSummary, PlaybookExecutor
from .playbook_discovery import PlaybookDiscovery, PlaybookMetadata
from .task_mapper import MappingResult, TaskMapper
from .template_generator import GeneratedTemplate, TemplateGenerator

__all__ = [
    "InfraAgent",
    "PlaybookDiscovery",
    "PlaybookMetadata",
    "TaskMapper",
    "MappingResult",
    "PlaybookExecutor",
    "ExecutionSummary",
    "PlaybookAnalyzer",
    "Suggestion",
    "AnalysisResult",
    "TemplateGenerator",
    "GeneratedTemplate",
]
