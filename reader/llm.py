"""The only place the Claude API is called.

Every call is tied to a pipeline stage, which fixes its model, effort and output limit
(config/settings.toml), its structured-output schema, and the run budget.
"""

from __future__ import annotations

import os
from typing import TypeVar

import anthropic
import pydantic
from pydantic import BaseModel

from .budget import Budget
from .config import Settings

T = TypeVar("T", bound=BaseModel)

# Always talk to Anthropic directly, even if the shell sets ANTHROPIC_BASE_URL for another tool.
API_URL = "https://api.anthropic.com"

# Opus 5 / Fable safety classifiers can decline a request; "default" re-runs a declined
# request server-side on Anthropic's recommended fallback model.
FALLBACK_MODELS = ("claude-opus-5", "claude-fable-5")
FALLBACK_BETA = "server-side-fallback-2026-07-01"

# Shortest system prompt each model will cache (tokens). Below this, caching silently does nothing.
CACHE_MINIMUM = {"claude-fable-5": 512, "claude-opus-5": 512, "claude-sonnet-5": 1024, "claude-haiku-4-5": 4096}


class StageError(RuntimeError):
    pass


class BudgetExceeded(StageError):
    pass


class OutputTruncated(StageError):
    pass


WORKSPACE_HELP = (
    "This API key works across workspaces, so Reader needs to know which workspace to use.\n"
    "Find the workspace ID (it starts with wrkspc_) in the ID column of Settings > Workspaces at\n"
    "platform.claude.com, then run ./set-workspace.sh and paste it when asked."
)


def make_client() -> anthropic.Anthropic:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise StageError("No Anthropic API key found. Run ./set-api-key.sh first.")
    # Keys that span several workspaces must name one on every request.
    workspace = os.environ.get("ANTHROPIC_WORKSPACE_ID")
    headers = {"anthropic-workspace-id": workspace} if workspace else None
    return anthropic.Anthropic(api_key=key, base_url=API_URL, max_retries=3, timeout=600, default_headers=headers)


def _is_workspace_error(e: anthropic.APIStatusError) -> bool:
    return "scoped to a workspace" in str(e.message) or "anthropic-workspace-id" in str(e.message)


class LLM:
    def __init__(self, settings: Settings, budget: Budget, dry_run: bool = False):
        self.settings = settings
        self.budget = budget
        self.dry_run = dry_run
        self.client = None if dry_run else make_client()
        self.calls: list[dict] = []  # per-call log for the run report
        self.outputs: list[dict] = []  # every structured output, saved with the run

    def cacheable(self, stage: str, system: str) -> bool:
        model = self.settings.stage(stage).model
        minimum = next((v for k, v in CACHE_MINIMUM.items() if model.startswith(k)), 4096)
        return Budget.tokens_for(len(system)) >= minimum

    def call(self, stage: str, system: str, user: str, schema: type[T], *, expected_output: int,
             reserve: float = 0.0, cache_system: bool = False, label: str = "") -> T | None:
        """Run one structured call. Returns None in dry-run mode."""
        cfg = self.settings.stage(stage)
        estimate = self.budget.estimate(cfg.model, len(system) + len(user), expected_output)
        if self.dry_run:
            self.budget.project(stage, cfg.model, len(system) + len(user), expected_output, note=label)
            return None
        if not self.budget.fits(estimate, reserve):
            raise BudgetExceeded(
                f"{stage}: estimated ${estimate:.2f} would exceed the ${self.budget.max_usd:.2f} run budget"
            )

        system_block = {"type": "text", "text": system}
        if cache_system and self.cacheable(stage, system):
            system_block["cache_control"] = {"type": "ephemeral"}
        kwargs = dict(
            model=cfg.model,
            max_tokens=cfg.max_tokens,
            system=[system_block],
            messages=[{"role": "user", "content": user}],
            output_format=schema,
        )
        if cfg.effort:
            kwargs["output_config"] = {"effort": cfg.effort}

        try:
            if cfg.model.startswith(FALLBACK_MODELS):
                resp = self.client.beta.messages.parse(betas=[FALLBACK_BETA], fallbacks="default", **kwargs)
            else:
                resp = self.client.messages.parse(**kwargs)
        except anthropic.AuthenticationError as e:
            raise StageError("The API key was rejected. Run ./set-api-key.sh again with a valid key.") from e
        except anthropic.NotFoundError as e:
            raise StageError(f"Model {cfg.model} is not available to this API key ({stage} stage).") from e
        except anthropic.RateLimitError as e:
            raise StageError(f"Rate limited during the {stage} stage; try again in a few minutes.") from e
        except anthropic.APIStatusError as e:
            if _is_workspace_error(e):
                raise StageError(WORKSPACE_HELP) from e
            raise StageError(f"API error in the {stage} stage (HTTP {e.status_code}): {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise StageError(f"Could not reach the Anthropic API during the {stage} stage.") from e
        except pydantic.ValidationError as e:
            # The SDK validates the JSON before we see the stop reason; an output cut off at the token limit
            # arrives here as invalid JSON. Treat it as the truncation it almost always is.
            raise OutputTruncated(f"{stage}: output ended mid-JSON, almost certainly at the {cfg.max_tokens}-token limit "
                                  f"({label}): {str(e).splitlines()[-1][:160]}") from e

        cost = self.budget.record(stage, resp.model, resp.usage)
        self.calls.append({
            "stage": stage, "label": label, "model": resp.model, "stop_reason": resp.stop_reason,
            "input": resp.usage.input_tokens, "output": resp.usage.output_tokens,
            "cache_read": resp.usage.cache_read_input_tokens or 0,
            "cache_write": resp.usage.cache_creation_input_tokens or 0,
            "cost": round(cost, 5), "request_id": getattr(resp, "_request_id", None),
        })
        if resp.stop_reason == "refusal":
            raise StageError(f"{stage}: the model declined this request ({label}).")
        if resp.stop_reason == "max_tokens":
            raise OutputTruncated(f"{stage}: output hit the {cfg.max_tokens}-token limit ({label}).")
        parsed = resp.parsed_output
        if parsed is None:
            raise StageError(f"{stage}: no structured output returned ({label}).")
        self.outputs.append({"stage": stage, "label": label, "output": parsed.model_dump()})
        return parsed


def check_access(settings: Settings) -> int:
    """`./brief doctor`: confirm the key works and every configured model is available. Free."""
    try:
        client = make_client()
    except StageError as e:
        print(e)
        return 1
    status = 0
    seen = set()
    for stage in ("screen", "find", "check", "write", "audit"):
        model = settings.stage(stage).model
        if model in seen:
            continue
        seen.add(model)
        try:
            info = client.models.retrieve(model)
            print(f"  ok   {model:22} ({info.display_name})")
        except anthropic.AuthenticationError:
            print("The API key was rejected. Run ./set-api-key.sh again with a valid key.")
            return 1
        except anthropic.NotFoundError:
            print(f"  --   {model:22} not available to this key; change it in config/settings.toml")
            status = 1
        except anthropic.APIConnectionError:
            print("Could not reach the Anthropic API. Check the internet connection.")
            return 1
        except anthropic.APIStatusError as e:
            if _is_workspace_error(e):
                print(WORKSPACE_HELP)
                return 1
            print(f"Anthropic returned an error (HTTP {e.status_code}): {e.message}")
            return 1
    if status == 0:
        print("API key works and all configured models are available.")
    return status
