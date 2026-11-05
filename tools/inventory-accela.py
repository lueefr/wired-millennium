#!/usr/bin/env python3
"""Inventory shipped ACCELA Python definitions without importing/executing them."""
import ast
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'backend'))
from runtime import ensure_runtime, sha256

info = ensure_runtime()
source = Path(info['source'])
modules = []
for path in sorted(source.rglob('*.py')):
    if 'deps' in path.relative_to(source).parts:
        continue
    text = path.read_text(encoding='utf-8-sig')
    tree = ast.parse(text)
    modules.append({'module': str(path.relative_to(source)), 'sha256': sha256(path), 'lines': len(text.splitlines()), 'classes': [node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)], 'functions': [node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]})
print(json.dumps({'version': info['version'], 'artifact_sha256': info['artifact_sha256'], 'modules': modules}, indent=2))
