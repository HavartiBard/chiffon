"""Tests for TemplateGenerator service.

Comprehensive test suite covering:
- Template generation
- Service name validation and normalization
- Template rendering
- Writing to disk
- InfraAgent integration
"""

import json
import tempfile
from pathlib import Path
from uuid import uuid4

import pytest
import yaml

from src.agents.infra_agent.template_generator import (
    GeneratedTemplate,
    InvalidServiceNameError,
    TemplateGenerator,
    TemplateRenderError,
)
from src.common.protocol import WorkRequest


class TestGeneratedTemplate:
    """Test GeneratedTemplate Pydantic model."""

    def test_valid_template_creation(self):
        """Test creating a valid GeneratedTemplate."""
        template = GeneratedTemplate(
            service_name="myapp",
            playbook_content="---\n# test playbook\n",
            role_structure={"roles/myapp/tasks/main.yml": "---\n# tasks\n"},
            readme_content="# MyApp\n",
            output_paths=["myapp-deploy.yml", "README-myapp.md"],
        )

        assert template.service_name == "myapp"
        assert template.playbook_content.startswith("---")
        assert len(template.role_structure) == 1
        assert template.readme_content.startswith("#")
        assert len(template.output_paths) == 2

    def test_generated_at_auto_populated(self):
        """Test that generated_at is auto-populated."""
        template = GeneratedTemplate(
            service_name="test",
            playbook_content="---",
            readme_content="#",
        )

        assert template.generated_at is not None

    def test_service_name_validation_empty(self):
        """Test that empty service name is rejected."""
        from pydantic import ValidationError

        with pytest.raises((InvalidServiceNameError, ValidationError)):
            GeneratedTemplate(
                service_name="",
                playbook_content="---",
                readme_content="#",
            )

    def test_service_name_validation_too_long(self):
        """Test that service names >50 chars are rejected."""
        from pydantic import ValidationError

        long_name = "a" * 51
        with pytest.raises((InvalidServiceNameError, ValidationError)):
            GeneratedTemplate(
                service_name=long_name,
                playbook_content="---",
                readme_content="#",
            )

    def test_service_name_validation_invalid_chars(self):
        """Test that service names with invalid characters are rejected."""
        from pydantic import ValidationError

        with pytest.raises((InvalidServiceNameError, ValidationError)):
            GeneratedTemplate(
                service_name="my_app!",
                playbook_content="---",
                readme_content="#",
            )

    def test_required_paths_in_role_structure(self):
        """Test that role structure contains expected paths."""
        template = GeneratedTemplate(
            service_name="test",
            playbook_content="---",
            readme_content="#",
            role_structure={
                "roles/test/tasks/main.yml": "---",
                "roles/test/handlers/main.yml": "---",
                "roles/test/defaults/main.yml": "---",
                "roles/test/meta/main.yml": "---",
            },
        )

        assert "roles/test/tasks/main.yml" in template.role_structure
        assert "roles/test/handlers/main.yml" in template.role_structure
        assert "roles/test/defaults/main.yml" in template.role_structure
        assert "roles/test/meta/main.yml" in template.role_structure

    def test_output_paths_populated(self):
        """Test that output_paths contains suggested file paths."""
        template = GeneratedTemplate(
            service_name="myservice",
            playbook_content="---",
            readme_content="#",
            output_paths=[
                "myservice-deploy.yml",
                "roles/myservice/tasks/main.yml",
                "README-myservice.md",
            ],
        )

        assert "myservice-deploy.yml" in template.output_paths
        assert any("tasks/main.yml" in p for p in template.output_paths)
        assert any("README" in p for p in template.output_paths)


