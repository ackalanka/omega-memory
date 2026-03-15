"""Structural validation tests for all OMEGA MCP tool schema modules.

Covers coord_schemas, tool_schemas, router/tool_schemas.
Ensures every schema is structurally valid and aligned with its handler registry.
"""
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from omega.server.coord_schemas import COORD_TOOL_SCHEMAS
from omega.server.tool_schemas import TOOL_SCHEMAS

# Optional modules — import if available
try:
    from omega.router.tool_schemas import ROUTER_TOOL_SCHEMAS
except ImportError:
    ROUTER_TOOL_SCHEMAS = None


# ============================================================================
# Parametrize over all schema sets
# ============================================================================

_ALL_SCHEMA_SETS = [
    ("coord", COORD_TOOL_SCHEMAS),
    ("memory", TOOL_SCHEMAS),
]
if ROUTER_TOOL_SCHEMAS is not None:
    _ALL_SCHEMA_SETS.append(("router", ROUTER_TOOL_SCHEMAS))
_SCHEMA_IDS = [s[0] for s in _ALL_SCHEMA_SETS]


@pytest.fixture(params=_ALL_SCHEMA_SETS, ids=_SCHEMA_IDS)
def schema_set(request):
    """Yield (label, schemas) for each schema module."""
    return request.param


# ============================================================================
# Structural validation
# ============================================================================


class TestSchemaStructure:
    """Every schema has the required MCP fields."""

    def test_has_name_description_input_schema(self, schema_set):
        label, schemas = schema_set
        for schema in schemas:
            assert "name" in schema, f"{label}: schema missing 'name'"
            assert "description" in schema, f"{label}/{schema.get('name')}: missing 'description'"
            assert "inputSchema" in schema, f"{label}/{schema.get('name')}: missing 'inputSchema'"

    def test_input_schema_is_object_type(self, schema_set):
        label, schemas = schema_set
        for schema in schemas:
            input_schema = schema["inputSchema"]
            assert input_schema.get("type") == "object", (
                f"{label}/{schema['name']}: inputSchema.type should be 'object', "
                f"got {input_schema.get('type')!r}"
            )

    def test_input_schema_has_properties(self, schema_set):
        label, schemas = schema_set
        for schema in schemas:
            assert "properties" in schema["inputSchema"], (
                f"{label}/{schema['name']}: inputSchema missing 'properties'"
            )

    def test_required_references_existing_properties(self, schema_set):
        label, schemas = schema_set
        for schema in schemas:
            required = schema["inputSchema"].get("required", [])
            properties = set(schema["inputSchema"]["properties"].keys())
            for req in required:
                assert req in properties, (
                    f"{label}/{schema['name']}: required field '{req}' "
                    f"not in properties {properties}"
                )

    def test_names_are_nonempty_strings(self, schema_set):
        label, schemas = schema_set
        for schema in schemas:
            assert isinstance(schema["name"], str) and len(schema["name"]) > 0
            assert isinstance(schema["description"], str) and len(schema["description"]) > 0

    def test_enum_values_are_string_lists(self, schema_set):
        """Any 'enum' in properties should be a list of strings."""
        label, schemas = schema_set
        for schema in schemas:
            for prop_name, prop_def in schema["inputSchema"]["properties"].items():
                if "enum" in prop_def:
                    enum_vals = prop_def["enum"]
                    assert isinstance(enum_vals, list), (
                        f"{label}/{schema['name']}.{prop_name}: enum should be a list"
                    )
                    for val in enum_vals:
                        assert isinstance(val, str), (
                            f"{label}/{schema['name']}.{prop_name}: enum value {val!r} is not a string"
                        )


class TestSchemaCount:
    """Schema counts are sane and have no duplicates."""

    def test_has_at_least_one_schema(self, schema_set):
        label, schemas = schema_set
        assert len(schemas) >= 1, f"{label}: should have at least 1 schema"

    def test_no_duplicate_names(self, schema_set):
        label, schemas = schema_set
        names = [s["name"] for s in schemas]
        assert len(names) == len(set(names)), (
            f"{label}: duplicate schema names: "
            f"{[n for n in names if names.count(n) > 1]}"
        )


class TestDocstringCount:
    """Docstring tool count matches actual schema count."""

    @pytest.mark.parametrize("module_path,schema_attr", [
        ("omega.server.coord_schemas", "COORD_TOOL_SCHEMAS"),
        ("omega.server.tool_schemas", "TOOL_SCHEMAS"),
    ])
    def test_docstring_count_matches(self, module_path, schema_attr):
        import importlib
        mod = importlib.import_module(module_path)
        doc = mod.__doc__ or ""
        match = re.search(r"(\d+)\s+tools", doc)
        if not match:
            pytest.skip(f"{module_path}: no 'N tools' in docstring")
        actual = len(getattr(mod, schema_attr))
        assert int(match.group(1)) == actual, (
            f"{module_path}: docstring says {match.group(1)} tools, "
            f"actually has {actual}"
        )


# ============================================================================
# Handler-schema parity (complements existing UAT test)
# ============================================================================


class TestHandlerParity:
    """Every schema name has a matching handler entry."""

    def test_coord_handler_parity(self):
        from omega.server.coord_handlers import COORD_HANDLERS
        schema_names = {s["name"] for s in COORD_TOOL_SCHEMAS}
        handler_names = set(COORD_HANDLERS.keys())
        # Every schema must have a handler; handlers may also include backward-compat aliases
        assert schema_names <= handler_names, f"Missing handlers: {schema_names - handler_names}"

    def test_memory_handler_parity(self):
        from omega.server.handlers import HANDLERS
        schema_names = {s["name"] for s in TOOL_SCHEMAS}
        handler_names = set(HANDLERS.keys())
        # Every schema must have a handler; handlers may also include backward-compat aliases
        assert schema_names <= handler_names, f"Missing handlers: {schema_names - handler_names}"
