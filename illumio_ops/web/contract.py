"""API contracts: every /api operation is declared once (request and response models),
bound to a route with api_route, and exported to the frontend as JSON Schema."""
from __future__ import annotations

import functools
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Generic, Literal, TypeVar

from flask import Blueprint, Response, jsonify, request
from pydantic import BaseModel, Field, ValidationError

from illumio_ops.pce.client import (
    PceBudgetExhausted,
    PceNotConfigured,
    PceTransportError,
)
from illumio_ops.settings.store import SettingsConflict, SettingsInvalid
from illumio_ops.web.errors import api_error

T = TypeVar("T")
Method = Literal["GET", "POST", "PUT", "DELETE", "PATCH"]


class ApiError(BaseModel):
    code: str
    message_key: str
    params: dict[str, str] = Field(default_factory=dict)
    field: str | None = None


class Meta(BaseModel):
    partial: bool = False
    truncated: bool = False
    notes: list[str] = Field(default_factory=list)


class Envelope(BaseModel, Generic[T]):
    ok: bool
    data: T | None = None
    error: ApiError | None = None
    meta: Meta = Field(default_factory=Meta)


class Empty(BaseModel):
    pass


@dataclass(frozen=True)
class Operation:
    op_id: str
    method: Method
    path: str
    request: type[BaseModel] | None
    response: type[BaseModel]


class ApiFailure(Exception):
    """Raised by a handler to answer with a specific error envelope."""

    def __init__(self, status: int, code: str, message_key: str, *, field: str | None = None,
                 params: dict[str, str] | None = None, data: Any = None) -> None:
        self.status, self.code, self.message_key = status, code, message_key
        self.field, self.params, self.data = field, params or {}, data
        super().__init__(code)


REGISTRY: dict[str, Operation] = {}
_ENDPOINT_TO_OP: dict[str, str] = {}


def operation(op_id: str, method: Method, path: str, request_model: type[BaseModel] | None,
              response_model: type[BaseModel], *, registry: dict[str, Operation] = REGISTRY) -> Operation:
    if op_id in registry:
        raise ValueError(f"operation {op_id} declared twice")
    op = Operation(op_id, method, path, request_model, response_model)
    registry[op_id] = op
    return op


def op_id_for_endpoint(endpoint: str | None) -> str | None:
    return _ENDPOINT_TO_OP.get(endpoint or "")


def _field(exc: ValidationError) -> str | None:
    errs = exc.errors(include_input=False)
    return ".".join(str(p) for p in errs[0]["loc"]) if errs else None


def _failure_response(exc: Exception) -> tuple[Response, int] | None:
    if isinstance(exc, ApiFailure):
        return api_error(exc.status, exc.code, exc.message_key, field=exc.field, params=exc.params, data=exc.data)
    if isinstance(exc, SettingsInvalid):
        return api_error(400, "invalid_settings", "err_invalid_settings",
                         field=exc.errors[0][0] if exc.errors else None)
    if isinstance(exc, SettingsConflict):
        return api_error(409, "stale_revision", "err_stale_revision",
                         params={"expected": str(exc.expected), "actual": str(exc.actual)})
    if isinstance(exc, PceNotConfigured):
        return api_error(409, "pce_not_configured", "err_pce_not_configured")
    if isinstance(exc, PceTransportError):
        return api_error(502, "pce_unreachable", "err_pce_unreachable", params={"kind": exc.kind})
    if isinstance(exc, PceBudgetExhausted):
        return api_error(503, "pce_busy", "err_pce_busy")
    return None


def api_route(bp: Blueprint, op: Operation, *,
              decorators: Sequence[Callable[[Callable[..., Any]], Callable[..., Any]]] = ()
              ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Bind a handler to op. The handler receives the validated body (if the op has
    a request model) plus path parameters, and returns an instance of op.response."""

    def bind(handler: Callable[..., Any]) -> Callable[..., Any]:
        local = op.op_id.replace(".", "_")

        @functools.wraps(handler)
        def view(**path_params: Any) -> tuple[Response, int]:
            args: list[Any] = []
            if op.request is not None:
                try:
                    args.append(op.request.model_validate(request.get_json(silent=True) or {}))
                except ValidationError as exc:  # never echo input: bodies carry secrets
                    return api_error(400, "invalid_input", "err_invalid_input", field=_field(exc))
            try:
                result = handler(*args, **path_params)
            except Exception as exc:
                mapped = _failure_response(exc)
                if mapped is None:
                    raise  # the app-level handler logs it and answers 500 without detail
                return mapped
            data = op.response.model_validate(result).model_dump(mode="json")
            return jsonify(Envelope[Any](ok=True, data=data).model_dump(mode="json")), 200

        view.__name__ = local
        wrapped: Callable[..., Any] = view
        for deco in decorators:
            wrapped = deco(wrapped)
        bp.add_url_rule(op.path, endpoint=local, view_func=wrapped, methods=[op.method])
        _ENDPOINT_TO_OP[f"{bp.name}.{local}"] = op.op_id
        return handler

    return bind