class TestServiceNameValidation:
    """Test service name validation and normalization."""

    @pytest.mark.asyncio
    async def test_valid_service_names(self):
        """Test that valid service names are accepted."""
        generator = TemplateGenerator()

        valid_names = ["myapp", "my-app", "app123", "a1b2c3"]

        for name in valid_names:
            template = await generator.generate_template(name)
            assert template.service_name == name

    @pytest.mark.asyncio
    async def test_normalize_spaces_to_dashes(self):
        """Test that spaces are normalized to dashes."""
        generator = TemplateGenerator()

        template = await generator.generate_template("my app")
        assert template.service_name == "my-app"

    @pytest.mark.asyncio
    async def test_normalize_underscores_to_dashes(self):
        """Test that underscores are normalized to dashes."""
        generator = TemplateGenerator()

        template = await generator.generate_template("my_app")
        assert template.service_name == "my-app"

    @pytest.mark.asyncio
    async def test_normalize_mixed_spaces_underscores(self):
        """Test that mixed spaces/underscores are normalized."""
        generator = TemplateGenerator()

        template = await generator.generate_template("my app_service")
        assert template.service_name == "my-app-service"

    @pytest.mark.asyncio
    async def test_normalize_uppercase_to_lowercase(self):
        """Test that uppercase is normalized to lowercase."""
        generator = TemplateGenerator()

        template = await generator.generate_template("MyApp")
        assert template.service_name == "myapp"

    @pytest.mark.asyncio
    async def test_normalize_remove_special_chars(self):
        """Test that special characters are removed."""
        generator = TemplateGenerator()

        template = await generator.generate_template("my@app#123")
        assert template.service_name == "myapp123"

    @pytest.mark.asyncio
    async def test_normalize_multiple_dashes(self):
        """Test that multiple consecutive dashes are collapsed."""
        generator = TemplateGenerator()

        template = await generator.generate_template("my---app")
        assert template.service_name == "my-app"

    @pytest.mark.asyncio
    async def test_normalize_leading_trailing_dashes(self):
        """Test that leading/trailing dashes are removed."""
        generator = TemplateGenerator()

        template = await generator.generate_template("-myapp-")
        assert template.service_name == "myapp"

    @pytest.mark.asyncio
    async def test_invalid_empty_name(self):
        """Test that empty service name raises error."""
        generator = TemplateGenerator()

        with pytest.raises(InvalidServiceNameError, match="empty"):
            await generator.generate_template("")

    @pytest.mark.asyncio
    async def test_invalid_special_chars_only(self):
        """Test that service name with only special chars raises error."""
        generator = TemplateGenerator()

        with pytest.raises(InvalidServiceNameError, match="empty normalized name"):
            await generator.generate_template("@#$%")


class TestTemplateRendering:
    """Test template rendering with Jinja2."""

    @pytest.mark.asyncio
    async def test_service_name_substitution(self):
        """Test that service name is correctly substituted in templates."""
        generator = TemplateGenerator()

        template = await generator.generate_template("testapp")

        assert "testapp" in template.playbook_content
        assert "testapp" in template.readme_content

    @pytest.mark.asyncio
    async def test_metadata_comments_in_playbook(self):
        """Test that chiffon metadata comments are in playbook."""
        generator = TemplateGenerator()

        template = await generator.generate_template("myapp", description="Test service")

        assert "chiffon:service=myapp" in template.playbook_content
        assert "chiffon:description=" in template.playbook_content

    @pytest.mark.asyncio
    async def test_rendered_playbook_valid_yaml(self):
        """Test that rendered playbook is valid YAML."""
        generator = TemplateGenerator()

        template = await generator.generate_template("testapp")

        # Parse YAML to verify syntax
        parsed = yaml.safe_load(template.playbook_content)
        assert isinstance(parsed, list)
        assert len(parsed) == 1
        assert parsed[0]["name"].startswith("Deploy")

    @pytest.mark.asyncio
    async def test_rendered_role_tasks_valid_yaml(self):
        """Test that rendered role tasks are valid YAML."""
        generator = TemplateGenerator()

        template = await generator.generate_template("testapp")

        tasks_content = template.role_structure["roles/testapp/tasks/main.yml"]
        parsed = yaml.safe_load(tasks_content)
        assert isinstance(parsed, list)
        assert len(parsed) > 0

    @pytest.mark.asyncio
    async def test_rendered_role_handlers_valid_yaml(self):
        """Test that rendered role handlers are valid YAML."""
        generator = TemplateGenerator()

        template = await generator.generate_template("testapp")

        handlers_content = template.role_structure["roles/testapp/handlers/main.yml"]
        parsed = yaml.safe_load(handlers_content)
        assert isinstance(parsed, list)
        assert len(parsed) > 0

    @pytest.mark.asyncio
    async def test_rendered_role_defaults_valid_yaml(self):
        """Test that rendered role defaults are valid YAML."""
        generator = TemplateGenerator()

        template = await generator.generate_template("testapp")

        defaults_content = template.role_structure["roles/testapp/defaults/main.yml"]
        parsed = yaml.safe_load(defaults_content)
        assert isinstance(parsed, dict)

    @pytest.mark.asyncio
    async def test_rendered_role_meta_valid_yaml(self):
        """Test that rendered role meta is valid YAML."""
        generator = TemplateGenerator()

        template = await generator.generate_template("testapp")

        meta_content = template.role_structure["roles/testapp/meta/main.yml"]
        parsed = yaml.safe_load(meta_content)
        assert isinstance(parsed, dict)
        assert "galaxy_info" in parsed

    @pytest.mark.asyncio
    async def test_readme_contains_service_name(self):
        """Test that README contains service name."""
        generator = TemplateGenerator()

        template = await generator.generate_template("myservice")

        assert "myservice" in template.readme_content.lower()


