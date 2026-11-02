"""The hub: finds providers and tasks, applies privacy rules, runs the chain, records every call."""
from __future__ import annotations

import importlib
import logging
import pkgutil
import time
from datetime import datetime, timedelta
from pathlib import Path

import yaml

from app.ai import voice
from app.ai.base import AIRequest, AIResult, Provider, ProviderError, RateLimited, Task
from app.ai.models import AICall
from app.extensions import db

log = logging.getLogger(__name__)
CONFIG = Path(__file__).resolve().parents[2] / "config" / "ai.yaml"


def _discover(package: str, attr: str) -> dict:
    pkg = importlib.import_module(package)
    found = {}
    for info in pkgutil.iter_modules(pkg.__path__):
        if info.name.startswith("_"):
            continue
        try:
            obj = getattr(importlib.import_module(f"{package}.{info.name}"), attr, None)
        except Exception:  # a broken plug-in must not take the product down
            log.exception("AI plug-in %s.%s failed to import", package, info.name)
            continue
        if obj is not None and obj.name:
            found[obj.name] = obj
    return found


class Hub:
    def __init__(self, path: Path = CONFIG):
        self.cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {} if path.is_file() else {}
        self.providers: dict[str, Provider] = _discover("app.ai.providers", "provider")
        self.tasks: dict[str, Task] = _discover("app.ai.tasks", "task")
        self._cool: dict[str, float] = {}   # provider -> monotonic time until which it is skipped (it just said "rate limited")

    # -- a provider that answered "rate limited" is parked, so the next calls go straight to the next one instead of waiting for it again ----
    def cool(self, name: str, seconds: float) -> None:
        self._cool[name] = time.monotonic() + max(5.0, float(seconds))

    def cooling(self, name: str) -> bool:
        return self._cool.get(name, 0) > time.monotonic()

    # -- configuration ----------------------------------------------------------
    @property
    def privacy(self) -> dict:
        return {"sample_rows": 8, "max_cell_chars": 60, "require_consent": True, "external_calls_per_org_per_day": 100, "timeout_seconds": 45, **(self.cfg.get("privacy") or {})}

    def provider_cfg(self, name: str) -> dict:
        return (self.cfg.get("providers") or {}).get(name) or {}

    def is_local(self, name: str) -> bool:
        return name == "offline" or bool(self.provider_cfg(name).get("local", False))

    def chain(self) -> list[str]:
        names = [n for n in (self.cfg.get("chain") or ["offline"]) if n in self.providers and n != "offline"]
        return names + ["offline"]

    def status(self) -> list[dict]:
        """For the settings page: what is configured and what would be used."""
        out = []
        for n in self.chain():
            p, cfg = self.providers[n], self.provider_cfg(n)
            out.append({"name": n, "available": p.available(cfg), "local": self.is_local(n)})
        return out

    def external_available(self) -> bool:
        return any(s["available"] and not s["local"] for s in self.status())

    # -- privacy gate -------------------------------------------------------------
    def external_allowed(self, org, *, consent: bool, read_only: bool) -> tuple[bool, str]:
        if read_only:
            return False, "demo"          # anonymous visitors of the sample workspace never spend the owner's API budget
        if self.privacy["require_consent"] and not consent:
            return False, "consent"
        if org is not None:
            since = datetime.utcnow() - timedelta(days=1)
            used = AICall.query.filter(AICall.org_id == org.id, AICall.external.is_(True), AICall.created_at >= since).count()
            if used >= int(self.privacy["external_calls_per_org_per_day"]):
                return False, "quota"
        return True, ""

    # -- run -------------------------------------------------------------------------
    def run(self, task_name: str, inputs: dict, *, lang: str = "ar", org=None, user=None, consent: bool = False, read_only: bool = False) -> AIResult:
        task = self.tasks.get(task_name)
        if task is None:
            raise KeyError(f"unknown AI task '{task_name}'")
        tcfg = (self.cfg.get("tasks") or {}).get(task_name) or {}
        enabled = bool(self.cfg.get("enabled", True)) and tcfg.get("enabled", True)
        inputs = {**inputs, "_lang": lang, "_company": voice.company_context(org, lang)}
        allowed, why = self.external_allowed(org, consent=consent, read_only=read_only)
        system, user_msg = task.prompt(inputs, lang)
        errors: list[str] = []
        wanted_model = False  # a model provider exists in the chain but was not used → "fell back"
        for name in (self.chain() if enabled else ["offline"]):
            prov, cfg = self.providers[name], self.provider_cfg(name)
            if not prov.available(cfg):
                continue
            if name != "offline" and self.cooling(name):
                errors.append(f"{name}: skipped (rate limited a moment ago)")
                wanted_model = True
                continue
            local = self.is_local(name)
            if not local and not allowed:
                errors.append(f"{name}: skipped ({why})")
                wanted_model = True
                continue
            # A model gets two tries: when our checks reject its answer (an invented number, a filler opener, a transliterated term…)
            # it is told exactly why and asked once more, instead of silently dropping to the plain rule-based text.
            feedback, done, last_err = "", None, None
            for attempt in range(1 if name == "offline" else 2):
                inputs["_attempt"] = attempt          # a task may be strict on the first answer and lenient on the second
                req = AIRequest(task=task, inputs=inputs, lang=lang, system=system, user=user_msg + feedback, schema=task.schema,
                                max_tokens=int(tcfg.get("max_tokens", 1500)), temperature=float(tcfg.get("temperature", 0)),
                                timeout=int(self.privacy["timeout_seconds"]))
                t0 = time.monotonic()
                try:
                    data, model = prov.complete(req, cfg)
                    data = task.validate(data, inputs)
                except ProviderError as e:          # network / auth / unparsable: asking again would not help
                    last_err = e
                    ms = int((time.monotonic() - t0) * 1000)
                    errors.append(f"{name}: {e}")
                    if isinstance(e, RateLimited):
                        self.cool(name, e.retry_after)
                    log.warning("AI task %s failed on provider %s: %s", task_name, name, e)
                    self._log(org, user, task_name, name, "", not local, False, str(e), ms, req)
                    break
                except (ValueError, KeyError, TypeError) as e:   # the model answered, our checks refused it
                    last_err = e
                    ms = int((time.monotonic() - t0) * 1000)
                    errors.append(f"{name}: {e}")
                    log.warning("AI task %s rejected on provider %s (attempt %d): %s", task_name, name, attempt + 1, e)
                    self._log(org, user, task_name, name, "", not local, False, str(e), ms, req)
                    feedback = (f"\n\nYOUR PREVIOUS ANSWER WAS REJECTED: {e}. Write it again and fix exactly that. "
                                "Use only the figures you were given, plain wording, and the product's vocabulary.")
                    continue
                ms = int((time.monotonic() - t0) * 1000)
                done = (data, model, ms)
                break
            if done is None:
                wanted_model = wanted_model or (name != "offline" and last_err is not None)
                continue
            data, model, ms = done
            if name != "offline":
                self._log(org, user, task_name, name, model, not local, True, "", ms, req)
            return AIResult(data=data, provider=name, model=model, external=not local, fell_back=wanted_model and name == "offline", errors=errors, ms=ms)
        raise RuntimeError("the offline provider must always answer")  # pragma: no cover

    # -- the agent: the first provider that can hold a conversation with tools, through the same privacy gate ----------------------------
    def chat_providers(self, org, *, consent: bool, read_only: bool):
        """-> (candidates, why_not). Candidates are (name, provider, cfg, local) in chain order that can hold a conversation with tools AND
        are allowed; `why_not` explains an empty list: demo | consent | quota | none."""
        allowed, why = self.external_allowed(org, consent=consent, read_only=read_only)
        blocked, out = "", []
        for name in self.chain():
            prov, cfg = self.providers[name], self.provider_cfg(name)
            if not prov.supports_chat or not prov.available(cfg) or self.cooling(name):
                continue
            local = self.is_local(name)
            if not local and not allowed:
                blocked = why
                continue
            out.append((name, prov, cfg, local))
        return out, ("" if out else (blocked or "none"))

    def log_round(self, org, user, task, provider, model, external, ok, error, ms, sent_chars, preview):
        try:
            db.session.add(AICall(org_id=org.id if org else None, user_id=user.id if user is not None and getattr(user, "is_authenticated", False) else None,
                                  task=task, provider=provider, model=model, external=external, ok=ok, error=(error or "")[:300], ms=ms,
                                  sent_chars=sent_chars, sent_preview=preview[:8000] if external else ""))
            db.session.commit()
        except Exception:
            db.session.rollback()
            log.exception("could not record AI call")

    def _log(self, org, user, task, provider, model, external, ok, error, ms, req: AIRequest):
        try:
            sent = req.system + "\n\n" + req.user
            db.session.add(AICall(org_id=org.id if org else None, user_id=user.id if user is not None and getattr(user, "is_authenticated", False) else None,
                                  task=task, provider=provider, model=model, external=external, ok=ok, error=error[:300], ms=ms,
                                  sent_chars=len(sent), sent_preview=sent[:8000] if external else ""))
            db.session.commit()
        except Exception:  # auditing must never break the feature
            db.session.rollback()
            log.exception("could not record AI call")
