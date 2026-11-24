"""NFR-13 / DC-05: docs/openapi.json is valid OpenAPI 3.0.3 and matches the code."""

import json

from openapi_spec_validator import validate
from scripts.export_openapi import DOCS, build, to_openapi_30


def test_exported_spec_is_valid_and_up_to_date() -> None:
    converted = to_openapi_30(build())
    validate(converted)
    assert converted["openapi"] == "3.0.3"
    saved = json.loads((DOCS / "openapi.json").read_text())
    assert saved == converted, "docs/openapi.json is outdated: run `make openapi`"


def test_every_schema_and_operation_is_documented() -> None:
    spec = to_openapi_30(build())
    schemas = spec["components"]["schemas"]
    assert all(schema.get("description") for schema in schemas.values())
    operations = [op for ops in spec["paths"].values() for op in ops.values()]
    assert all(op.get("summary") for op in operations)
    assert '"type": "null"' not in json.dumps(spec)  # 3.1-only construct removed


def test_conversion_rules() -> None:
    node = {
        "anyOf": [{"$ref": "#/components/schemas/X"}, {"type": "null"}],
        "description": "d",
    }
    assert to_openapi_30({"components": {"schemas": {"A": node}}, "paths": {}})["components"][
        "schemas"
    ]["A"] == {
        "allOf": [{"$ref": "#/components/schemas/X"}],
        "description": "d",
        "nullable": True,
    }
