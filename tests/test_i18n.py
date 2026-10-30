"""Catalog health: valid plurals, Arabic plural forms, and the glossary avoid-lists."""
import re

import pytest
import yaml

from app.core import i18n


def test_plural_tables_use_cldr_categories(app):
    ok = {"zero", "one", "two", "few", "many", "other"}
    for lang, table in app.extensions["catalogs"].tables.items():
        for key, v in table.items():
            if isinstance(v, dict):
                assert set(v) <= ok and "other" in v, (lang, key)


def test_arabic_plurals_pick_right_form(app):
    with app.test_request_context("/"):
        assert i18n.tn("goals.count_objectives", 1) == "هدف واحد"
        assert i18n.tn("goals.count_objectives", 2) == "هدفان"
        assert "أهداف" in i18n.tn("goals.count_objectives", 5)
        assert i18n.tn("goals.count_objectives", 11).endswith("هدفًا")


def test_glossary_avoid_list(app):
    terms = app.extensions["glossary"]
    assert terms, "glossary is empty"
    avoid = {w for t in terms for w in t.get("avoid_ar", [])}
    assert avoid
    for src in app.extensions["catalogs"].sources["ar"]:
        text = open(src, encoding="utf-8").read()
        text = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))
        for w in avoid:
            assert w not in text, f"{src}: avoided term '{w}'"


def test_glossary_entries_are_complete(app):
    for t in app.extensions["glossary"]:
        assert t["id"] and t["ar"]
        assert t["confidence"] in ("settled", "review")


def test_no_key_used_in_code_is_missing():
    import subprocess, sys
    r = subprocess.run([sys.executable, "scripts/audit_keys.py"], capture_output=True, text=True, env={"PYTHONPATH": ".", "PATH": "/usr/bin:/usr/local/bin"})
    bad = [l for l in r.stdout.splitlines() if l.startswith("MISSING") and "swot.add_" not in l]
    assert not bad, bad
