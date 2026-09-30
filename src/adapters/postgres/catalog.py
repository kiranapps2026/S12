"""Load a registry catalog (capabilities, kernel operations, bindings, versions) from a YAML file into the database.

`validate` is pure and checks the catalog on its own; `plan` compares it with the database; `apply` writes it in ONE
transaction. Rules (fail closed): every production-enabled write/delete/irreversible operation names an observation method;
references exist; a capability's mutation equals its operation's; nothing is ever deleted (an operation is retired by
marking it DEPRECATED); and the registry versions must change whenever anything else does, because every plan pins them."""
from __future__ import annotations

from dataclasses import dataclass, field

from adapters.postgres.database import Database

MUTATIONS = ("R", "W", "D", "IRREVERSIBLE")
TRUTH = ("DRAFT", "REVIEW", "PRODUCTION_ENABLED", "DEPRECATED")
RETRY = ("safe", "idempotent", "never")
VERSION_KEYS = ("capability", "binding", "risk_policy", "authorization", "worker_runtime", "model")
OP_FIELDS = frozenset({"id", "mutation", "risk_floor", "cost", "timeout_seconds", "retry_safety", "inverse", "observation", "truth_state"})
CAP_FIELDS = frozenset({"id", "name", "intent", "mutation", "risk_floor", "risk_rule", "risk_implied", "truth_state"})
BIND_FIELDS = frozenset({"id", "capability", "kernel_op", "provider", "engine_module", "adapter_class", "priority", "is_active"})
OBS_FIELDS = frozenset({"method", "identifier_field", "expects_absent"})


