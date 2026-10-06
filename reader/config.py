"""Loads settings, the source registry, the watchlist, and the local .env file.

`config/settings.toml` is shared; `config/local.toml`, if present, is this machine's own settings (which
sources to read, where to copy briefs) and overrides it key by key. local.toml is never committed.
"""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
LOCAL_SETTINGS = CONFIG_DIR / "local.toml"
DATA_DIR = ROOT / "data"
BRIEFS_DIR = ROOT / "briefs"


@dataclass(frozen=True)
class Source:
    id: str
    publisher: str
    section: str
    url: str
    kind: str  # news | official | wire | institutional | calendar
    tier: int
    owner: str
    format: str = "rss"
    model_ok: bool = True
    enabled: bool = True
    needs_contact: bool = False
    categories: tuple[str, ...] = ()  # keep only entries tagged with one of these (feeds that mix sections)
    day_only: bool = False  # the source gives dates, not times: stamped at first sight, printed as a day
    terms: str = "not-read"  # official | no-clause | restricts | not-read: what the publisher's terms say (see TERMS)
    terms_note: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "categories", tuple(self.categories))

    @property
    def label(self) -> str:
        return f"{self.publisher} · {self.section}"


# What each source's terms of use say about automated reading and AI use, as read on 2026-10-01.
TERMS = {
    "official": "government, central bank or regulator publication",
    "no-clause": "the publisher's terms have no clause against automated reading or AI use",
    "restricts": "the publisher's terms restrict automated access, AI use, or both",
    "not-read": "terms not reviewed",
}

# Which sources a machine reads ([sources] policy in local.toml). Each is the one before it plus more.
POLICIES = {
    "official": ("official",),
    "unrestricted": ("official", "no-clause"),
    "all": ("official", "no-clause", "restricts", "not-read"),
}


@dataclass(frozen=True)
class StageModel:
    model: str
    max_tokens: int
    effort: str | None = None
    extra: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Company:
    name: str
    ticker: str
    aliases: tuple[str, ...] = ()

    @property
    def names(self) -> tuple[str, ...]:
        return (self.name, *self.aliases)


@dataclass
class Settings:
    raw: dict
    sources: list[Source]
    companies: list[Company]
    themes: list[str]

    @property
    def tz(self) -> str:
        return self.raw["brief"]["timezone"]

    def stage(self, name: str) -> StageModel:
        cfg = dict(self.raw["models"][name])
        model = cfg.pop("model")
        max_tokens = int(cfg.pop("max_tokens"))
        effort = cfg.pop("effort", None) or None
        return StageModel(model=model, max_tokens=max_tokens, effort=effort, extra=cfg)

    def price(self, model: str) -> dict:
        prices = self.raw["prices"]
        if model in prices:
            return prices[model]
        # Dated or fallback model IDs: match on the family prefix.
        for key, value in prices.items():
            if model.startswith(key):
                return value
        raise KeyError(f"No price configured for model {model!r} in config/settings.toml")

    @property
    def user_agent(self) -> str:
        net = self.raw["network"]
        ua = net["user_agent"]
        if net.get("contact_email"):
            ua = f"{ua} {net['contact_email']}"
        return ua

    @property
    def has_contact(self) -> bool:
        return bool(self.raw["network"].get("contact_email"))

    @property
    def source_policy(self) -> str:
        """"official", "unrestricted" or "all"; empty until this machine's owner has chosen."""
        return str(self.raw.get("sources", {}).get("policy", "")).strip()

    def policy_allows(self, source: Source) -> bool:
        """Unset counts as "all", so library calls and tests are unaffected; the commands that fetch refuse
        to start until a policy is chosen (cli.py)."""
        allowed = POLICIES.get(self.source_policy or "all")
        if allowed is None:
            raise ValueError(f"Unknown sources policy {self.source_policy!r}; use one of: {', '.join(POLICIES)}")
        return source.terms in allowed and source.id not in self.raw.get("sources", {}).get("off", [])

    def active_sources(self, kinds: tuple[str, ...] | None = None) -> list[Source]:
        out = []
        for s in self.sources:
            if not s.enabled or (s.needs_contact and not self.has_contact) or not self.policy_allows(s):
                continue
            if kinds and s.kind not in kinds:
                continue
            out.append(s)
        return out

    def source(self, source_id: str) -> Source:
        for s in self.sources:
            if s.id == source_id:
                return s
        raise KeyError(source_id)


def load_env(path: Path = ROOT / ".env") -> None:
    """Minimal .env reader: KEY=VALUE lines; existing environment variables win."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def merge(base: dict, override: dict) -> dict:
    """Tables merge key by key; any other value in `override` replaces the one in `base`."""
    out = dict(base)
    for key, value in override.items():
        out[key] = merge(out[key], value) if isinstance(value, dict) and isinstance(out.get(key), dict) else value
    return out


def load_settings(local: Path | None = LOCAL_SETTINGS) -> Settings:
    with open(CONFIG_DIR / "settings.toml", "rb") as f:
        raw = tomllib.load(f)
    if local and local.exists():
        with open(local, "rb") as f:
            raw = merge(raw, tomllib.load(f))
    with open(CONFIG_DIR / "sources.toml", "rb") as f:
        src = tomllib.load(f)
    with open(CONFIG_DIR / "watchlist.toml", "rb") as f:
        wl = tomllib.load(f)
    sources = [Source(**s) for s in src.get("source", [])]
    ids = [s.id for s in sources]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate source id in config/sources.toml")
    unknown = sorted({s.terms for s in sources} - set(TERMS))
    if unknown:
        raise ValueError(f"Unknown terms value in config/sources.toml: {', '.join(unknown)}")
    companies = [
        Company(name=c["name"], ticker=c["ticker"], aliases=tuple(c.get("aliases", ())))
        for c in wl.get("companies", [])
    ]
    return Settings(raw=raw, sources=sources, companies=companies, themes=list(wl.get("themes", [])))


def company_pattern(companies: list[Company]) -> re.Pattern:
    """Whole-word, case-sensitive matcher for any watchlist company name or alias."""
    names = sorted({n for c in companies for n in c.names}, key=len, reverse=True)
    alternation = "|".join(re.escape(n) for n in names)
    return re.compile(rf"(?<![\w&-])(?:{alternation})(?![\w&-])")


def set_local(section: str, key: str, value: str, path: Path = LOCAL_SETTINGS) -> None:
    """Sets one string value in local.toml, keeping every other line (and comment) as it was."""
    line = f'{key} = "{value}"'
    lines = path.read_text().splitlines() if path.exists() else [
        "# This machine's own Reader settings. They override config/settings.toml and are never committed."]
    header = f"[{section}]"
    if header not in (l.strip() for l in lines):
        lines += ["", header, line]
    else:
        start = next(i for i, l in enumerate(lines) if l.strip() == header)
        end = next((i for i in range(start + 1, len(lines)) if lines[i].lstrip().startswith("[")), len(lines))
        for i in range(start + 1, end):
            if re.match(rf"\s*{re.escape(key)}\s*=", lines[i]):
                lines[i] = line
                break
        else:
            lines.insert(end if lines[end - 1].strip() else end - 1, line)
    path.write_text("\n".join(lines) + "\n")
