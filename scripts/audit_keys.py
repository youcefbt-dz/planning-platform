"""List i18n keys used in code/templates that no catalog defines (and keys defined but never referenced)."""
import re, sys
from pathlib import Path
from app import create_app

ROOT = Path(__file__).resolve().parents[1] / "app"
app = create_app({"TESTING": True})
tables = app.extensions["catalogs"].tables
defined = set(tables["en"])

static = re.compile(r"""\bt[nh]?\(\s*['"]([a-zA-Z0-9_.]+)['"]""")
dynamic = re.compile(r"""\bt[nh]?\(\s*['"]([a-zA-Z0-9_.]+\.)['"]\s*(?:~|\+)""")
# any string literal that looks like a catalog key and is passed around (tabs, labels, manifests)
literal = re.compile(r"""['"]((?:[a-z_]+)\.(?:[a-z_0-9]+)(?:\.[a-z_0-9]+)*)['"]""")
prefixes = {k.split(".")[0] for k in defined}

used, dyn = {}, {}
for f in list(ROOT.rglob("*.html")) + list(ROOT.rglob("*.py")):
    txt = f.read_text(encoding="utf-8")
    for m in static.finditer(txt):
        (dyn if m.group(1).endswith(('.', '_')) else used).setdefault(m.group(1), f)
    for m in dynamic.finditer(txt): dyn.setdefault(m.group(1), f)

missing = sorted(k for k in used if k not in defined and not any(d.startswith(k + ".") for d in defined))
for k in missing: print("MISSING", k, used[k].relative_to(ROOT.parent))
for p, f in sorted(dyn.items()):
    if not any(d.startswith(p) for d in defined): print("MISSING-PREFIX", p, f.relative_to(ROOT.parent))

# manifest labels
reg = app.extensions["modules"]
for m in reg.discovered.values():
    for k in [m.label_key] + [t.key for t in m.tabs if hasattr(t, "key")]:
        pass
    for t in m.tabs:
        for attr in ("label", "label_key", "key"):
            v = getattr(t, attr, None)
            if isinstance(v, str) and "." in v and v not in defined: print("MISSING-TAB", m.id, v)
    for a in m.create:
        for attr in ("label_key", "label"):
            v = getattr(a, attr, None)
            if isinstance(v, str) and "." in v and v not in defined: print("MISSING-CREATE", m.id, v)
    for e in m.entities:
        v = getattr(e, "label_key", None) or getattr(e, "label", None)
        if isinstance(v, str) and v not in defined: print("MISSING-ENTITY", m.id, v)
    if m.label_key not in defined: print("MISSING-MODULE", m.label_key)
print(len(used), "static keys,", len(missing), "missing")
sys.exit(1 if missing else 0)
