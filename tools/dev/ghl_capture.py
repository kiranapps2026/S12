#!/usr/bin/env python3
"""Capture real GoHighLevel (LeadConnector v2) responses for the `crm` adapter (adapter phase, dev only).

Run on your machine against a test location:

    python tools/dev/ghl_capture.py --location-id <LOCATION_ID> --key <PRIVATE_INTEGRATION_TOKEN>
    python tools/dev/ghl_capture.py --location-id <ID> --key <KEY> --writes            # + create/read/delete cases
    python tools/dev/ghl_capture.py --location-id <ID> --key <KEY> --writes --burst    # + 120-request burst (L3)

Standard library only (Python 3.9+). Output: ./ghl_capture_<UTC timestamp>/
    summary.json                     what each check found, mapped to the VERIFY points of
                                     batch_bundles/LAYER_A/ADAPTER_SPECS/ghl_crm.md
    fixtures/<op>/<case>.json        one recorded request/response per case, in the layout of
                                     tests_agent/fixtures/providers/ghl/ (ghl_crm.md §6)

In the output the key is replaced by <key> and the location id by <location_id>; ids of records this script created
become contact_1, note_1, ...; personal fields of records it did not create are masked. Push the folder (or upload it)
and the adapter work turns it into the GHL profile, bindings and offline tests.

With --writes the script creates records whose e-mail / text contain "s12dev", and deletes them at the end.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import random
import string
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

MARKER = "s12dev"
HEADERS_KEPT = ("x-ratelimit-remaining", "x-ratelimit-max", "x-ratelimit-interval-milliseconds",
                "x-ratelimit-daily-remaining", "retry-after", "x-request-id", "cf-ray", "content-type",
                "deprecation", "sunset")
PII_KEYS = {"email", "phone", "firstName", "lastName", "name", "contactName", "fullNameLowerCase",
            "firstNameLowerCase", "lastNameLowerCase", "emailLowerCase", "address1", "city", "postalCode",
            "companyName", "website", "dateOfBirth", "body", "title", "additionalEmails", "additionalPhones"}


class Capture:
    def __init__(self, args: argparse.Namespace) -> None:
        self.base = args.base_url.rstrip("/")
        self.version = args.api_version
        self.key = args.key
        self.location = args.location_id
        self.timeout = args.timeout
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.out = Path(args.out or f"ghl_capture_{stamp}")
        (self.out / "fixtures").mkdir(parents=True, exist_ok=True)
        self.generated = stamp
        self.checks: list[dict] = []
        self.latencies: list[float] = []
        self.created: list[dict] = []          # {"kind", "id", "contactId"}
        self.aliases: dict[str, str] = {}      # real id -> contact_1 / note_1 / task_1
        self.case_count: dict[str, int] = {}

    # ---------------------------------------------------------------- http and recording ----------------------------

    def call(self, op: str, case: str, method: str, path: str, template: str | None = None,
             body: dict | None = None, key: str | None = None) -> tuple[int, object, dict]:
        url = self.base + path
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": f"Bearer {key or self.key}", "Version": self.version, "Accept": "application/json",
            **({"Content-Type": "application/json"} if data is not None else {})})
        started = time.monotonic()
        status, raw, headers, error = 0, "", {}, None
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                status, raw, headers = resp.status, resp.read().decode("utf-8", "replace"), dict(resp.headers)
        except urllib.error.HTTPError as exc:
            status, raw, headers = exc.code, exc.read().decode("utf-8", "replace"), dict(exc.headers or {})
        except Exception as exc:  # noqa: BLE001 - recorded, never raised
            error = f"{type(exc).__name__}: {exc}"
        latency = round((time.monotonic() - started) * 1000, 1)
        if status:
            self.latencies.append(latency)
        try:
            parsed = json.loads(raw) if raw else None
        except ValueError:
            parsed = raw[:2000]
        headers = {k.lower(): v for k, v in headers.items()}
        self._record(op, case, {
            "op": op, "case": case,
            "request": {"method": method, "path": template or path, "body": self._scrub(body)},
            "response": {"status": status, "headers": {k: headers[k] for k in HEADERS_KEPT if k in headers},
                         "header_names": sorted(headers), "body": self._scrub(parsed)},
            "latency_ms": latency, "transport_error": error})
        return status, parsed, headers

    def _record(self, op: str, case: str, record: dict) -> None:
        n = self.case_count.get(f"{op}/{case}", 0) + 1
        self.case_count[f"{op}/{case}"] = n
        folder = self.out / "fixtures" / op
        folder.mkdir(parents=True, exist_ok=True)
        name = case if n == 1 else f"{case}_{n}"
        (folder / f"{name}.json").write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def alias(self, real_id: str, kind: str) -> str:
        if real_id not in self.aliases:
            self.aliases[real_id] = f"{kind}_{sum(1 for v in self.aliases.values() if v.startswith(kind)) + 1}"
        return self.aliases[real_id]

    def _scrub(self, node):
        if node is None:
            return None
        text = json.dumps(node)
        text = text.replace(self.key, "<key>").replace(self.location, "<location_id>")
        for real, alias in self.aliases.items():
            text = text.replace(real, alias)
        return self._mask(json.loads(text))

    def _mask(self, node):
        if isinstance(node, dict):
            ours = any(isinstance(v, str) and MARKER in v.lower() for v in node.values())
            return {k: ("<masked>" if (not ours and k in PII_KEYS and not isinstance(v, (dict, list)) and v is not None)
                        else self._mask(v)) for k, v in node.items()}
        if isinstance(node, list):
            return [self._mask(v) for v in node]
        return node

    def check(self, check_id: str, result: str, finding: str, resolves: str) -> None:
        self.checks.append({"id": check_id, "result": result, "finding": finding, "resolves": resolves})
        print(f"[{check_id}] {result:<4} {finding}")

    # ---------------------------------------------------------------- read-only checks -------------------------------

    def read_only(self) -> bool:
        st, body, hdr = self.call("crm.contact_list", "ok", "POST", "/contacts/search",
                                  body={"locationId": self.location, "pageLimit": 1})
        if st == 0:
            self.check("R1", "FAIL", "GHL not reachable (network, DNS or TLS)", "base URL")
            return False
        if st == 200 and isinstance(body, dict):
            self.check("R1", "PASS", f"POST /contacts/search with Version {self.version} -> 200; keys {sorted(body)}",
                       "ghl_crm.md: base URL, Version header")
            first = (body.get("contacts") or [None])[0]
            cursor = first.get("searchAfter") if isinstance(first, dict) else None
            self.check("R1b", "INFO", f"paging cursor on each contact: searchAfter={json.dumps(cursor)}; total={'total' in body}",
                       "profile paging.next for crm.contact_list")
        else:
            self.check("R1", "FAIL", f"search -> {st}: {message(body)}", "base URL / Version / scope contacts.readonly")
        limits = sorted(k for k in hdr if k.startswith("x-ratelimit"))
        self.check("R1c", "INFO" if limits else "WARN", f"rate-limit headers: {limits or 'none'}", "ghl_crm.md rate-limit headers")

        for size in (100, 101):
            st, body, _ = self.call("crm.contact_list", f"page_limit_{size}", "POST", "/contacts/search",
                                    body={"locationId": self.location, "pageLimit": size})
            self.check(f"R2.{size}", "INFO", f"pageLimit {size} -> {st} {'' if st == 200 else message(body)}", "pageLimit max")

        st, body, _ = self.call("crm.contact_list", "invalid_key_401", "POST", "/contacts/search",
                                body={"locationId": self.location, "pageLimit": 1}, key="s12dev-invalid-key")
        self.check("R3", "PASS" if st == 401 else "WARN", f"invalid key -> {st}: {message(body)}", "ghl_crm.md §2 401 row")

        st, body, _ = self.call("crm.contact_list", "foreign_location_403", "POST", "/contacts/search",
                                body={"locationId": "s12devNoSuchLocation00", "pageLimit": 1})
        self.check("R4", "PASS" if st == 403 else "WARN", f"foreign location -> {st}: {message(body)}",
                   "ghl_crm.md G2; not_found: absent (no access answers 403)")

        st, body, _ = self.call("crm.contact_get", "not_found", "GET", "/contacts/s12devNoSuchContact00", "/contacts/{id}")
        self.check("R5", "INFO", f"missing contact -> {st}: {message(body)}", "not-found shape (classify -> not_found)")

        st, body, _ = self.call("crm.custom_fields", "list", "GET", f"/locations/{self.location}/customFields",
                                "/locations/{locationId}/customFields")
        self.field_id = None
        if st == 200 and isinstance(body, dict):
            match = next((f for f in body.get("customFields") or [] if isinstance(f, dict) and
                          (f.get("name") == "s12_ref" or "s12_ref" in str(f.get("fieldKey", "")))), None)
            if match:
                self.field_id = match.get("id")
                self.check("R6", "PASS", f"custom field s12_ref exists ({match.get('dataType')})", "ghl_crm.md §0 stamp field")
            else:
                self.check("R6", "WARN", "no custom field 's12_ref': create a single-line text field with that name to test stamping",
                           "ghl_crm.md §0 stamp field")
        else:
            self.check("R6", "WARN", f"custom fields -> {st}: {message(body)}", "scope locations/customFields.readonly")
        return True

    # ---------------------------------------------------------------- write checks -----------------------------------

    def writes(self, lag_seconds: int, ryw_runs: int) -> None:
        rand = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
        email, stamp = f"{MARKER}+{rand}@example.com", f"s12-{rand:0<32}"
        contact = {"locationId": self.location, "firstName": "S12", "lastName": f"Dev {rand}", "email": email.upper(),
                   "phone": f"+1555{random.randint(1000000, 9999999)}", "tags": ["S12-Dev"], "source": f"{MARKER}-capture"}
        if self.field_id:
            contact["customFields"] = [{"id": self.field_id, "field_value": stamp}]

        st, body, _ = self.call("crm.contact_create", "ok", "POST", "/contacts/", body=contact)
        cid = (body or {}).get("contact", {}).get("id") if isinstance(body, dict) else None
        if st not in (200, 201) or not cid:
            self.check("W1", "FAIL", f"contact create -> {st}: {message(body)}", "crm.contact_create")
            return
        self.created.append({"kind": "contact", "id": cid, "contactId": cid})
        self.alias(cid, "contact")
        self.check("W1", "PASS", f"contact create -> {st}; id at contact.id", "crm.contact_create identifier path")

        st, body, _ = self.call("crm.contact_get", "ok_after_create", "GET", f"/contacts/{cid}", "/contacts/{id}")
        c = body.get("contact", {}) if isinstance(body, dict) else {}
        self.check("W2", "PASS" if st == 200 else "FAIL", f"GET by id right after create -> {st}", "read_by_id: consistent")
        self.check("W2b", "INFO", f"stored email={c.get('email')!r} (sent upper-case), phone={c.get('phone')!r}, "
                   f"tags={c.get('tags')!r}", "ghl_crm.md §4 normalisation")
        if self.field_id:
            values = [cf.get("value", cf.get("field_value")) for cf in c.get("customFields") or []
                      if isinstance(cf, dict) and cf.get("id") == self.field_id]
            self.check("W2c", "PASS" if stamp in values else "WARN", f"s12_ref read back equals the stamp: {stamp in values}",
                       "stamp in customFields")

        st, body, _ = self.call("crm.contact_create", "duplicate", "POST", "/contacts/", body=contact)
        dup = body.get("contact", {}).get("id") if isinstance(body, dict) and isinstance(body.get("contact"), dict) else None
        if st in (200, 201) and dup and dup != cid:
            self.created.append({"kind": "contact", "id": dup, "contactId": dup})
            self.alias(dup, "contact")
            self.check("W3", "INFO", "duplicate create made a second contact: 'Allow duplicate contact' is ON",
                       "ghl_crm.md §2 duplicate rule")
        else:
            self.check("W3", "INFO", f"duplicate create -> {st}: {message(body)}; meta={json.dumps((body or {}).get('meta') if isinstance(body, dict) else None)}",
                       "ghl_crm.md §2 duplicate rule (400 + meta.contactId)")

        found_after = None
        start = time.monotonic()
        while lag_seconds and time.monotonic() - start < lag_seconds:
            st, body, _ = self.call("crm.contact_list", "search_by_email", "POST", "/contacts/search",
                                    body={"locationId": self.location, "pageLimit": 5, "query": email})
            if any(isinstance(x, dict) and x.get("id") == cid for x in (body or {}).get("contacts", []) if isinstance(body, dict)):
                found_after = round(time.monotonic() - start, 1)
                break
            time.sleep(1)
        if lag_seconds:
            self.check("W4", "INFO" if found_after is not None else "WARN",
                       f"search index lag by e-mail: {found_after if found_after is not None else f'> {lag_seconds}'} s",
                       "ghl_crm.md L1 (light)")
        if self.field_id:
            for label, extra in (("filters customFields.<id> eq", {"filters": [{"field": f"customFields.{self.field_id}", "operator": "eq", "value": stamp}]}),
                                 ("filters customField.<id> eq", {"filters": [{"field": f"customField.{self.field_id}", "operator": "eq", "value": stamp}]}),
                                 ("query = stamp", {"query": stamp})):
                st, body, _ = self.call("crm.contact_create", "probe_stamp_search", "POST", "/contacts/search",
                                        body={"locationId": self.location, "pageLimit": 5, **extra})
                hit = isinstance(body, dict) and any(isinstance(x, dict) and x.get("id") == cid for x in body.get("contacts", []))
                self.check("W4b", "INFO", f"stamp search '{label}' -> {st}, finds ours: {hit}", "custom-field filter syntax")

        for kind, op_create, op_delete, payload in (
                ("note", "crm.note_create", "crm.note_delete", lambda n: {"body": f"{MARKER} note {n}\n\n[ref:{stamp}-{n}]"}),
                ("task", "crm.task_create", "crm.task_delete", lambda n: {
                    "title": f"{MARKER} task {n}", "body": f"{MARKER}\n\n[ref:{stamp}-{n}]", "completed": False,
                    "dueDate": (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")})):
            plural, ids = f"{kind}s", []
            for n in range(1, ryw_runs + 1):
                st, body, _ = self.call(op_create, "ok", "POST", f"/contacts/{cid}/{plural}", f"/contacts/{{contactId}}/{plural}",
                                        body=payload(n))
                iid = body.get(kind, {}).get("id") if isinstance(body, dict) and isinstance(body.get(kind), dict) else None
                if not iid:
                    self.check(f"W5.{kind}", "FAIL", f"{kind} create -> {st}: {message(body)}", op_create)
                    break
                ids.append(iid)
                self.created.append({"kind": kind, "id": iid, "contactId": cid})
                self.alias(iid, kind)
                st, body, _ = self.call(f"crm.{kind}_list", "immediately_after_create", "GET", f"/contacts/{cid}/{plural}",
                                        f"/contacts/{{contactId}}/{plural}")
                seen = isinstance(body, dict) and any(isinstance(x, dict) and x.get("id") == iid for x in body.get(plural, []))
                self.check(f"W5.{kind}.{n}", "PASS" if seen else "WARN", f"{kind} in the list immediately after create: {seen}",
                           "ghl_crm.md L2 (20 runs needed before lookup: consistent)")
            if not ids:
                continue
            first = ids[0]
            path, tpl = f"/contacts/{cid}/{plural}/{first}", f"/contacts/{{contactId}}/{plural}/{{id}}"
            g1, b1, _ = self.call(f"crm.{kind}_get", "ok", "GET", path, tpl)
            d1, bd1, _ = self.call(op_delete, "ok", "DELETE", path, tpl)
            g2, bg2, _ = self.call(f"crm.{kind}_get", "after_delete", "GET", path, tpl)
            d2, bd2, _ = self.call(op_delete, "already_absent", "DELETE", path, tpl)
            self.check(f"W6.{kind}", "INFO", f"get -> {g1}; delete -> {d1} {json.dumps(bd1)}; get after -> {g2} {message(bg2)}; "
                       f"delete again -> {d2} {message(bd2)}", f"{op_delete} body, G3 already-absent, not-found shape")
            self.created = [x for x in self.created if x["id"] != first]

        # the remaining notes and tasks first: whether GHL deletes them with their contact is not assumed
        for item in [x for x in self.created if x["kind"] in ("note", "task")]:
            self.call("cleanup", item["kind"], "DELETE", f"/contacts/{cid}/{item['kind']}s/{item['id']}", "cleanup")
        self.created = [x for x in self.created if x["kind"] == "contact"]

        d1, bd1, _ = self.call("crm.contact_delete", "ok", "DELETE", f"/contacts/{cid}", "/contacts/{id}")
        g2, bg2, _ = self.call("crm.contact_get", "after_delete", "GET", f"/contacts/{cid}", "/contacts/{id}")
        d2, bd2, _ = self.call("crm.contact_delete", "already_absent", "DELETE", f"/contacts/{cid}", "/contacts/{id}")
        self.check("W7", "INFO", f"contact delete -> {d1} {json.dumps(bd1)}; get after -> {g2} {message(bg2)}; "
                   f"delete again -> {d2} {message(bd2)}", "crm.contact_delete body, G3, not-found shape")
        if 200 <= d1 < 300:
            self.created = [x for x in self.created if x["id"] != cid]

    def cleanup(self) -> None:
        for item in reversed(self.created):
            path = (f"/contacts/{item['id']}" if item["kind"] == "contact"
                    else f"/contacts/{item['contactId']}/{item['kind']}s/{item['id']}")
            self.call("cleanup", item["kind"], "DELETE", path, "cleanup")
        self.created.clear()

    def burst(self) -> None:
        def one(_):
            st, _, hdr = self.call("crm.contact_list", "burst", "POST", "/contacts/search",
                                   body={"locationId": self.location, "pageLimit": 1})
            return st, hdr.get("retry-after"), hdr.get("x-ratelimit-remaining")
        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
            results = list(pool.map(one, range(120)))
        counts: dict[int, int] = {}
        for st, _, _ in results:
            counts[st] = counts.get(st, 0) + 1
        retry = next((r for st, r, _ in results if st == 429), None)
        self.check("L3", "INFO", f"120 searches, 12 in parallel: {counts}; first 429 Retry-After={retry}", "ghl_crm.md L3 burst")

    def finalize(self) -> None:
        """Replace ids learned during the run in every file already written (a create's own response included)."""
        for path in (self.out / "fixtures").rglob("*.json"):
            text = path.read_text(encoding="utf-8")
            for real, alias in self.aliases.items():
                text = text.replace(real, alias)
            path.write_text(text.replace(self.key, "<key>").replace(self.location, "<location_id>"), encoding="utf-8")

    def write_summary(self) -> int:
        self.finalize()
        lat = sorted(self.latencies)
        pct = lambda p: lat[min(len(lat) - 1, max(0, int(round(p * len(lat))) - 1))] if lat else None  # noqa: E731
        summary = {"generated_utc": self.generated, "base_url": self.base, "api_version": self.version,
                   "location_id": "<location_id>", "requests": len(lat),
                   "latency_ms": {"p50": pct(0.5), "p95": pct(0.95), "max": lat[-1] if lat else None},
                   "checks": self.checks, "leftover_records": [f"{x['kind']} {self.aliases.get(x['id'], '?')}" for x in self.created]}
        (self.out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print(f"\nlatency p50 {summary['latency_ms']['p50']} ms, p95 {summary['latency_ms']['p95']} ms")
        print(f"output: {self.out.resolve()}  (key and location id replaced; push or upload this folder)")
        return 1 if any(c["result"] == "FAIL" for c in self.checks) else 0


def message(body) -> str:
    if isinstance(body, dict):
        msg = body.get("message") or body.get("error") or ""
        return "; ".join(map(str, msg)) if isinstance(msg, list) else str(msg)
    return str(body or "")[:200]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--location-id", required=True)
    parser.add_argument("--key", required=True, help="Private Integration Token of the test location")
    parser.add_argument("--writes", action="store_true", help="also create, read and delete s12dev test records")
    parser.add_argument("--burst", action="store_true", help="also send 120 searches to observe the rate limit")
    parser.add_argument("--lag-seconds", type=int, default=30, help="how long to wait for the search index (W4)")
    parser.add_argument("--ryw-runs", type=int, default=3, help="notes/tasks created to test read-your-writes (W5)")
    parser.add_argument("--out", help="output folder (default ./ghl_capture_<timestamp>)")
    parser.add_argument("--base-url", default="https://services.leadconnectorhq.com")
    parser.add_argument("--api-version", default="2021-07-28")
    parser.add_argument("--timeout", type=float, default=15.0)
    args = parser.parse_args()

    cap = Capture(args)
    print(f"GHL capture: location {args.location_id}, {cap.base}, Version {cap.version}")
    try:
        if cap.read_only():
            if args.writes:
                try:
                    cap.writes(args.lag_seconds, args.ryw_runs)
                finally:
                    cap.cleanup()
            if args.burst:
                cap.burst()
    finally:
        code = cap.write_summary()
    return code


if __name__ == "__main__":
    sys.exit(main())
