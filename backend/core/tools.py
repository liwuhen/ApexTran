"""Tool abstractions — project-owned (no longer a republic facade).

A ``Tool`` is a model-invocable callable with a JSON-schema parameter spec.
``@tool`` builds one from a function signature (schema via pydantic ``TypeAdapter``)
or, when ``model=`` is given, from a pydantic model. ``ToolContext`` is passed to
context-aware tools; ``ToolAutoResult`` is the legacy result shape kept for typing.
"""

from __future__ import annotations

import inspect
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, NoReturn, TypeVar, overload

from pydantic import BaseModel, TypeAdapter, validate_call

if TYPE_CHECKING:
    from backend.core.errors import AgentError

ModelT = TypeVar("ModelT", bound=BaseModel)


@dataclass(frozen=True)
class ToolContext:
    """Runtime context handed to context-aware tools."""

    tape: str | None
    run_id: str
    meta: dict[str, Any] = field(default_factory=dict)
    state: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolAutoResult:
    """Outcome of an auto tool turn: text, tool calls, or an error."""

    kind: Literal["text", "tools", "error"]
    text: str | None
    tool_calls: list[dict[str, Any]]
    tool_results: list[Any]
    error: AgentError | None

    @classmethod
    def text_result(cls, text: str) -> ToolAutoResult:
        return cls(kind="text", text=text, tool_calls=[], tool_results=[], error=None)

    @classmethod
    def tools_result(cls, tool_calls: list[dict[str, Any]], tool_results: list[Any]) -> ToolAutoResult:
        return cls(kind="tools", text=None, tool_calls=tool_calls, tool_results=tool_results, error=None)

    @classmethod
    def error_result(
        cls,
        error: AgentError,
        *,
        tool_calls: list[dict[str, Any]] | None = None,
        tool_results: list[Any] | None = None,
    ) -> ToolAutoResult:
        return cls(
            kind="error",
            text=None,
            tool_calls=tool_calls or [],
            tool_results=tool_results or [],
            error=error,
        )


def _to_snake_case(name: str) -> str:
    return "".join(["_" + c.lower() if c.isupper() else c for c in name]).lstrip("_")


def _callable_name(func: Callable[..., Any]) -> str:
    name = getattr(func, "__name__", None)
    if isinstance(name, str) and name:
        return name
    return func.__class__.__name__


def _raise_value_error(message: str, *, cause: Exception | None = None) -> NoReturn:
    if cause is None:
        raise ValueError(message)
    raise ValueError(message) from cause


def _raise_type_error(message: str, *, cause: Exception | None = None) -> NoReturn:
    if cause is None:
        raise TypeError(message)
    raise TypeError(message) from cause


def _schema_from_annotation(annotation: Any) -> dict[str, Any]:
    """Convert Python type annotations to JSON schema via Pydantic."""
    if annotation is inspect._empty:
        annotation = Any
    try:
        return TypeAdapter(annotation).json_schema()
    except Exception as exc:
        _raise_value_error(f"Failed to build JSON schema for type: {annotation!r}", cause=exc)


def _schema_from_signature(signature: inspect.Signature, *, ignore_params: set[str] | None = None) -> dict[str, Any]:
    ignore = ignore_params or set()
    properties: dict[str, Any] = {}
    required: list[str] = []
    for param in signature.parameters.values():
        if param.name in ignore:
            continue
        if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
            continue
        properties[param.name] = _schema_from_annotation(param.annotation)
        if param.default is param.empty:
            required.append(param.name)
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


