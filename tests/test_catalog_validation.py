"""Catalog validation: every rule that keeps an unverifiable or inconsistent operation out of the registry."""
import copy
import sys
from pathlib import Path

import yaml

from adapters.postgres import catalog

EXAMPLE = yaml.safe_load((Path(__file__).resolve().parent.parent / "docs" / "catalog" / "catalog.example.yaml").read_text(encoding="utf-8"))


def _doc(**edit):
    doc = copy.deepcopy(EXAMPLE)
    for path, value in edit.items():
        target = doc
        *parents, last = path.split("__")
        for p in parents:
            target = target[int(p)] if p.isdigit() else target[p]
        if value is KeyError:
            del target[int(last) if last.isdigit() else last]
        else:
            target[int(last) if last.isdigit() else last] = value
    return doc


def _problems(doc):
    return " | ".join(catalog.validate(doc))


def test_the_example_catalog_is_valid():
    assert catalog.validate(EXAMPLE) == []


def test_a_production_write_or_delete_without_an_observation_method_is_refused_and_a_draft_is_not():
    assert "needs observation.method" in _problems(_doc(kernel_ops__1__observation=KeyError))
    assert "needs observation.method" in _problems(_doc(kernel_ops__2__observation={"identifier_field": "id"}))
    draft = _doc(kernel_ops__1__observation=KeyError, kernel_ops__1__truth_state="DRAFT")
    draft["capabilities"][1]["truth_state"] = "DRAFT"
    draft["bindings"][1]["is_active"] = False
    assert catalog.validate(draft) == []


def test_references_types_ranges_and_consistency_are_checked():
    cases = {
        "inverse crm.nope": _doc(kernel_ops__1__inverse="crm.nope"),
        "its own inverse": _doc(kernel_ops__1__inverse="crm.contact_create"),
        "risk_floor must be between 0 and 1": _doc(kernel_ops__0__risk_floor=1.5),
        "cost must be a whole number": _doc(kernel_ops__0__cost=0),
        "retry_safety": _doc(kernel_ops__0__retry_safety="sometimes"),
        "mutation must be one of": _doc(kernel_ops__0__mutation="X"),
        "unknown fields": _doc(kernel_ops__0__colour="red"),
        "capability cap.zzz is not in this file": _doc(bindings__0__capability="cap.zzz"),
        "kernel_op crm.zzz is not in this file": _doc(bindings__0__kernel_op="crm.zzz"),
        "differs from operation mutation": _doc(bindings__0__kernel_op="crm.contact_create"),
        "duplicate id": _doc(kernel_ops__1__id="crm.contact_list"),
        "more than one production capability": _doc(capabilities__1__intent="contact.list"),
        "has no active binding": _doc(bindings__0__is_active=False),
        "expects_absent only makes sense for a delete": _doc(kernel_ops__1__observation={"method": "get_contact", "expects_absent": True}),
        "a read needs no observation": _doc(kernel_ops__0__observation={"method": "get_contact"}),
        "unknown top-level keys": _doc(extras=[]),
        "versions must give": _doc(versions__model=""),
    }
    for expected, doc in cases.items():
        assert expected in _problems(doc), (expected, _problems(doc))


def test_garbage_input_is_reported_not_raised():
    assert "must be a mapping" in _problems([])
    assert "must be a list of mappings" in _problems({"versions": EXAMPLE["versions"], "kernel_ops": "x"})


def test_the_committed_catalog_file_is_valid():
    """docs/catalog/catalog.yaml is what the owner loads: it must always pass validation (also after the owner edits it)."""
    path = Path(__file__).resolve().parent.parent / "docs" / "catalog" / "catalog.yaml"
    assert catalog.validate(yaml.safe_load(path.read_text(encoding="utf-8"))) == []
