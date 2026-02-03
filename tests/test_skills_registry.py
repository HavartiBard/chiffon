"""Tests for skills registry infrastructure."""

import pytest
import yaml
from pathlib import Path
from chiffon.skills.registry import SkillsRegistry


@pytest.fixture
def registry():
    return SkillsRegistry(Path(__file__).parent.parent / "src" / "chiffon" / "skills")


def test_registry_loads_skills():
    """Test that registry loads and indexes skills."""
    registry = SkillsRegistry(Path("src/chiffon/skills"))
    skills = registry.get_all_skills()
    assert len(skills) > 0
    assert "yaml-validation" in skills


def test_registry_gets_skill_metadata():
    """Test retrieving skill metadata."""
    registry = SkillsRegistry(Path("src/chiffon/skills"))
    meta = registry.get_skill_metadata("yaml-validation")
    assert meta["domains"]
    assert meta["languages"]
    assert meta["tokens"]


def test_select_skills_by_domains():
    """Test skill selection by domain."""
    registry = SkillsRegistry(Path("src/chiffon/skills"))
    selected = registry.select_skills(
        domains=["testing", "implementation"],
        max_tokens=1000
    )
    assert "test-driven-development" in selected