@dataclass(frozen=True)
class Tool:
    """A Tool is a callable unit the model can invoke."""

    name: str
    description: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)
    handler: Callable[..., Any] | None = None
    context: bool = False

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def as_tool(self, json_mode: bool = False) -> str | dict[str, Any]:
        schema = self.schema()
        if json_mode:
            return json.dumps(schema, indent=2)
        return schema

    def run(self, *args: Any, **kwargs: Any) -> Any:
        handler = self.handler
        if handler is None:
            _raise_type_error(f"Tool '{self.name}' is schema-only and cannot be executed.")
        return handler(*args, **kwargs)

    @classmethod
    def from_callable(
        cls,
        func: Callable[..., Any],
        *,
        name: str | None = None,
        description: str | None = None,
        context: bool = False,
    ) -> Tool:
        signature = inspect.signature(func)
        if context and "context" not in signature.parameters:
            _raise_type_error("Tool context is enabled but the callable lacks a 'context' parameter.")
        tool_name = name or _to_snake_case(_callable_name(func))
        tool_description = description if description is not None else (inspect.getdoc(func) or "")
        parameters = _schema_from_signature(signature, ignore_params={"context"} if context else None)
        validated = validate_call(func)
        return cls(
            name=tool_name,
            description=tool_description,
            parameters=parameters,
            handler=validated,
            context=context,
        )

    @classmethod
    def from_model(
        cls,
        model: type[ModelT],
        handler: Callable[..., Any] | None = None,
        *,
        context: bool = False,
    ) -> Tool:
        if handler is None:

            def _default_handler(payload: ModelT) -> Any:
                return payload.model_dump()

            handler_fn = _default_handler
        else:
            handler_fn = handler
        return tool_from_model(model, handler_fn, context=context)


def schema_from_model[ModelT: BaseModel](
    model: type[ModelT],
    *,
    name: str | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    """Create a tool schema from a Pydantic model without making it runnable."""
    model_name = name or _to_snake_case(model.__name__)
    model_description = description if description is not None else (model.__doc__ or "")
    return {
        "type": "function",
        "function": {
            "name": model_name,
            "description": model_description,
            "parameters": model.model_json_schema(),
        },
    }


def tool_from_model[ModelT: BaseModel](
    model: type[ModelT],
    handler: Callable[..., Any],
    *,
    name: str | None = None,
    description: str | None = None,
    context: bool = False,
) -> Tool:
    """Create a runnable Tool that validates inputs via a Pydantic model."""
    tool_name = name or _to_snake_case(model.__name__)
    tool_description = description if description is not None else (model.__doc__ or "")

    if context:
        signature = inspect.signature(handler)
        if "context" not in signature.parameters:
            _raise_type_error("Tool context is enabled but the handler lacks a 'context' parameter.")

    def _handler(*args: Any, **kwargs: Any) -> Any:
        tool_context = kwargs.pop("context", None)
        parsed = model(*args, **kwargs)
        if context:
            return handler(parsed, context=tool_context)
        return handler(parsed)

    return Tool(
        name=tool_name,
        description=tool_description,
        parameters=model.model_json_schema(),
        handler=_handler,
        context=context,
    )


@overload
def tool(
    func: Callable[..., Any],
    *,
    name: str | None = None,
    model: type[BaseModel] | None = None,
    description: str | None = None,
    context: bool = False,
) -> Tool: ...


@overload
def tool(
    func: None = None,
    *,
    name: str | None = None,
    model: type[BaseModel] | None = None,
    description: str | None = None,
    context: bool = False,
) -> Callable[[Callable[..., Any]], Tool]: ...


def tool(
    func: Callable[..., Any] | None = None,
    *,
    name: str | None = None,
    model: type[BaseModel] | None = None,
    description: str | None = None,
    context: bool = False,
) -> Tool | Callable[[Callable[..., Any]], Tool]:
    """Decorator to convert a function into a :class:`Tool` instance."""

    def _create_tool(f: Callable[..., Any]) -> Tool:
        if model is not None:
            return tool_from_model(model, f, name=name, description=description, context=context)
        return Tool.from_callable(f, name=name, description=description, context=context)

    if func is None:
        return _create_tool
    return _create_tool(func)


__all__ = [
    "Tool",
    "ToolAutoResult",
    "ToolContext",
    "schema_from_model",
    "tool",
    "tool_from_model",
]
