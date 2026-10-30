"""Resolve local schema references for both site and routing configuration forms."""

from typing import Any
from pydantic import BaseModel

def plugin_schema(model: type[BaseModel]) -> dict[str, Any]:
    raw = model.model_json_schema() if hasattr(model, "model_json_schema") else model.schema()
    return inline_local_refs(raw)


def inline_local_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Publish nested models as concrete properties so the form does not need $ref."""

    definitions = schema.get("$defs", {})

    def walk(node: Any) -> Any:
        if not isinstance(node, dict):
            return node
        if "$ref" in node:
            name = str(node["$ref"]).rsplit("/", 1)[-1]
            target = walk(definitions[name])
            rest = {key: value for key, value in node.items() if key != "$ref"}
            return {**target, **rest}
        current = node
        if "allOf" in current:
            merged: dict[str, Any] = {}
            for item in current["allOf"]:
                merged.update(walk(item))
            rest = {key: value for key, value in current.items() if key != "allOf"}
            merged.update(rest)
            current = merged
        if "properties" in current:
            current = {
                **current,
                "properties": {key: walk(value) for key, value in current["properties"].items()},
            }
        return current

    inlined = walk(schema)
    if isinstance(inlined, dict):
        inlined.pop("$defs", None)
    return inlined
