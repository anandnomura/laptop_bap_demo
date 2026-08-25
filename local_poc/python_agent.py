from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import sys
from pathlib import Path
from typing import Any

from demo_common import json_request


DEFAULT_CONNECTOR_URL = "http://127.0.0.1:8765"
DEFAULT_LLM_URL = "http://127.0.0.1:8080/v1/chat/completions"


def connector_post(connector_url: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    status, result = json_request(f"{connector_url.rstrip('/')}{path}", payload, timeout=10)
    if status != 200:
        raise RuntimeError(result.get("error", f"Connector returned HTTP {status}"))
    return result


def local_chat(llm_url: str, model: str, messages: list[dict[str, str]]) -> str:
    status, result = json_request(
        llm_url,
        {
            "model": model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": 300,
            "stream": False,
        },
        headers={"Authorization": "Bearer local-demo"},
        timeout=120,
    )
    if status != 200:
        detail = result.get("error")
        suffix = f": {detail}" if detail else ""
        raise RuntimeError(f"Local LLM endpoint {llm_url} returned HTTP {status}{suffix}")
    try:
        content = result["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("Local LLM response was not OpenAI chat-completions JSON") from exc
    if isinstance(content, list):
        content = "".join(str(item.get("text", "")) for item in content if isinstance(item, dict))
    return str(content).strip()


def resolve_model(llm_url: str, requested_model: str) -> str:
    if requested_model != "auto":
        return requested_model
    models_url = llm_url.rsplit("/chat/completions", 1)[0] + "/models"
    try:
        status, result = json_request(models_url, method="GET", timeout=5)
        if status == 200 and result.get("data"):
            return str(result["data"][0]["id"])
    except Exception:
        pass
    return "local-model"


def parse_proposal(text: str) -> tuple[dict[str, str], str | None]:
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    try:
        value = json.loads(match.group(0) if match else text)
    except (json.JSONDecodeError, AttributeError):
        value = {}
    operation = str(value.get("operation", "")).lower() if isinstance(value, dict) else ""
    key = str(value.get("key", "")) if isinstance(value, dict) else ""
    reason = str(value.get("reason", "")) if isinstance(value, dict) else ""
    if operation == "read" and re.fullmatch(r"[A-Za-z0-9._-]{1,80}", key):
        return {"operation": operation, "key": key, "reason": reason[:200]}, None
    return (
        {
            "operation": "read",
            "key": "customer-123",
            "reason": "Safe demo fallback after an invalid model proposal",
        },
        "Model output did not match the read-only action schema; used the bounded demo default",
    )


def run_agent(args: argparse.Namespace) -> int:
    session_id = "python-agent-" + secrets.token_hex(4)
    user = os.environ.get("USERNAME") or os.environ.get("USER") or "developer"
    model = resolve_model(args.llm_url, args.model)
    registered = False
    try:
        registration = connector_post(
            args.connector_url,
            "/session/start",
            {
                "session_id": session_id,
                "agent": "local-llm-python-agent",
                "user": user,
                "cwd": str(Path.cwd()),
            },
        )
        registered = True
        session = registration["session"]
        connector_post(
            args.connector_url,
            "/intent",
            {"session_id": session_id, "prompt": args.task},
        )
        connector_post(
            args.connector_url,
            "/agent/event",
            {
                "session_id": session_id,
                "phase": "LLM_REQUEST",
                "details": {"llm_url": args.llm_url, "model": model, "task": args.task},
            },
        )

        proposal_text = local_chat(
            args.llm_url,
            model,
            [
                {
                    "role": "system",
                    "content": (
                        "You are a read-only demo agent. Select one lookup using only this JSON schema: "
                        '{"operation":"read","key":"customer-123","reason":"short reason"}. '
                        "Return JSON only. Never propose writes, deletes, shell commands, URLs, or credentials."
                    ),
                },
                {"role": "user", "content": args.task},
            ],
        )
        proposal, normalization = parse_proposal(proposal_text)
        connector_post(
            args.connector_url,
            "/agent/event",
            {
                "session_id": session_id,
                "phase": "LLM_PROPOSAL",
                "details": {
                    "raw_model_output": proposal_text[:500],
                    "bounded_proposal": proposal,
                    "normalization": normalization,
                },
            },
        )

        authorization = connector_post(
            args.connector_url,
            "/agent/authorize",
            {
                "session_id": session_id,
                "tool_name": "AgentDatabase",
                "tool_use_id": "agent-action-1",
                "tool_input": {
                    "operation": proposal["operation"],
                    "resource": "dev-customer-db",
                    "key": proposal["key"],
                },
            },
        )
        if authorization.get("decision") != "ALLOW":
            raise RuntimeError(f"BAP denied the proposed action: {authorization.get('reason', 'no reason')}")

        result = connector_post(
            args.connector_url,
            "/db/execute",
            {
                "session_id": session_id,
                "operation": proposal["operation"],
                "key": proposal["key"],
            },
        )
        connector_post(
            args.connector_url,
            "/agent/action/result",
            {
                "session_id": session_id,
                "tool_name": "AgentDatabase",
                "tool_use_id": "agent-action-1",
                "result": {"ok": result.get("ok"), "key": proposal["key"]},
            },
        )

        try:
            summary = local_chat(
                args.llm_url,
                model,
                [
                    {
                        "role": "system",
                        "content": "Summarize this read-only database result in one sentence. Do not invent facts.",
                    },
                    {"role": "user", "content": json.dumps(result, sort_keys=True)},
                ],
            )
        except Exception as exc:
            summary = f"Read {proposal['key']} successfully through BAP (summary LLM failed: {exc})."
        connector_post(
            args.connector_url,
            "/agent/event",
            {
                "session_id": session_id,
                "phase": "FINAL_RESPONSE",
                "details": {"summary": summary[:1000]},
            },
        )

        print(json.dumps({"session": session, "proposal": proposal, "result": result, "summary": summary}, indent=2))
        return 0
    except Exception as exc:
        if registered:
            try:
                connector_post(
                    args.connector_url,
                    "/agent/event",
                    {"session_id": session_id, "phase": "AGENT_ERROR", "details": {"error": str(exc)}},
                )
            except Exception:
                pass
        print(f"Python agent failed: {exc}", file=sys.stderr)
        return 1
    finally:
        if registered:
            try:
                connector_post(args.connector_url, "/session/end", {"session_id": session_id})
            except Exception:
                pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only local-LLM agent controlled by the laptop BAP connector")
    parser.add_argument(
        "task",
        nargs="?",
        default="Read customer-123 and tell me the customer's current status.",
    )
    parser.add_argument("--connector-url", default=os.environ.get("BAP_CONNECTOR_URL", DEFAULT_CONNECTOR_URL))
    parser.add_argument("--llm-url", default=os.environ.get("LOCAL_LLM_URL", DEFAULT_LLM_URL))
    parser.add_argument(
        "--model",
        default=os.environ.get("LOCAL_LLM_MODEL", "auto"),
        help="Model ID, or 'auto' to use the first model returned by /v1/models",
    )
    return run_agent(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