def _unit(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 1


def validate(doc: dict) -> list[str]:
    """Every problem in the catalog document (empty list: valid)."""
    errors: list[str] = []
    if not isinstance(doc, dict):
        return ["the catalog must be a mapping with versions, kernel_ops, capabilities and bindings"]
    extra = set(doc) - {"versions", "kernel_ops", "capabilities", "bindings"}
    if extra:
        errors.append(f"unknown top-level keys: {sorted(extra)}")
    versions = doc.get("versions")
    if not isinstance(versions, dict) or set(versions) != set(VERSION_KEYS) or not all(isinstance(v, str) and v for v in versions.values()):
        errors.append(f"versions must give a non-empty text for each of {list(VERSION_KEYS)}")
    ops, caps, binds = doc.get("kernel_ops") or [], doc.get("capabilities") or [], doc.get("bindings") or []
    for name, rows in (("kernel_ops", ops), ("capabilities", caps), ("bindings", binds)):
        if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
            errors.append(f"{name} must be a list of mappings")
            return errors

    def ids(rows, label):
        seen: set[str] = set()
        for r in rows:
            i = r.get("id")
            if not isinstance(i, str) or not i:
                errors.append(f"{label}: an entry has no id")
            elif i in seen:
                errors.append(f"{label}: duplicate id {i}")
            seen.add(i)
        return seen
    op_ids, cap_ids = ids(ops, "kernel_ops"), ids(caps, "capabilities")
    ids(binds, "bindings")
    by_op = {o.get("id"): o for o in ops}

    for o in ops:
        i = o.get("id")
        if set(o) - OP_FIELDS:
            errors.append(f"kernel op {i}: unknown fields {sorted(set(o) - OP_FIELDS)}")
        if o.get("mutation") not in MUTATIONS:
            errors.append(f"kernel op {i}: mutation must be one of {MUTATIONS}")
        if not _unit(o.get("risk_floor")):
            errors.append(f"kernel op {i}: risk_floor must be between 0 and 1")
        for f in ("cost", "timeout_seconds"):
            if not isinstance(o.get(f), int) or isinstance(o.get(f), bool) or o[f] < 1:
                errors.append(f"kernel op {i}: {f} must be a whole number >= 1")
        if o.get("retry_safety") not in RETRY:
            errors.append(f"kernel op {i}: retry_safety must be one of {RETRY}")
        if o.get("truth_state", "PRODUCTION_ENABLED") not in TRUTH:
            errors.append(f"kernel op {i}: truth_state must be one of {TRUTH}")
        if o.get("inverse") is not None:
            if o["inverse"] not in op_ids:
                errors.append(f"kernel op {i}: inverse {o['inverse']} is not in this file")
            elif o["inverse"] == i:
                errors.append(f"kernel op {i}: an operation cannot be its own inverse")
        obs = o.get("observation")
        if obs is not None and (not isinstance(obs, dict) or set(obs) - OBS_FIELDS or not obs.get("method")):
            errors.append(f"kernel op {i}: observation needs a method (and only method, identifier_field, expects_absent)")
        live = o.get("truth_state", "PRODUCTION_ENABLED") == "PRODUCTION_ENABLED"
        if live and o.get("mutation") in ("W", "D", "IRREVERSIBLE") and not (isinstance(obs, dict) and obs.get("method")):
            errors.append(f"kernel op {i}: a production {o.get('mutation')} operation needs observation.method "
                          "(or set truth_state: DRAFT until a read can show its effect)")
        if isinstance(obs, dict) and obs.get("expects_absent") and o.get("mutation") not in ("D", "IRREVERSIBLE"):
            errors.append(f"kernel op {i}: expects_absent only makes sense for a delete")
        if o.get("mutation") == "R" and obs:
            errors.append(f"kernel op {i}: a read needs no observation")
    for c in caps:
        i = c.get("id")
        if set(c) - CAP_FIELDS:
            errors.append(f"capability {i}: unknown fields {sorted(set(c) - CAP_FIELDS)}")
        for f in ("name", "intent"):
            if not isinstance(c.get(f), str) or not c[f].strip():
                errors.append(f"capability {i}: {f} is required")
        if c.get("mutation") not in MUTATIONS:
            errors.append(f"capability {i}: mutation must be one of {MUTATIONS}")
        for f in ("risk_floor", "risk_rule", "risk_implied"):
            if not _unit(c.get(f)):
                errors.append(f"capability {i}: {f} must be between 0 and 1")
        if c.get("truth_state", "PRODUCTION_ENABLED") not in TRUTH:
            errors.append(f"capability {i}: truth_state must be one of {TRUTH}")
    intents = [c.get("intent") for c in caps if c.get("truth_state", "PRODUCTION_ENABLED") == "PRODUCTION_ENABLED"]
    for intent in {x for x in intents if intents.count(x) > 1}:
        errors.append(f"intent {intent} is offered by more than one production capability")
    cap_by_id = {c.get("id"): c for c in caps}
    for b in binds:
        i = b.get("id")
        if set(b) - BIND_FIELDS:
            errors.append(f"binding {i}: unknown fields {sorted(set(b) - BIND_FIELDS)}")
        for f in ("provider", "engine_module", "adapter_class"):
            if not isinstance(b.get(f), str) or not b[f]:
                errors.append(f"binding {i}: {f} is required")
        if b.get("capability") not in cap_ids:
            errors.append(f"binding {i}: capability {b.get('capability')} is not in this file")
        if b.get("kernel_op") not in op_ids:
            errors.append(f"binding {i}: kernel_op {b.get('kernel_op')} is not in this file")
        cap, op = cap_by_id.get(b.get("capability")), by_op.get(b.get("kernel_op"))
        if cap and op and cap.get("mutation") != op.get("mutation"):
            errors.append(f"binding {i}: capability mutation {cap.get('mutation')} differs from operation mutation {op.get('mutation')}")
    for c in caps:
        if c.get("truth_state", "PRODUCTION_ENABLED") == "PRODUCTION_ENABLED" and not any(
                b.get("capability") == c.get("id") and b.get("is_active", True) for b in binds):
            errors.append(f"capability {c.get('id')} is production-enabled but has no active binding")
    return errors


@dataclass
class Plan:
    add: dict = field(default_factory=dict)             # table -> ids to insert
    change: dict = field(default_factory=dict)          # table -> ids whose row differs
    missing_from_file: dict = field(default_factory=dict)   # table -> ids in the database, not in the file (kept)
    versions_change: bool = False

    @property
    def content_changes(self) -> bool:
        return any(self.add.values()) or any(self.change.values())


def _op_row(o: dict) -> tuple:
    obs = o.get("observation") or {}
    return (o["mutation"], float(o["risk_floor"]), o["cost"], o["timeout_seconds"], o["retry_safety"],
            o.get("truth_state", "PRODUCTION_ENABLED"), o.get("inverse"), obs.get("method"),
            bool(obs.get("expects_absent", False)), obs.get("identifier_field"))


def _cap_row(c: dict) -> tuple:
    return (c["name"], c["intent"], c["mutation"], float(c["risk_floor"]), float(c["risk_rule"]), float(c["risk_implied"]),
            c.get("truth_state", "PRODUCTION_ENABLED"))


def _bind_row(b: dict) -> tuple:
    return (b["capability"], b["kernel_op"], b["provider"], b["engine_module"], b["adapter_class"], b.get("priority", 1),
            bool(b.get("is_active", True)))


async def _current(c) -> tuple[dict, dict, dict, tuple | None]:
    ops = {r["kernel_op_id"]: (r["mutation"], float(r["risk_floor"]), r["cost"], r["timeout_seconds"], r["retry_safety"], r["truth_state"],
                               r["inverse"], r["observation_method"], r["observation_expects_absent"], r["observation_identifier_field"])
           for r in await c.fetch("SELECT * FROM kernel_ops")}
    caps = {r["capability_id"]: (r["name"], r["intent"], r["mutation"], float(r["risk_floor"]), float(r["risk_rule"]),
                                 float(r["risk_implied"]), r["truth_state"]) for r in await c.fetch("SELECT * FROM capabilities")}
    binds = {r["binding_id"]: (r["capability_id"], r["kernel_op_id"], r["provider"], r["engine_module"], r["adapter_class"],
                               r["priority"], r["is_active"]) for r in await c.fetch("SELECT * FROM bindings")}
    v = await c.fetchrow("SELECT capability_version, binding_version, risk_policy_version, authorization_version,"
                         " worker_runtime_version, model_version FROM registry_versions")
    return ops, caps, binds, None if v is None else tuple(v)


def _version_tuple(doc: dict) -> tuple:
    v = doc["versions"]
    return tuple(v[k] for k in VERSION_KEYS)


def _plan(doc: dict, current: tuple) -> Plan:
    ops, caps, binds, versions = current
    plan = Plan()
    for table, rows, rowfn, cur in (("kernel_ops", doc.get("kernel_ops") or [], _op_row, ops),
                                    ("capabilities", doc.get("capabilities") or [], _cap_row, caps),
                                    ("bindings", doc.get("bindings") or [], _bind_row, binds)):
        wanted = {r["id"]: rowfn(r) for r in rows}
        plan.add[table] = sorted(i for i in wanted if i not in cur)
        plan.change[table] = sorted(i for i in wanted if i in cur and cur[i] != wanted[i])
        plan.missing_from_file[table] = sorted(i for i in cur if i not in wanted)
    plan.versions_change = versions != _version_tuple(doc)
    return plan


async def plan(database: Database, doc: dict) -> Plan:
    async with database.transaction() as c:
        return _plan(doc, await _current(c))


async def apply(database: Database, doc: dict) -> Plan:
    """Validate, check the version rule and write everything in one transaction. Raises ValueError with the reasons."""
    errors = validate(doc)
    if errors:
        raise ValueError("; ".join(errors))
    async with database.transaction() as c:
        await c.execute("LOCK TABLE registry_versions IN EXCLUSIVE MODE")
        current = await _current(c)
        result = _plan(doc, current)
        if current[3] is not None and result.content_changes and not result.versions_change:
            raise ValueError("the catalog changed but its versions did not: bump `versions` (every plan pins them)")
        # operations first with no inverse, then the inverse links (they reference each other)
        for o in doc.get("kernel_ops") or []:
            row = _op_row(o)
            await c.execute(
                "INSERT INTO kernel_ops (kernel_op_id, mutation, risk_floor, cost, timeout_seconds, retry_safety, truth_state,"
                " observation_method, observation_expects_absent, observation_identifier_field) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)"
                " ON CONFLICT (kernel_op_id) DO UPDATE SET mutation = EXCLUDED.mutation, risk_floor = EXCLUDED.risk_floor,"
                " cost = EXCLUDED.cost, timeout_seconds = EXCLUDED.timeout_seconds, retry_safety = EXCLUDED.retry_safety,"
                " truth_state = EXCLUDED.truth_state, observation_method = EXCLUDED.observation_method,"
                " observation_expects_absent = EXCLUDED.observation_expects_absent,"
                " observation_identifier_field = EXCLUDED.observation_identifier_field",
                o["id"], row[0], row[1], row[2], row[3], row[4], row[5], row[7], row[8], row[9])
        for o in doc.get("kernel_ops") or []:
            await c.execute("UPDATE kernel_ops SET inverse = $2 WHERE kernel_op_id = $1", o["id"], o.get("inverse"))
        for k in doc.get("capabilities") or []:
            r = _cap_row(k)
            await c.execute(
                "INSERT INTO capabilities (capability_id, name, intent, mutation, risk_floor, risk_rule, risk_implied, truth_state)"
                " VALUES ($1,$2,$3,$4,$5,$6,$7,$8) ON CONFLICT (capability_id) DO UPDATE SET name = EXCLUDED.name,"
                " intent = EXCLUDED.intent, mutation = EXCLUDED.mutation, risk_floor = EXCLUDED.risk_floor,"
                " risk_rule = EXCLUDED.risk_rule, risk_implied = EXCLUDED.risk_implied, truth_state = EXCLUDED.truth_state",
                k["id"], *r)
        for b in doc.get("bindings") or []:
            r = _bind_row(b)
            await c.execute(
                "INSERT INTO bindings (binding_id, capability_id, kernel_op_id, provider, engine_module, adapter_class, priority,"
                " is_active) VALUES ($1,$2,$3,$4,$5,$6,$7,$8) ON CONFLICT (binding_id) DO UPDATE SET capability_id = EXCLUDED.capability_id,"
                " kernel_op_id = EXCLUDED.kernel_op_id, provider = EXCLUDED.provider, engine_module = EXCLUDED.engine_module,"
                " adapter_class = EXCLUDED.adapter_class, priority = EXCLUDED.priority, is_active = EXCLUDED.is_active",
                b["id"], *r)
        v = _version_tuple(doc)
        await c.execute(
            "INSERT INTO registry_versions (singleton, capability_version, binding_version, risk_policy_version,"
            " authorization_version, worker_runtime_version, model_version) VALUES (true,$1,$2,$3,$4,$5,$6)"
            " ON CONFLICT (singleton) DO UPDATE SET capability_version = EXCLUDED.capability_version,"
            " binding_version = EXCLUDED.binding_version, risk_policy_version = EXCLUDED.risk_policy_version,"
            " authorization_version = EXCLUDED.authorization_version, worker_runtime_version = EXCLUDED.worker_runtime_version,"
            " model_version = EXCLUDED.model_version", *v)
    return result
