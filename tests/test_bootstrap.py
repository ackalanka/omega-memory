"""Tests for the OMEGA project bootstrap scanner."""

import json
import subprocess
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def python_project(tmp_path):
    """Create a minimal Python project directory."""
    # pyproject.toml
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "my-app"\nrequires-python = ">=3.11"\n'
        'dependencies = ["fastapi", "sqlalchemy", "pydantic"]\n\n'
        "[tool.ruff]\nline-length = 100\n"
    )
    # README
    (tmp_path / "README.md").write_text(
        "# my-app\n\n"
        "[![CI](https://badge.svg)](https://ci)\n\n"
        "A web API for managing tasks and projects.\n\n"
        "## Installation\n\npip install my-app\n"
    )
    # Directories
    (tmp_path / "src" / "my_app").mkdir(parents=True)
    (tmp_path / "src" / "my_app" / "__init__.py").write_text("")
    (tmp_path / "src" / "my_app" / "main.py").write_text("print('hello')")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_main.py").write_text("def test_it(): pass")
    (tmp_path / "tests" / "test_api.py").write_text("def test_api(): pass")
    (tmp_path / "tests" / "conftest.py").write_text("")
    (tmp_path / "docs").mkdir()
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "ci.yml").write_text("on: push")
    (tmp_path / "conftest.py").write_text("")  # pytest marker
    (tmp_path / "CLAUDE.md").write_text("# Instructions")
    (tmp_path / "Dockerfile").write_text("FROM python:3.11")
    return tmp_path


@pytest.fixture
def node_project(tmp_path):
    """Create a minimal Node.js project directory."""
    (tmp_path / "package.json").write_text(
        json.dumps(
            {
                "name": "my-dashboard",
                "dependencies": {"next": "14.0.0", "react": "18.2.0", "react-dom": "18.2.0"},
                "devDependencies": {"typescript": "5.0.0", "eslint": "8.0.0"},
                "scripts": {"dev": "next dev", "build": "next build", "test": "jest"},
            }
        )
    )
    (tmp_path / "README.md").write_text("# my-dashboard\n\nA Next.js dashboard for analytics.\n")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.tsx").write_text("")
    (tmp_path / "__tests__").mkdir()
    (tmp_path / "__tests__" / "app.test.ts").write_text("")
    (tmp_path / "jest.config.js").write_text("module.exports = {}")
    (tmp_path / ".eslintrc.json").write_text("{}")
    return tmp_path


@pytest.fixture
def empty_project(tmp_path):
    """Create a bare directory with nothing in it."""
    return tmp_path


@pytest.fixture
def git_project(tmp_path):
    """Create a project with real git history."""
    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(tmp_path),
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=str(tmp_path),
        capture_output=True,
    )
    (tmp_path / "main.py").write_text("print('v1')")
    subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "feat: initial commit", "--no-gpg-sign"],
        cwd=str(tmp_path),
        capture_output=True,
    )
    (tmp_path / "main.py").write_text("print('v2')")
    subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "fix: update output", "--no-gpg-sign"],
        cwd=str(tmp_path),
        capture_output=True,
    )
    return tmp_path


# ---------------------------------------------------------------------------
# scan_project tests
# ---------------------------------------------------------------------------


class TestScanProject:
    def test_python_project(self, python_project):
        from omega.bootstrap import scan_project

        ctx = scan_project(str(python_project))

        assert ctx["language"] == "Python"
        assert ctx["project_name"] == "my-app"
        assert ctx["python_version"] == ">=3.11"
        assert ctx["framework"] == "FastAPI"
        assert "fastapi" in ctx["dependencies"]
        assert "sqlalchemy" in ctx["dependencies"]
        assert "ruff" in ctx.get("linters", [])
        assert ctx["test_framework"] == "pytest"
        assert ctx["test_file_count"] >= 2
        assert "GitHub Actions" in ctx.get("ci", [])
        assert ctx["has_claude_md"] is True
        assert ctx["has_docker"] is True
        assert "src" in ctx["directories"]
        assert "tests" in ctx["directories"]
        assert "docs" in ctx["directories"]

    def test_node_project(self, node_project):
        from omega.bootstrap import scan_project

        ctx = scan_project(str(node_project))

        assert ctx["language"] == "Node.js"
        assert ctx["project_name"] == "my-dashboard"
        assert ctx["framework"] == "Next.js"
        assert "next" in ctx["dependencies"]
        assert "react" in ctx["dependencies"]
        assert "ESLint" in ctx.get("linters", [])
        assert ctx["test_framework"] == "Jest"
        assert "dev" in ctx.get("scripts", {})

    def test_empty_project(self, empty_project):
        from omega.bootstrap import scan_project

        ctx = scan_project(str(empty_project))

        # Should still return something (project_name from dir name)
        assert ctx.get("project_name") == empty_project.name
        assert "language" not in ctx

    def test_nonexistent_dir(self):
        from omega.bootstrap import scan_project

        ctx = scan_project("/nonexistent/path/that/doesnt/exist")
        assert ctx == {}

    def test_git_history(self, git_project):
        from omega.bootstrap import scan_project

        ctx = scan_project(str(git_project))

        assert ctx.get("is_git") is True
        assert ctx.get("commit_count", 0) >= 2
        assert len(ctx.get("recent_commits", [])) >= 2
        assert any("initial commit" in c for c in ctx["recent_commits"])

    def test_readme_extraction(self, python_project):
        from omega.bootstrap import scan_project

        ctx = scan_project(str(python_project))

        # Should extract the description paragraph, skipping title and badges
        assert "description" in ctx
        assert "managing tasks" in ctx["description"]
        assert "badge" not in ctx["description"].lower()