class TestTemplateGeneration:
    """Test end-to-end template generation."""

    @pytest.mark.asyncio
    async def test_generate_with_defaults(self):
        """Test template generation with default parameters."""
        generator = TemplateGenerator()

        template = await generator.generate_template("testapp")

        assert template.service_name == "testapp"
        assert "8080" in template.playbook_content  # default port
        assert "hosts: all" in template.playbook_content  # default hosts

    @pytest.mark.asyncio
    async def test_generate_with_custom_port(self):
        """Test template generation with custom port."""
        generator = TemplateGenerator()

        template = await generator.generate_template("testapp", service_port=9090)

        assert "9090" in template.playbook_content

    @pytest.mark.asyncio
    async def test_generate_with_custom_hosts(self):
        """Test template generation with custom hosts pattern."""
        generator = TemplateGenerator()

        template = await generator.generate_template("testapp", hosts="webservers")

        assert "hosts: webservers" in template.playbook_content

    @pytest.mark.asyncio
    async def test_generate_with_custom_become(self):
        """Test template generation with become=False."""
        generator = TemplateGenerator()

        template = await generator.generate_template("testapp", become=False)

        assert "become: no" in template.playbook_content

    @pytest.mark.asyncio
    async def test_generate_with_description(self):
        """Test template generation with description."""
        generator = TemplateGenerator()

        template = await generator.generate_template("testapp", description="My test application")

        assert "My test application" in template.playbook_content

    @pytest.mark.asyncio
    async def test_generate_with_extra_vars(self):
        """Test template generation with extra variables."""
        generator = TemplateGenerator()

        template = await generator.generate_template(
            "testapp", extra_vars={"custom_var": "custom_value"}
        )

        # Extra vars should be in context, though may not appear in rendered output
        # Just verify generation doesn't fail
        assert template.service_name == "testapp"

    @pytest.mark.asyncio
    async def test_role_structure_has_all_files(self):
        """Test that role structure contains all required files."""
        generator = TemplateGenerator()

        template = await generator.generate_template("testapp")

        expected_paths = [
            "roles/testapp/tasks/main.yml",
            "roles/testapp/handlers/main.yml",
            "roles/testapp/defaults/main.yml",
            "roles/testapp/meta/main.yml",
            "roles/testapp/templates/.gitkeep",
            "roles/testapp/files/.gitkeep",
        ]

        for path in expected_paths:
            assert path in template.role_structure

    @pytest.mark.asyncio
    async def test_output_paths_match_role_structure(self):
        """Test that output_paths align with role_structure."""
        generator = TemplateGenerator()

        template = await generator.generate_template("testapp")

        # Check that key role files are in output_paths
        assert any("tasks/main.yml" in p for p in template.output_paths)
        assert any("handlers/main.yml" in p for p in template.output_paths)
        assert any("defaults/main.yml" in p for p in template.output_paths)
        assert any("meta/main.yml" in p for p in template.output_paths)


class TestWriteToDisk:
    """Test writing generated templates to disk."""

    @pytest.mark.asyncio
    async def test_write_creates_files(self):
        """Test that write_template_to_disk creates files."""
        generator = TemplateGenerator()
        template = await generator.generate_template("testapp")

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            written_paths = await generator.write_template_to_disk(template, output_dir)

            assert len(written_paths) > 0
            for path in written_paths:
                assert path.exists()

    @pytest.mark.asyncio
    async def test_write_creates_directories(self):
        """Test that write_template_to_disk creates directories."""
        generator = TemplateGenerator()
        template = await generator.generate_template("testapp")

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            await generator.write_template_to_disk(template, output_dir)

            # Check role directories exist
            role_dir = output_dir / "roles" / "testapp"
            assert role_dir.exists()
            assert (role_dir / "tasks").exists()
            assert (role_dir / "handlers").exists()
            assert (role_dir / "defaults").exists()
            assert (role_dir / "meta").exists()

    @pytest.mark.asyncio
    async def test_write_playbook_file(self):
        """Test that playbook file is written correctly."""
        generator = TemplateGenerator()
        template = await generator.generate_template("testapp")

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            await generator.write_template_to_disk(template, output_dir)

            playbook_path = output_dir / "testapp-deploy.yml"
            assert playbook_path.exists()
            content = playbook_path.read_text()
            assert "testapp" in content

    @pytest.mark.asyncio
    async def test_write_readme_file(self):
        """Test that README file is written correctly."""
        generator = TemplateGenerator()
        template = await generator.generate_template("testapp")

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            await generator.write_template_to_disk(template, output_dir)

            readme_path = output_dir / "README-testapp.md"
            assert readme_path.exists()
            content = readme_path.read_text()
            assert "testapp" in content.lower()

    @pytest.mark.asyncio
    async def test_write_skip_existing_files(self):
        """Test that existing files are skipped when overwrite=False."""
        generator = TemplateGenerator()
        template = await generator.generate_template("testapp")

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)

            # First write
            written_paths_1 = await generator.write_template_to_disk(template, output_dir)
            original_count = len(written_paths_1)

            # Second write (should skip existing)
            written_paths_2 = await generator.write_template_to_disk(
                template, output_dir, overwrite=False
            )

            # Should skip all existing files
            assert len(written_paths_2) == 0

    @pytest.mark.asyncio
    async def test_write_overwrite_existing_files(self):
        """Test that existing files are overwritten when overwrite=True."""
        generator = TemplateGenerator()
        template = await generator.generate_template("testapp")

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)

            # First write
            written_paths_1 = await generator.write_template_to_disk(template, output_dir)
            original_count = len(written_paths_1)

            # Second write with overwrite=True
            written_paths_2 = await generator.write_template_to_disk(
                template, output_dir, overwrite=True
            )

            # Should overwrite all files
            assert len(written_paths_2) == original_count


