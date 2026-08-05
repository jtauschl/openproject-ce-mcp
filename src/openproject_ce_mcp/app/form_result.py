"""Shared form-validation result shape.

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

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FormResult:
    payload: dict[str, Any]
    validation_errors: dict[str, str]
