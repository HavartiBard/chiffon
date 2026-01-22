"""Template Generator for Ansible playbook scaffolds.

Generates Galaxy-compliant playbook templates for common homelab services.
Follows Ansible best practices and homelab conventions.
"""

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from jinja2 import Environment, FileSystemLoader, TemplateNotFound
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)


class InvalidServiceNameError(ValueError):
    """Raised when service name fails validation."""

    pass


class TemplateRenderError(Exception):
    """Raised when template rendering fails."""

    pass


class GeneratedTemplate(BaseModel):
    """Result of template generation containing all generated files.

    Attributes:
        service_name: Normalized service name (lowercase, dashes)
        playbook_content: Rendered main playbook YAML
        role_structure: Dict mapping relative paths to rendered content
        readme_content: Rendered README markdown
        generated_at: Timestamp of generation
        output_paths: Suggested file paths for writing to disk
    """

    service_name: str
    playbook_content: str
    role_structure: dict[str, str] = Field(default_factory=dict)
    readme_content: str
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    output_paths: list[str] = Field(default_factory=list)

    @field_validator("service_name")
    @classmethod
    def validate_service_name(cls, v: str) -> str:
        """Validate service name format."""
        if not v:
            raise InvalidServiceNameError("Service name cannot be empty")
        if len(v) > 50:
            raise InvalidServiceNameError("Service name must be 50 characters or less")
        if not re.match(r"^[a-z0-9-]+$", v):
            raise InvalidServiceNameError(
                "Service name must contain only lowercase letters, numbers, and dashes"
            )
        return v