class TestInfraAgentTemplateGeneration:
    """Test InfraAgent integration with TemplateGenerator."""

    @pytest.fixture
    def agent(self, monkeypatch, tmp_path):
        """Create InfraAgent for testing."""
        from src.agents.infra_agent.agent import InfraAgent
        from src.common.config import Config

        # Set environment variables for Config
        monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost/test")
        monkeypatch.setenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")

        config = Config()

        # Create a temporary repo directory so PlaybookDiscovery doesn't fail
        repo_path = tmp_path / "ansible"
        repo_path.mkdir(parents=True, exist_ok=True)

        # Use the temporary repo path
        return InfraAgent(agent_id="test-agent", config=config, repo_path=str(repo_path))

    @pytest.mark.asyncio
    async def test_agent_handles_generate_template_work_type(self, agent):
        """Test that InfraAgent handles generate_template work type."""
        work_request = WorkRequest(
            task_id=uuid4(),
            work_type="generate_template",
            parameters={"service_name": "testapp"},
        )

        result = await agent.execute_work(work_request)

        assert result.status == "completed"
        assert result.exit_code == 0
        assert "testapp" in result.output

    @pytest.mark.asyncio
    async def test_agent_template_output_format(self, agent):
        """Test that InfraAgent returns properly formatted template output."""
        work_request = WorkRequest(
            task_id=uuid4(),
            work_type="generate_template",
            parameters={
                "service_name": "myapp",
                "description": "My test app",
                "service_port": 9090,
            },
        )

        result = await agent.execute_work(work_request)

        # Parse JSON output
        output_data = json.loads(result.output)

        assert output_data["service_name"] == "myapp"
        assert "playbook_content" in output_data
        assert "role_structure" in output_data
        assert "readme_content" in output_data
        assert "output_paths" in output_data

    @pytest.mark.asyncio
    async def test_agent_write_to_disk_parameter(self, agent):
        """Test that InfraAgent respects write_to_disk parameter."""
        with tempfile.TemporaryDirectory() as tmpdir:
            work_request = WorkRequest(
                task_id=uuid4(),
                work_type="generate_template",
                parameters={
                    "service_name": "writetest",
                    "write_to_disk": True,
                    "output_dir": tmpdir,
                },
            )

            result = await agent.execute_work(work_request)

            # Parse output
            output_data = json.loads(result.output)

            # Should have written_paths populated
            assert len(output_data["written_paths"]) > 0

            # Verify files exist
            for path_str in output_data["written_paths"]:
                path = Path(path_str)
                assert path.exists()

    @pytest.mark.asyncio
    async def test_agent_missing_service_name_parameter(self, agent):
        """Test that InfraAgent returns error for missing service_name."""
        work_request = WorkRequest(
            task_id=uuid4(),
            work_type="generate_template",
            parameters={},  # Missing service_name
        )

        result = await agent.execute_work(work_request)

        assert result.status == "failed"
        assert result.exit_code == 1
        assert "service_name" in result.output.lower()

    @pytest.mark.asyncio
    async def test_agent_invalid_service_name(self, agent):
        """Test that InfraAgent handles invalid service names."""
        work_request = WorkRequest(
            task_id=uuid4(),
            work_type="generate_template",
            parameters={"service_name": "@#$%"},  # Invalid characters
        )

        result = await agent.execute_work(work_request)

        assert result.status == "failed"
        assert result.exit_code == 1
