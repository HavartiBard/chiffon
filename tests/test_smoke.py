import pytest
from typer.testing import CliRunner

from chiffon.cli import app


@pytest.fixture
def runner():
    return CliRunner()


def test_cli_help(runner):
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Usage:" in result.output


# Ensure run-once stub runs with exit code 2
def test_run_once_exit_code_2(runner):
    result = runner.invoke(app, ["run-once"])
    assert result.exit_code == 2
    assert "not implemented" in result.stdout
