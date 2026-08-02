"""Shared form-validation result shape.

Package-root shared kernel: a frozen dataclass with exactly `payload` and
`validation_errors` fields, importable from any port module without creating a
layering violation.

Extracted after a byte-identical `<Domain>FormResult` dataclass (same two
fields) was found independently duplicated across MembershipFormResult,
GridFormResult, ProjectFormResult, ProjectCopyFormResult, and
VersionFormResult (found during the Sprints migration's step-6
reuse/simplification audit) -- past this project's own "3+ identical copies"
unification threshold.

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