class TemplateGenerator:
    """Generates Ansible playbook scaffolds using Jinja2 templates.

    Creates Galaxy-compliant playbooks with:
    - Main playbook file with chiffon metadata
    - Role structure (tasks, handlers, defaults, meta)
    - README documentation
    """

    def __init__(self, templates_dir: Optional[Path] = None):
        """Initialize template generator.

        Args:
            templates_dir: Path to Jinja2 templates directory
                          (defaults to ./templates relative to this file)
        """
        self.templates_dir = templates_dir or Path(__file__).parent / "templates"

        if not self.templates_dir.exists():
            raise FileNotFoundError(f"Templates directory not found: {self.templates_dir}")

        self.env = Environment(
            loader=FileSystemLoader(str(self.templates_dir)),
            trim_blocks=True,
            lstrip_blocks=True,
            keep_trailing_newline=True,
        )

        logger.info(f"TemplateGenerator initialized: templates_dir={self.templates_dir}")

    def _normalize_service_name(self, service_name: str) -> str:
        """Normalize service name to lowercase with dashes.

        Args:
            service_name: Raw service name

        Returns:
            Normalized service name

        Raises:
            InvalidServiceNameError: If normalization produces invalid name
        """
        # Convert to lowercase
        normalized = service_name.lower()

        # Replace spaces and underscores with dashes
        normalized = normalized.replace(" ", "-").replace("_", "-")

        # Remove special characters (keep only alphanumeric and dashes)
        normalized = re.sub(r"[^a-z0-9-]", "", normalized)

        # Remove multiple consecutive dashes
        normalized = re.sub(r"-+", "-", normalized)

        # Remove leading/trailing dashes
        normalized = normalized.strip("-")

        # Validate result
        if not normalized:
            raise InvalidServiceNameError(
                f"Service name '{service_name}' produces empty normalized name"
            )

        return normalized

    def _render_template(self, template_name: str, context: dict[str, Any]) -> str:
        """Render a Jinja2 template with context.

        Args:
            template_name: Name of template file (e.g., "playbook.yml.j2")
            context: Template context variables

        Returns:
            Rendered template content

        Raises:
            TemplateRenderError: If template not found or rendering fails
        """
        try:
            template = self.env.get_template(template_name)
            return template.render(**context)
        except TemplateNotFound as e:
            raise TemplateRenderError(f"Template not found: {template_name}") from e
        except Exception as e:
            raise TemplateRenderError(f"Failed to render template {template_name}: {e}") from e

    def _build_role_structure(self, service_name: str, context: dict[str, Any]) -> dict[str, str]:
        """Build Galaxy-compliant role directory structure.

        Args:
            service_name: Normalized service name
            context: Template rendering context

        Returns:
            Dict mapping relative paths to rendered content
        """
        role_base = f"roles/{service_name}"

        structure = {
            f"{role_base}/tasks/main.yml": self._render_template("role_tasks_main.yml.j2", context),
            f"{role_base}/handlers/main.yml": self._render_template(
                "role_handlers_main.yml.j2", context
            ),
            f"{role_base}/defaults/main.yml": self._render_template(
                "role_defaults_main.yml.j2", context
            ),
            f"{role_base}/meta/main.yml": self._render_template("role_meta_main.yml.j2", context),
            # Placeholder directories (empty but documented)
            f"{role_base}/templates/.gitkeep": "# Placeholder for service config templates\n",
            f"{role_base}/files/.gitkeep": "# Placeholder for static files\n",
        }

        return structure

    def _generate_output_paths(self, service_name: str) -> list[str]:
        """Generate suggested output paths for writing template to disk.

        Args:
            service_name: Normalized service name

        Returns:
            List of suggested file paths
        """
        return [
            f"{service_name}-deploy.yml",
            f"roles/{service_name}/tasks/main.yml",
            f"roles/{service_name}/handlers/main.yml",
            f"roles/{service_name}/defaults/main.yml",
            f"roles/{service_name}/meta/main.yml",
            f"roles/{service_name}/templates/.gitkeep",
            f"roles/{service_name}/files/.gitkeep",
            f"README-{service_name}.md",
        ]

    async def generate_template(
        self,
        service_name: str,
        description: Optional[str] = None,
        service_port: int = 8080,
        hosts: str = "all",
        become: bool = True,
        extra_vars: Optional[dict[str, Any]] = None,
    ) -> GeneratedTemplate:
        """Generate complete playbook template for a service.

        Args:
            service_name: Service name (will be normalized)
            description: Service description (optional)
            service_port: Default service port (default: 8080)
            hosts: Ansible hosts pattern (default: "all")
            become: Whether to use privilege escalation (default: True)
            extra_vars: Additional template variables (optional)

        Returns:
            GeneratedTemplate with all rendered content

        Raises:
            InvalidServiceNameError: If service name is invalid
            TemplateRenderError: If rendering fails
        """
        # Normalize service name
        normalized_name = self._normalize_service_name(service_name)
        logger.info(
            f"Generating template: original='{service_name}', normalized='{normalized_name}'"
        )

        # Build template context
        context = {
            "service_name": normalized_name,
            "description": description or f"Deploy {normalized_name} service",
            "service_port": service_port,
            "hosts": hosts,
            "become": "yes" if become else "no",
            "service_user": normalized_name,
            "service_group": normalized_name,
            **(extra_vars or {}),
        }

        # Render playbook
        playbook_content = self._render_template("playbook.yml.j2", context)

        # Build role structure
        role_structure = self._build_role_structure(normalized_name, context)

        # Render README
        readme_content = self._render_template("README.md.j2", context)

        # Generate output paths
        output_paths = self._generate_output_paths(normalized_name)

        template = GeneratedTemplate(
            service_name=normalized_name,
            playbook_content=playbook_content,
            role_structure=role_structure,
            readme_content=readme_content,
            output_paths=output_paths,
        )

        logger.info(
            f"Template generated successfully: service={normalized_name}, "
            f"files={len(role_structure) + 2}"
        )

        return template

    async def write_template_to_disk(
        self,
        template: GeneratedTemplate,
        output_dir: Path,
        overwrite: bool = False,
    ) -> list[Path]:
        """Write generated template to disk.

        Args:
            template: GeneratedTemplate to write
            output_dir: Base directory for output
            overwrite: If False, skip existing files (default: False)

        Returns:
            List of paths that were written

        Raises:
            FileExistsError: If file exists and overwrite=False
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        written_paths: list[Path] = []

        # Write main playbook
        playbook_path = output_dir / f"{template.service_name}-deploy.yml"
        if playbook_path.exists() and not overwrite:
            logger.warning(f"Skipping existing file: {playbook_path}")
        else:
            playbook_path.write_text(template.playbook_content)
            written_paths.append(playbook_path)
            logger.debug(f"Wrote playbook: {playbook_path}")

        # Write role structure
        for rel_path, content in template.role_structure.items():
            file_path = output_dir / rel_path
            file_path.parent.mkdir(parents=True, exist_ok=True)

            if file_path.exists() and not overwrite:
                logger.warning(f"Skipping existing file: {file_path}")
            else:
                file_path.write_text(content)
                written_paths.append(file_path)
                logger.debug(f"Wrote role file: {file_path}")

        # Write README
        readme_path = output_dir / f"README-{template.service_name}.md"
        if readme_path.exists() and not overwrite:
            logger.warning(f"Skipping existing file: {readme_path}")
        else:
            readme_path.write_text(template.readme_content)
            written_paths.append(readme_path)
            logger.debug(f"Wrote README: {readme_path}")

        logger.info(
            f"Template written to disk: output_dir={output_dir}, "
            f"files_written={len(written_paths)}"
        )

        return written_paths
