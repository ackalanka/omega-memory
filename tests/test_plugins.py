"""Tests for omega.plugins discovery and OmegaPlugin base class."""

from unittest.mock import MagicMock, patch


from omega.plugins import OmegaPlugin, discover_plugins


class TestOmegaPluginBase:
    def test_default_attributes(self):
        plugin = OmegaPlugin()
        assert plugin.TOOL_SCHEMAS == []
        assert plugin.HANDLERS == {}
        assert plugin.HOOK_HANDLERS == {}
        assert plugin.CLI_COMMANDS == []
        assert plugin.HOOKS_JSON == {}
        assert plugin.RETRIEVAL_PROFILES == {}
        assert plugin.SCORE_MODIFIERS == []

    def test_subclass_inherits(self):
        class MyPlugin(OmegaPlugin):
            TOOL_SCHEMAS = [{"name": "test_tool"}]
            HANDLERS = {"test_tool": lambda: None}

        p = MyPlugin()
        assert len(p.TOOL_SCHEMAS) == 1
        assert "test_tool" in p.HANDLERS
        assert isinstance(p, OmegaPlugin)


class TestDiscoverPlugins:
    @patch("importlib.metadata.entry_points")
    def test_no_plugins(self, mock_ep):
        mock_ep.return_value = []
        result = discover_plugins()
        assert result == []

    @patch("importlib.metadata.entry_points")
    def test_valid_plugin_class(self, mock_ep):
        class GoodPlugin(OmegaPlugin):
            TOOL_SCHEMAS = [{"name": "good"}]

        ep = MagicMock()
        ep.name = "good_plugin"
        ep.load.return_value = GoodPlugin
        mock_ep.return_value = [ep]

        result = discover_plugins()
        assert len(result) == 1
        assert isinstance(result[0], GoodPlugin)

    @patch("importlib.metadata.entry_points")
    def test_invalid_plugin_skipped(self, mock_ep):
        """Non-OmegaPlugin classes are skipped with a warning."""
        ep = MagicMock()
        ep.name = "bad_plugin"
        ep.load.return_value = str  # not an OmegaPlugin

        mock_ep.return_value = [ep]
        result = discover_plugins()
        assert result == []

    @patch("importlib.metadata.entry_points")
    def test_load_failure_graceful(self, mock_ep):
        """Plugin load failures don't crash discovery."""
        ep = MagicMock()
        ep.name = "broken_plugin"
        ep.load.side_effect = ImportError("missing dependency")

        mock_ep.return_value = [ep]
        result = discover_plugins()
        assert result == []

    @patch("importlib.metadata.entry_points")
    def test_instance_accepted(self, mock_ep):
        """Pre-instantiated OmegaPlugin instances are accepted."""
        instance = OmegaPlugin()

        ep = MagicMock()
        ep.name = "instance_plugin"
        ep.load.return_value = instance

        mock_ep.return_value = [ep]
        result = discover_plugins()
        assert len(result) == 1
        assert result[0] is instance

    @patch("importlib.metadata.entry_points", side_effect=Exception("importlib broken"))
    def test_importlib_failure(self, mock_ep):
        """Total importlib failure returns empty list gracefully."""
        result = discover_plugins()
        assert result == []

    @patch("importlib.metadata.entry_points")
    def test_mixed_plugins(self, mock_ep):
        """Valid plugins are returned even when some fail."""
        class GoodPlugin(OmegaPlugin):
            pass

        good_ep = MagicMock()
        good_ep.name = "good"
        good_ep.load.return_value = GoodPlugin

        bad_ep = MagicMock()
        bad_ep.name = "bad"
        bad_ep.load.side_effect = ImportError("broken")

        mock_ep.return_value = [good_ep, bad_ep]
        result = discover_plugins()
        assert len(result) == 1
        assert isinstance(result[0], GoodPlugin)
