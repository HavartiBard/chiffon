"""Tests for skills registry infrastructure."""

import pytest
import yaml
from pathlib import Path
from chiffon.skills.registry import SkillsRegistry


@pytest.fixture(scope="module")
def registry():
    return SkillsRegistry(Path(__file__).parent.parent / "src" / "chiffon" / "skills")


def test_registry_loads_skills(registry):
    """Test that registry loads and indexes skills."""
    skills = registry.get_all_skills()
    assert len(skills) > 0
    assert "yaml-validation" in skills


def test_registry_gets_skill_metadata(registry):
    """Test retrieving skill metadata."""
    meta = registry.get_skill_metadata("yaml-validation")
    assert meta["domains"]
    assert meta["languages"]
    assert meta["tokens"]


def test_select_skills_by_domains(registry):
    """Test skill selection by domain."""
    selected = registry.select_skills(
        domains=["testing", "implementation"],
        max_tokens=1000
    )
    assert "test-driven-development" in selected


def test_get_skill_content_returns_content_for_all_skills(registry):
    """Test that get_skill_content() returns non-None for all registered skills."""
    all_skills = registry.get_all_skills().keys()
    for skill_name in all_skills:
        content = registry.get_skill_content(skill_name)
        assert content is not None, f"Expected content for skill '{skill_name}', got None"
        assert len(content) > 0, f"Expected non-empty content for skill '{skill_name}'"
