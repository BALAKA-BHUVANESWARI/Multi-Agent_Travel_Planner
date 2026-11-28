"""Checks a response against the application's declared shapes (the TypedDicts in ``app/schemas``)."""
from __future__ import annotations

import types
import typing


def problems(value, shape, where: str) -> list[str]:
    """Where ``value`` does not fit ``shape``. Extra keys are allowed; missing required keys are not."""
    if shape is typing.Any:
        return []
    origin = typing.get_origin(shape)
    if origin in (typing.Required, typing.NotRequired):
        return problems(value, typing.get_args(shape)[0], where)
    if origin in (typing.Union, types.UnionType):
        found = [problems(value, option, where) for option in typing.get_args(shape)]
        return [] if any(not f for f in found) else min(found, key=len)
    if typing.is_typeddict(shape):
        if not isinstance(value, dict):
            return [f"{where}: expected an object, found {type(value).__name__}"]
        hints = typing.get_type_hints(shape, include_extras=True)
        out = [f"{where}.{key}: missing" for key in sorted(shape.__required_keys__) if key not in value]
        for key, hint in hints.items():
            if key in value:
                out += problems(value[key], hint, f"{where}.{key}")
        return out
    if shape is type(None):
        return [] if value is None else [f"{where}: expected nothing"]
    if shape in (list, dict) or origin in (list, dict):
        kind = origin or shape
        if not isinstance(value, kind):
            return [f"{where}: expected {kind.__name__}, found {type(value).__name__}"]
        args = typing.get_args(shape)
        if kind is list and args:
            return [p for i, item in enumerate(value) for p in problems(item, args[0], f"{where}[{i}]")]
        return []
    if shape is float:
        ok = isinstance(value, (int, float)) and not isinstance(value, bool)
    elif shape is int:
        ok = isinstance(value, int) and not isinstance(value, bool)
    elif isinstance(shape, type):
        ok = isinstance(value, shape)
    else:
        return []
    return [] if ok else [f"{where}: expected {shape.__name__}, found {type(value).__name__}"]
