"""Command line: flask seed-demo | modules | ai-status"""
from __future__ import annotations

import click
from flask import Flask, current_app

from app.core import i18n


def register_cli(app: Flask) -> None:
    @app.cli.command("seed-demo")
    @click.option("--lang", "langs", multiple=True, default=i18n.LANGS, help="demo languages (Arabic only for now)")
    def seed_demo(langs):
        """(Re)build the read-only demo organizations."""
        from app.core.demo import create_demo

        for lang in langs:
            org = create_demo(lang)
            click.echo(f"demo[{lang}] -> /app/{org.slug}/")

    @app.cli.command("modules")
    def modules():
        """List modules and whether they are enabled."""
        reg = current_app.extensions["modules"]
        for mid, m in reg.discovered.items():
            state = "enabled " if mid in reg.enabled else "disabled"
            click.echo(f"{state}  {mid:<12} depends_on={m.depends_on} optional={m.optional_depends}")

    @app.cli.command("ai-status")
    def ai_status():
        """Show which AI provider would answer, with which model, and whether its key is set (the key itself is never printed)."""
        import os

        hub = current_app.extensions["ai"]
        click.echo(f".env file: {'found' if (current_app.root_path and os.path.isfile(os.path.join(os.path.dirname(current_app.root_path), '.env'))) else 'NOT found next to wsgi.py'}")
        click.echo(f"chain: {' -> '.join(hub.chain())}\n")
        for name in hub.chain():
            if name == "offline":
                continue
            cfg = hub.provider_cfg(name)
            prov = hub.providers[name]
            key_env, model_env = cfg.get("api_key_env"), cfg.get("model_env")
            key = os.environ.get(key_env, "") if key_env else ""
            try:
                model = prov.model_for(type("R", (), {"task": type("T", (), {"name": "map_columns"})()})(), cfg)
            except Exception as e:  # pragma: no cover
                model = f"? ({e})"
            click.echo(f"{name:<14} available={prov.available(cfg)!s:<5} key={'set (' + str(len(key)) + ' chars)' if key else 'EMPTY':<16} model={model or 'EMPTY'}")
