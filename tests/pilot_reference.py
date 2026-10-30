"""Execute selected, hash-verified original functions without importing the old app."""

import ast
import hashlib
import json
from pathlib import Path
import typing

import numpy as np

SOURCE = Path(__file__).parent / "reference" / "pilot_v2"


def source_manifest():
    manifest = json.loads((SOURCE / "provenance.json").read_text())
    for name, entry in manifest["files"].items():
        data = (SOURCE / name).read_bytes()
        if hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise ValueError(f"frozen PILOT source changed: {name}")
    return manifest


def original_functions(filename, names, bindings):
    source_manifest()
    tree = ast.parse((SOURCE / filename).read_text())
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    if {node.name for node in functions} != set(names):
        raise ValueError("original function not found")
    namespace = {**vars(typing), "np": np, **bindings}
    module = ast.Module(body=functions, type_ignores=[])
    exec(compile(module, str(SOURCE / filename), "exec"), namespace)
    return namespace


def original_constants():
    source_manifest()
    constants = {}
    for node in ast.parse((SOURCE / "constants.py").read_text()).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                constants[node.targets[0].id] = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                pass
    return constants
