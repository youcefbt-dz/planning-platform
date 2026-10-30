"""Module system — the backbone of the "add / change / delete freely" requirement.

A module is a package  app/modules/<id>/  whose __init__.py exposes `manifest`
(a Manifest). The registry:

  * DISCOVERS every package under app/modules/ and imports its models (the database
    schema is global: toggling a module never drops or hides tables from Alembic);
  * ENABLES only the ones switched on in config/modules.yaml (blueprint, nav, search,
    dashboard widgets, create actions, i18n are loaded for those);
  * validates `depends_on` at boot (fails loudly), while `optional_depends` only
    switches individual UI affordances on or off.

Extension points a module can contribute to (all optional):
    nav          top navigation entry + sub-tabs
    widgets      cards on the organization overview
    create       entries of the "+" menu
    search       a provider  (org, query, limit) -> [Hit]
    entities     entity types it owns (title + URL), for check-ins / links / activity feed
    permissions  {"goals.edit": "member", ...}  minimum role per permission
    seed         function (org, lang) -> None  filling demo data
    hooks        {"name": fn}  extension points a module offers/consumes (e.g. "key_result.saved")
See docs/ADDING_A_MODULE.md for a walkthrough.
"""
from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import yaml
from flask import Blueprint, Flask, url_for

log = logging.getLogger(__name__)
MODULES_DIR = Path(__file__).resolve().parents[1] / "modules"
MODULES_CONFIG = Path(__file__).resolve().parents[2] / "config" / "modules.yaml"


@dataclass
class Tab:
    key: str            # i18n key (already namespaced, e.g. "goals.tabs.list")
    endpoint: str       # flask endpoint
    icon: str = "circle"
    match: tuple[str, ...] = ()  # extra endpoints that mark this tab active
    requires: tuple[str, ...] = ()  # module ids that must be enabled for this tab to show


@dataclass
class Widget:
    id: str
    template: str                      # template path, receives `data`
    loader: Callable[[object], dict]   # (org) -> dict
    order: int = 50
    span: int = 1                      # 1 or 2 columns wide on the overview


@dataclass
class CreateAction:
    key: str        # i18n key of the label
    endpoint: str
    icon: str = "plus"
    permission: str = ""


@dataclass
class Hit:
    type: str        # entity type
    id: int
    title: str
    subtitle: str
    url: str
    icon: str = "circle"


@dataclass
class EntityType:
    key: str                         # "objective"
    label_key: str                   # i18n key for the singular label
    icon: str
    loader: Callable[[int], object]  # id -> model instance (or None)
    title: Callable[[object], str]
    endpoint: str
    id_param: str = "id"


@dataclass
class Manifest:
    id: str
    label_key: str
    icon: str
    blueprint: Blueprint | None = None
    home_endpoint: str = ""
    tabs: list[Tab] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    optional_depends: list[str] = field(default_factory=list)
    shown_with: list[str] = field(default_factory=list)       # hidden from the navigation (and its pages 404) while any of these modules is off
    permissions: dict[str, str] = field(default_factory=dict)
    widgets: list[Widget] = field(default_factory=list)
    create: list[CreateAction] = field(default_factory=list)
    search: Callable | None = None
    entities: list[EntityType] = field(default_factory=list)
    seed: Callable | None = None
    hooks: dict[str, Callable] = field(default_factory=dict)   # named extension points other modules may call: registry.hook("name", …)


class Registry:
    def __init__(self):
        self.discovered: dict[str, Manifest] = {}
        self.enabled: dict[str, Manifest] = {}
        self.order: dict[str, int] = {}

    # -- boot -----------------------------------------------------------------
    def load(self, app: Flask) -> None:
        cfg = yaml.safe_load(MODULES_CONFIG.read_text(encoding="utf-8")) or {}
        conf = cfg.get("modules", {})
        app.config["PRODUCT_DEFAULTS"] = cfg.get("defaults", {})

        for pkg in sorted(p for p in MODULES_DIR.iterdir() if (p / "__init__.py").is_file()):
            mod = importlib.import_module(f"app.modules.{pkg.name}")  # imports models too
            manifest = getattr(mod, "manifest", None)
            if manifest is None:
                log.warning("module %s has no manifest, skipped", pkg.name)
                continue
            self.discovered[manifest.id] = manifest

        for mid, manifest in self.discovered.items():
            c = conf.get(mid, {})
            if c.get("enabled", False):
                self.enabled[mid] = manifest
                self.order[mid] = int(c.get("order", 100))

        for mid, m in self.enabled.items():
            missing = [d for d in m.depends_on if d not in self.enabled]
            if missing:
                raise RuntimeError(
                    f"Module '{mid}' requires {missing}, which is disabled in config/modules.yaml"
                )

        for m in self.enabled.values():
            if m.blueprint is not None:
                app.register_blueprint(m.blueprint)

    # -- queries --------------------------------------------------------------
    def is_enabled(self, mid: str) -> bool:
        return mid in self.enabled

    def ordered(self) -> list[Manifest]:
        return sorted(self.enabled.values(), key=lambda m: self.order.get(m.id, 100))

    def widgets(self) -> list[Widget]:
        ws = [w for m in self.ordered() for w in m.widgets]
        return sorted(ws, key=lambda w: w.order)

    def create_actions(self) -> list[CreateAction]:
        return [a for m in self.ordered() for a in m.create]

    def entity(self, key: str) -> EntityType | None:
        for m in self.ordered():
            for e in m.entities:
                if e.key == key:
                    return e
        return None

    def hook(self, name: str, *args, **kwargs) -> None:
        """Call `name` on every enabled module that registered it. A failing hook never breaks the caller's save."""
        for m in self.ordered():
            fn = m.hooks.get(name)
            if fn:
                try:
                    fn(*args, **kwargs)
                except Exception:
                    log.exception("hook %s of module %s failed", name, m.id)

    def query(self, name: str, *args, **kwargs) -> list:
        """Ask every enabled module that registered `name` and collect the answers that are not None (a failing provider is skipped).
        The read-side twin of hook(): e.g. goals asks "kr.data" and the data module, if enabled, answers; with it off, the list is empty."""
        out = []
        for m in self.ordered():
            fn = m.hooks.get(name)
            if fn:
                try:
                    r = fn(*args, **kwargs)
                except Exception:
                    log.exception("provider %s of module %s failed", name, m.id)
                    continue
                if r is not None:
                    out.append(r)
        return out

    def permissions(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for m in self.enabled.values():
            out.update(m.permissions)
        return out

    def search(self, org, query: str, limit: int = 6) -> list[Hit]:
        hits: list[Hit] = []
        for m in self.ordered():
            if m.search:
                try:
                    hits.extend(m.search(org, query, limit))
                except Exception:  # a broken provider must not break search
                    log.exception("search provider of %s failed", m.id)
        return hits

    def seeders(self):
        """Demo seeders in dependency order (a module seeds after the modules it depends on, whatever its nav position)."""
        mods = [m for m in self.ordered()]
        by_id = {m.id: m for m in mods}
        out, done = [], set()

        def visit(m):
            if m.id in done:
                return
            done.add(m.id)
            for dep in list(m.depends_on or []) + list(m.optional_depends or []):
                if dep in by_id:
                    visit(by_id[dep])
            if m.seed:
                out.append((m.id, m.seed))

        for m in mods:
            visit(m)
        return out
