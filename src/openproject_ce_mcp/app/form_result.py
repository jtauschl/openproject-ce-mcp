"""Shared form-validation result shape and the reader of OpenProject's error identifier.

Package-root shared kernel: a frozen dataclass with exactly `payload` and
`validation_errors` fields, importable from any port module without creating a
layering violation.

The same two-field shape is needed independently by MembershipFormResult,
GridFormResult, ProjectFormResult, ProjectCopyFormResult, and
VersionFormResult; sharing one dataclass here avoids re-duplicating it across
those domains.

Each domain still declares its own `<Domain>FormResult = FormResult` alias in
its own port module rather than importing `FormResult` directly at call
sites: this keeps each Protocol's `create_form`/`update_form` return-type
annotation reading as a domain-owned name (matching every other Port-owned
type in that module), and keeps a future domain free to diverge from this
shape without a breaking rename if its form ever needs a third field.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_ERROR_IDENTIFIER = re.compile(r"urn:openproject-org:api:v3:errors:([A-Za-z]{1,64})")
_ATTRIBUTE = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,63}")


def error_code(error: Any) -> str | None:
    """The class name of an OpenProject error object, or None without a well-formed identifier.

    The identifier is server data that reaches the caller, so only the documented URN shape with a
    letters-only final segment passes."""
    identifier = error.get("errorIdentifier") if isinstance(error, dict) else None
    match = _ERROR_IDENTIFIER.fullmatch(identifier) if isinstance(identifier, str) else None
    return match.group(1) if match else None


def error_attribute(error: Any) -> str | None:
    """The attribute an OpenProject error object names under `_embedded.details`, if it is a plain name."""
    embedded = error.get("_embedded") if isinstance(error, dict) else None
    details = embedded.get("details") if isinstance(embedded, dict) else None
    attribute = details.get("attribute") if isinstance(details, dict) else None
    return attribute if isinstance(attribute, str) and _ATTRIBUTE.fullmatch(attribute) else None


@dataclass(frozen=True)
class ValidationFailure:
    """One rejected attribute of a form: OpenProject's message and its error classes.

    The message is written in the language of the account the token belongs to, so a caller cannot
    branch on it. `error_codes` are the class names OpenProject sends beside it (the final segment of
    `errorIdentifier`, e.g. `PropertyConstraintViolation`); they are language-independent but coarse:
    every violated property constraint shares one class, and the reason stays in the message.
    """

    message: str
    error_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class FormResult:
    payload: dict[str, Any]
    validation_errors: dict[str, ValidationFailure]
