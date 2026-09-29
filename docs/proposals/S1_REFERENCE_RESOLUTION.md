# S1 reference resolution — what was built, and the choices the spec left open

PIPELINE_STAGES §3 lists S1's actions in one line each ("resolve `$ref` references (e.g. "$1" →
previous result)", "resolve `$file` references", "resolve `{{template}}` expressions", "extract
mentioned entities (dates, contact names, file names)"). Everything below the one-liners is a
**proposed choice for the owner to ratify** (ruling ids to be assigned).

## Behaviour (implemented; `src/engine/stages/s1_normalize/`)

| Form | Meaning | Unresolved |
|---|---|---|
| `$ref:N` | the N-th most recent result of *this user's* conversation (N = 1..20) → `[result N: <text ≤ 2000 chars>]` | CLARIFY `unresolved_reference` |
| `$N` (single digit 1–9) | shorthand for `$ref:N`, **only if that result exists**; otherwise literal ("$5 fee" is a price) | stays literal |
| `$file:name` / `$file:"a b.pdf"` | the file in *this workspace* → `[file:name#id]` (**metadata only, never content**) | CLARIFY |
| `{{name}}` | `today`/`yesterday`/`tomorrow` (database clock) or a tenant/workspace variable (workspace overrides tenant) | CLARIFY |
| anything else in braces (`{{ 7*7 }}`, filters, attributes) | not a reference: left as literal text, never evaluated | — |

Rules: single pass (a resolved value is never re-scanned); ≤ 10 references per message
(`too_many_references`); resolved text still ≤ 8000 chars; control characters stripped from resolved
values; the sanitizer runs **after** resolution (a stored value may carry an injection → DENY
`injection_detected`); a source outage is ERROR `reference_source_unavailable` (text without
references never touches the source); the run's stored state holds none of the resolved text.

Unicode (action 1): text is NFC and trimmed. **Injection detection also runs on an
obfuscation-proof form** (NFKC + invisible format characters removed + whitespace collapsed), so
fullwidth "ｉｇｎｏｒｅ…" or zero-width-split "ig​nore…" no longer evade the regex; the model still
receives the user's own text.

Entities (action 5, advisory, deterministic, English): ISO / "5 March 2026" / "March 5, 2026" dates,
today/tomorrow/yesterday when the date is known, e-mail addresses, file names by extension, names
from `named|called|contact|customer|client X Y` and quoted strings. Nothing decides risk, mutation,
capability or access from entities. `NormalizedInput` gained `text`, `entities`, `references`.

Sources (`ReferenceSource` port; PostgreSQL adapter; migration 005; forced RLS):
`conversation_results`, `files`, `template_variables`. The application only READS them; whatever
writes results and files (S15 / a files API) is not built yet.

## Rulings needed

1. `$ref:N` vs bare `$N` and the "only if it exists" rule for the shorthand (currency collision).
2. Files resolve to metadata only; content access is a separate, gated capability.
3. Template syntax limited to variable names; the system variables offered (`today`, `yesterday`,
   `tomorrow`) and who may define stored variables.
4. Ownership of a "result": per user and conversation (recommended) or per conversation.
5. Result text form (`summary`, ≤ 4000 chars) — who produces it (S15) and whether secrets are redacted.
6. Detection on the NFKC form: accept that the detection copy differs from the model's text.
7. Entity coverage beyond English, and whether S2 should be given the entities as hints.