# ---------------------------------------------------------------------------
# format_summary tests
# ---------------------------------------------------------------------------


class TestFormatSummary:
    def test_python_summary(self, python_project):
        from omega.bootstrap import scan_project, format_summary

        ctx = scan_project(str(python_project))
        summary = format_summary(ctx)

        assert "my-app" in summary
        assert "Python" in summary
        assert "FastAPI" in summary
        assert "pytest" in summary

    def test_node_summary(self, node_project):
        from omega.bootstrap import scan_project, format_summary

        ctx = scan_project(str(node_project))
        summary = format_summary(ctx)

        assert "my-dashboard" in summary
        assert "Node.js" in summary
        assert "Next.js" in summary

    def test_empty_context(self):
        from omega.bootstrap import format_summary

        assert format_summary({}) == ""

    def test_summary_has_project_line(self):
        from omega.bootstrap import format_summary

        summary = format_summary({"project_name": "foo", "language": "Rust"})
        assert "Project:" in summary
        assert "foo" in summary
        assert "Rust" in summary

    def test_summary_has_tools_line(self):
        from omega.bootstrap import format_summary

        summary = format_summary({
            "project_name": "x",
            "test_framework": "pytest",
            "test_file_count": 10,
            "linters": ["ruff"],
            "ci": ["GitHub Actions"],
        })
        assert "Tools:" in summary
        assert "pytest" in summary
        assert "10 test files" in summary
        assert "ruff" in summary
        assert "GitHub Actions" in summary


# ---------------------------------------------------------------------------
# store_bootstrap tests
# ---------------------------------------------------------------------------


class TestStoreBootstrap:
    def test_stores_memories(self, python_project, tmp_omega_dir):
        from omega.bootstrap import scan_project, store_bootstrap

        ctx = scan_project(str(python_project))
        count = store_bootstrap(ctx, project=str(python_project), entity_id="my-app")

        assert count >= 2  # at least overview + tech stack

    def test_stores_with_correct_type(self, python_project, tmp_omega_dir):
        from omega.bootstrap import scan_project, store_bootstrap

        ctx = scan_project(str(python_project))

        stored_calls = []
        original_store = None

        def mock_store(content, event_type="memory", **kwargs):
            stored_calls.append({"content": content, "event_type": event_type, **kwargs})
            return f"node_{len(stored_calls)}"

        with patch("omega.bridge.store", side_effect=mock_store):
            count = store_bootstrap(ctx, project=str(python_project), entity_id="my-app")

        assert count >= 2
        for call in stored_calls:
            assert call["event_type"] == "project_context"
            assert call["metadata"]["bootstrap"] is True
            assert call["entity_id"] == "my-app"

    def test_empty_context_stores_nothing(self):
        from omega.bootstrap import store_bootstrap

        with patch("omega.bridge.store") as mock:
            count = store_bootstrap({})
            assert count == 0
            mock.assert_not_called()

    def test_categories_are_distinct(self, python_project):
        from omega.bootstrap import scan_project, store_bootstrap

        ctx = scan_project(str(python_project))
        stored_calls = []

        def mock_store(content, event_type="memory", **kwargs):
            stored_calls.append(kwargs.get("metadata", {}))
            return f"node_{len(stored_calls)}"

        with patch("omega.bridge.store", side_effect=mock_store):
            store_bootstrap(ctx, project=str(python_project))

        categories = [c.get("category") for c in stored_calls]
        assert "overview" in categories
        assert "tech_stack" in categories
        # categories should be unique
        assert len(categories) == len(set(categories))


# ---------------------------------------------------------------------------
# Integration: session_start with bootstrap
# ---------------------------------------------------------------------------


class TestSessionStartBootstrap:
    def test_first_session_shows_bootstrap(self, tmp_omega_dir, python_project):
        """When memory_count is 0 and project is set, bootstrap summary appears."""
        from omega.server.hook_server import handle_session_start

        with patch("omega.bridge.get_session_context") as mock_ctx:
            mock_ctx.return_value = {
                "memory_count": 0,
                "health_status": "ok",
                "last_capture_ago": "never",
                "context_items": [],
            }
            result = handle_session_start({"session_id": "test", "project": str(python_project)})

        output = result["output"]
        assert "scanned your project" in output.lower() or "welcome" in output.lower()
        # Should contain project info
        assert "my-app" in output or "Quick start" in output

    def test_first_session_no_project_falls_back(self, tmp_omega_dir):
        """When no project path, falls back to generic welcome."""
        from omega.server.hook_server import handle_session_start

        with patch("omega.bridge.get_session_context") as mock_ctx:
            mock_ctx.return_value = {
                "memory_count": 0,
                "health_status": "ok",
                "last_capture_ago": "never",
                "context_items": [],
            }
            result = handle_session_start({"session_id": "test", "project": ""})

        output = result["output"]
        assert "welcome" in output.lower()
        assert "Quick start" in output
