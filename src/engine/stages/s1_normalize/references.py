"""
S1 reference resolution: `$ref`, `$file` and `{{template}}` (PIPELINE_STAGES §3, actions 2–4).

Safety rules (these are the design, not details):
- ONE pass. A resolved value is inserted as text and never scanned again, so a stored value that
  contains `$1` or `{{x}}` cannot loop or amplify.
- The caller's own data only: results of this user's conversation, this workspace's files, this
  tenant/workspace's variables (the ReferenceSource enforces the scope; RLS in PostgreSQL).
- Files resolve to their METADATA (`[file:name#id]`), never their content.
- Templates are variable names only: `{{today}}`, `{{crm_owner}}`. No expressions, filters or
  attribute walking; anything that is not a plain name is left as literal text.
- At most MAX_REFERENCES references per message; each inserted value is capped.
- Fail closed: an explicit reference that cannot be resolved is CLARIFY `unresolved_reference`
  (the text is never sent on with the reference silently dropped).
- Resolved text is sanitized afterwards by S1 like any other input (a stored value may itself
  carry an injection).

Reference forms
  $ref:N     explicit: the N-th most recent result of this conversation (N = 1..MAX_RESULT_INDEX)
  $N         bare shorthand for $ref:N, ONLY for a single digit 1-9 and ONLY if that result exists
             (otherwise it is literal text: "$5 fee" stays "$5 fee")
  $file:name unquoted name [A-Za-z0-9._-], or $file:"quoted name.pdf"
  {{name}}   variable name [A-Za-z_][A-Za-z0-9_.]*
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

from contracts.reference_source import ReferenceSource

MAX_REFERENCES = 10
MAX_RESULT_INDEX = 20
MAX_RESULT_CHARS = 2000
MAX_VARIABLE_CHARS = 500

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_MASTER = re.compile(
    r"""(?P<ref>(?<![\w$])\$ref:(?P<ref_n>\d{1,2})(?!\w))
      | (?P<bare>(?<![\w$.,])\$(?P<bare_n>[1-9])(?![\d]|[.,]\d))
      | (?P<file>(?<![\w$])\$file:(?:"(?P<file_q>[^"\n]{1,100})"
                    |(?P<file_u>[A-Za-z0-9](?:[A-Za-z0-9._\-]{0,98}[A-Za-z0-9])?)))
      | (?P<tpl>\{\{\s*(?P<tpl_name>[A-Za-z_][A-Za-z0-9_.]{0,63})\s*\}\})""",
    re.VERBOSE,
)


@dataclass
class Resolution:
    text: str
    references: dict[str, str] = field(default_factory=dict)   # reference as written -> what it stood for
    files: list[str] = field(default_factory=list)              # file names referenced
    unresolved: list[str] = field(default_factory=list)
    problem: str | None = None                                  # "too_many_references"


def has_reference(text: str) -> bool:
    return _MASTER.search(text) is not None


def _clean(value: str, cap: int) -> str:
    value = _CONTROL.sub("", value).strip()
    return value if len(value) <= cap else value[: cap - 1] + "…"


async def resolve_references(text: str, *, tenant_id: str, workspace_id: str, user_id: str,
                             conversation_id: str | None, source: ReferenceSource | None) -> Resolution:
    """Resolve every reference in `text`. Does not raise for unresolved references (they are
    reported); a failing `source` raises, and the caller turns that into ERROR."""
    matches = list(_MASTER.finditer(text))
    out = Resolution(text=text)
    if not matches:
        return out
    if len(matches) > MAX_REFERENCES:
        out.problem = "too_many_references"
        return out

    pieces: list[str] = []
    cursor = 0
    for m in matches:
        written = m.group(0)
        replacement: str | None

        if m.group("ref") or m.group("bare"):
            explicit = bool(m.group("ref"))
            n = int(m.group("ref_n") if explicit else m.group("bare_n"))
            replacement = None
            if source is not None and conversation_id and 1 <= n <= MAX_RESULT_INDEX:
                value = await source.previous_result(
                    tenant_id=tenant_id, user_id=user_id, conversation_id=conversation_id, index=n)
                if value is not None:
                    replacement = f"[result {n}: {_clean(value, MAX_RESULT_CHARS)}]"
                    out.references[written] = _clean(value, MAX_RESULT_CHARS)
            if replacement is None:
                if explicit:
                    out.unresolved.append(written)      # an explicit reference must resolve
                replacement = written                    # a bare "$5" is just text
        elif m.group("file"):
            name = m.group("file_q") or m.group("file_u")
            info = await source.file(tenant_id=tenant_id, workspace_id=workspace_id, name=name) \
                if source is not None else None
            if info is None:
                out.unresolved.append(written)
                replacement = written
            else:
                replacement = f"[file:{info.name}#{info.file_id}]"
                out.references[written] = f"file:{info.file_id}"
                out.files.append(info.name)
        else:  # template
            name = m.group("tpl_name")
            value = await _template_value(name, tenant_id, workspace_id, source)
            if value is None:
                out.unresolved.append(written)
                replacement = written
            else:
                replacement = _clean(value, MAX_VARIABLE_CHARS)
                out.references[written] = replacement

        pieces.append(text[cursor:m.start()])
        pieces.append(replacement)
        cursor = m.end()
    pieces.append(text[cursor:])
    out.text = "".join(pieces)
    return out


async def _template_value(name: str, tenant_id: str, workspace_id: str,
                          source: ReferenceSource | None) -> str | None:
    """System variables first (deterministic, from the authoritative clock), then stored ones."""
    if source is None:
        return None
    if name in ("today", "yesterday", "tomorrow"):
        today = dt.datetime.fromtimestamp(await source.now(), dt.timezone.utc).date()
        return (today + dt.timedelta(days={"today": 0, "yesterday": -1, "tomorrow": 1}[name])).isoformat()
    return await source.variable(tenant_id=tenant_id, workspace_id=workspace_id, name=name)
