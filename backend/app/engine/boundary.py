"""The engine boundary (36-COPILOT-ENHANCED-CONVERSION Part I).

The platform refuses to send an engagement's code to any conversion engine or
LLM provider that is not on that engagement's allowlist. This module is the one
place that decides; every path that hands code to an engine or provider calls
`require_allowed` first:

- a person-executed engine run is admitted by `app.engine.runs.start`, which
  calls it before anything is recorded;
- the shared LLM provider (32-TEST-COVERAGE-ASSESSMENT Part G) calls it before
  any request that carries source code, once that provider is built.

The allowlist is `engagements.engine_allowlist`: [{provider, organisation}].
It starts empty for every engagement, so nothing is allowed until a person
sets it. An entry with an organisation admits that provider under that
organisation only (for example, GitHub Copilot under the client's own organisation); an entry
without one admits the provider under any organisation, which is what an LLM
provider with no organisation concept needs.

The platform never holds, stores or reads an engine credential. Every value
that reaches the allowlist or a run record passes `refuse_credential`, which
rejects anything shaped like a token, key or password.
"""
import re

from sqlalchemy.orm import Session

from app import models

# Every engine or provider code could be sent to. `kind` is what it is to the
# platform; a provider absent here cannot be allowlisted at all.
PROVIDERS: dict[str, dict] = {
    "github-copilot": {"kind": "conversion_engine", "name": "GitHub Copilot upgrade"},
    "claude-code": {"kind": "llm_provider", "name": "Claude Code (headless claude -p)"},
    "devin": {"kind": "llm_provider", "name": "Devin"},
}

# Providers that send nothing anywhere (32-TEST-COVERAGE-ASSESSMENT G1): `none`
# makes no call and `fake` answers from canned responses in tests. They need no
# allowlist entry.
LOCAL_PROVIDERS = ("none", "fake")

SLUG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")

# Shapes of credentials. Identity, organisation, model and version strings are
# short human-readable names; none of them ever looks like one of these.
CREDENTIAL_SHAPES = (
    re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}"),       # GitHub tokens
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),                    # GitHub fine-grained tokens
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"),                           # API keys (Anthropic, OpenAI)
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),                              # AWS access keys
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),       # JWTs
    re.compile(r"(?i)\b(?:bearer|basic)\s+[A-Za-z0-9+/=._-]{16,}"),   # authorization headers
    re.compile(r"(?i)(?:password|passwd|pwd|secret|token|api[_-]?key|client[_-]?secret)\s*[=:]"),
    re.compile(r"[A-Za-z0-9+/_-]{40,}={0,2}"),                        # any long opaque string
)


class EngineNotAllowed(Exception):
    """Code may not be sent to this engine or provider for this engagement."""


class CredentialRefused(ValueError):
    """A value looked like a credential. The platform never accepts one."""


def refuse_credential(field: str, value: str | None) -> str | None:
    """`value`, unchanged, unless it looks like a credential. The message names the
    field and never echoes the value."""
    if value is None:
        return None
    for shape in CREDENTIAL_SHAPES:
        if shape.search(value):
            raise CredentialRefused(
                f"{field} looks like a credential. The platform never accepts an engine credential: "
                f"sign in to the engine in your own tool and record only who is signed in")
    return value


def _entry(provider: str, organisation: str | None) -> dict:
    if provider not in PROVIDERS:
        raise ValueError(f"unknown provider {provider!r}; known: {', '.join(sorted(PROVIDERS))}")
    if organisation is not None:
        refuse_credential("organisation", organisation)
        if not SLUG.match(organisation):
            raise ValueError(f"organisation {organisation!r} is not an organisation name")
    return {"provider": provider, "organisation": organisation}


def allowlist(engagement: models.Engagement) -> list[dict]:
    return list(engagement.engine_allowlist or [])


def is_allowed(engagement: models.Engagement, provider: str, organisation: str | None = None) -> bool:
    if provider in LOCAL_PROVIDERS:
        return True
    for entry in allowlist(engagement):
        if entry.get("provider") != provider:
            continue
        allowed_org = entry.get("organisation")
        if allowed_org is None:
            return True
        if organisation is not None and organisation.lower() == allowed_org.lower():
            return True
    return False


def require_allowed(engagement: models.Engagement, provider: str, organisation: str | None = None) -> None:
    """Raise EngineNotAllowed unless this engagement's code may go to `provider`
    (under `organisation`, where the allowlist entry names one)."""
    if is_allowed(engagement, provider, organisation):
        return
    entries = allowlist(engagement)
    if not entries:
        why = "its engine allowlist is empty: nothing is allowed until a person sets it"
    else:
        listed = ", ".join(f"{e['provider']}" + (f" under {e['organisation']}" if e.get("organisation") else "")
                           for e in entries)
        why = f"its engine allowlist allows only: {listed}"
    target = provider + (f" under organisation {organisation}" if organisation else "")
    raise EngineNotAllowed(f"Refused: engagement {engagement.id}'s code may not be sent to {target}; {why}")


def allow(db: Session, engagement: models.Engagement, provider: str, organisation: str | None) -> list[dict]:
    entry = _entry(provider, organisation)
    entries = [e for e in allowlist(engagement) if e.get("provider") != provider or e.get("organisation") != organisation]
    entries.append(entry)
    engagement.engine_allowlist = sorted(entries, key=lambda e: (e["provider"], e.get("organisation") or ""))
    db.flush()
    return engagement.engine_allowlist


def revoke(db: Session, engagement: models.Engagement, provider: str, organisation: str | None) -> list[dict]:
    engagement.engine_allowlist = [e for e in allowlist(engagement)
                                   if not (e.get("provider") == provider and e.get("organisation") == organisation)]
    db.flush()
    return engagement.engine_allowlist
