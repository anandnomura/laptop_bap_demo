from __future__ import annotations

import json
import os
import re
import secrets
from typing import Any

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse


app = FastAPI(title="Claude Code to local OpenAI bridge")
LOCAL_LLM_BASE = os.environ.get("LOCAL_LLM_BASE", "http://127.0.0.1:8080/v1").rstrip("/")
LOCAL_LLM_MODEL = os.environ.get("LOCAL_LLM_MODEL", "")
LOCAL_MAX_OUTPUT_TOKENS = int(os.environ.get("LOCAL_MAX_OUTPUT_TOKENS", "1024"))
LOCAL_MAX_SYSTEM_CHARS = int(os.environ.get("LOCAL_MAX_SYSTEM_CHARS", "12000"))


def text_from_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content or "")
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            parts.append(str(block.get("text", "")))
        elif block.get("type") == "tool_result":
            parts.append(text_from_content(block.get("content", "")))
    return "\n".join(part for part in parts if part)


def compact_system_prompt(system: str) -> str:
    if len(system) <= LOCAL_MAX_SYSTEM_CHARS:
        return system
    half = LOCAL_MAX_SYSTEM_CHARS // 2
    return (
        system[:half]
        + "\n\n[Claude Code system prompt compacted by the local bridge for the 8K model context.]\n\n"
        + system[-half:]
    )


def convert_messages(data: dict[str, Any]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    system = compact_system_prompt(text_from_content(data.get("system", "")))
    if system:
        messages.append({"role": "system", "content": system})

    for source in data.get("messages", []):
        role = str(source.get("role", "user"))
        content = source.get("content", "")
        if not isinstance(content, list):
            messages.append({"role": role, "content": str(content)})
            continue

        if role == "assistant":
            text_parts: list[str] = []
            tool_calls: list[dict[str, Any]] = []
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text":
                    text_parts.append(str(block.get("text", "")))
                elif block.get("type") == "tool_use":
                    tool_calls.append(
                        {
                            "id": str(block.get("id", "call_" + secrets.token_hex(8))),
                            "type": "function",
                            "function": {
                                "name": str(block.get("name", "")),
                                "arguments": json.dumps(block.get("input") or {}),
                            },
                        }
                    )
            converted: dict[str, Any] = {
                "role": "assistant",
                "content": "\n".join(text_parts) if text_parts else "",
            }
            if tool_calls:
                converted["tool_calls"] = tool_calls
            messages.append(converted)
            continue

        user_text: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type")
            if block_type == "tool_result":
                if user_text:
                    messages.append({"role": "user", "content": "\n".join(user_text)})
                    user_text.clear()
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": str(block.get("tool_use_id", "")),
                        "content": text_from_content(block.get("content", "")),
                    }
                )
            elif block_type == "text":
                user_text.append(str(block.get("text", "")))
        if user_text:
            messages.append({"role": "user", "content": "\n".join(user_text)})
    return messages


def convert_tools(data: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for tool in data.get("tools", []):
        if not isinstance(tool, dict) or not tool.get("name"):
            continue
        name = str(tool["name"])
        description = str(tool.get("description", ""))
        if name == "Bash":
            description = (
                "Execute a shell command in the current Windows project directory. "
                "When the user supplies an exact command, preserve it character-for-character."
            )
        else:
            description = description[:1200]
        result.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": tool.get("input_schema") or {"type": "object", "properties": {}},
                },
            }
        )
    return result


def convert_tool_choice(value: Any) -> Any:
    if not isinstance(value, dict):
        return "auto"
    choice_type = value.get("type", "auto")
    if choice_type == "any":
        return "required"
    if choice_type == "tool" and value.get("name"):
        return {"type": "function", "function": {"name": str(value["name"])}}
    return "auto"


def explicitly_requested_single_tool(messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> Any | None:
    if len(tools) != 1 or not messages or messages[-1].get("role") != "user":
        return None
    name = str(tools[0]["function"]["name"])
    prompt = str(messages[-1].get("content", ""))
    pattern = rf"\b(?:call|use|run)(?:\s+the)?\s+{re.escape(name)}\b"
    if re.search(pattern, prompt, flags=re.IGNORECASE):
        return {"type": "function", "function": {"name": name}}
    return None


def normalize_tool_input(raw_arguments: Any, tool_name: str) -> dict[str, Any]:
    value = raw_arguments
    for _ in range(3):
        if isinstance(value, dict):
            return value
        if not isinstance(value, str):
            break
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return {"command": value} if tool_name == "Bash" else {"value": value}
        if decoded == value:
            break
        value = decoded
    if isinstance(value, dict):
        return value
    if tool_name == "Bash" and isinstance(value, str):
        return {"command": value}
    return {}


async def model_id(client: httpx.AsyncClient) -> str:
    if LOCAL_LLM_MODEL:
        return LOCAL_LLM_MODEL
    response = await client.get(f"{LOCAL_LLM_BASE}/models")
    response.raise_for_status()
    models = response.json().get("data") or []
    if not models:
        raise RuntimeError("Local LLM /v1/models returned no models")
    return str(models[0]["id"])


def anthropic_response(data: dict[str, Any], openai_data: dict[str, Any]) -> dict[str, Any]:
    choice = openai_data["choices"][0]
    message = choice.get("message") or {}
    blocks: list[dict[str, Any]] = []
    content = str(message.get("content") or "")
    tool_calls = list(message.get("tool_calls") or [])
    if not tool_calls and content:
        for match in re.finditer(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", content, flags=re.DOTALL):
            try:
                parsed = json.loads(match.group(1))
            except json.JSONDecodeError:
                continue
            name = parsed.get("name")
            arguments = parsed.get("arguments", parsed.get("input", {}))
            if name:
                tool_calls.append(
                    {
                        "id": "call_" + secrets.token_hex(12),
                        "type": "function",
                        "function": {"name": str(name), "arguments": json.dumps(arguments)},
                    }
                )
        content = re.sub(r"<tool_call>.*?</tool_call>", "", content, flags=re.DOTALL).strip()
    if content:
        blocks.append({"type": "text", "text": content})
    for call in tool_calls:
        function = call.get("function") or {}
        raw_arguments = function.get("arguments") or "{}"
        tool_name = str(function.get("name", ""))
        arguments = normalize_tool_input(raw_arguments, tool_name)
        blocks.append(
            {
                "type": "tool_use",
                "id": str(call.get("id") or "toolu_" + secrets.token_hex(12)),
                "name": tool_name,
                "input": arguments,
            }
        )
    if not blocks:
        blocks.append({"type": "text", "text": ""})

    finish_reason = choice.get("finish_reason")
    stop_reason = "tool_use" if tool_calls else "max_tokens" if finish_reason == "length" else "end_turn"
    usage = openai_data.get("usage") or {}
    return {
        "id": "msg_local_" + secrets.token_hex(12),
        "type": "message",
        "role": "assistant",
        "model": data.get("model", "local-model"),
        "content": blocks,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {
            "input_tokens": int(usage.get("prompt_tokens", 0)),
            "output_tokens": int(usage.get("completion_tokens", 0)),
        },
    }


def streaming_events(message: dict[str, Any]):
    start_message = {
        **message,
        "content": [],
        "stop_reason": None,
        "stop_sequence": None,
        "usage": {"input_tokens": message["usage"]["input_tokens"], "output_tokens": 0},
    }
    events: list[dict[str, Any]] = [{"type": "message_start", "message": start_message}]
    for index, block in enumerate(message["content"]):
        if block["type"] == "tool_use":
            start_block = {**block, "input": {}}
            delta = {"type": "input_json_delta", "partial_json": json.dumps(block.get("input") or {})}
        else:
            start_block = {"type": "text", "text": ""}
            delta = {"type": "text_delta", "text": str(block.get("text", ""))}
        events.append({"type": "content_block_start", "index": index, "content_block": start_block})
        events.append({"type": "content_block_delta", "index": index, "delta": delta})
        events.append({"type": "content_block_stop", "index": index})
    events.append(
        {
            "type": "message_delta",
            "delta": {"stop_reason": message["stop_reason"], "stop_sequence": None},
            "usage": {"output_tokens": message["usage"]["output_tokens"]},
        }
    )
    events.append({"type": "message_stop"})
    for event in events:
        event_name = event["type"]
        yield f"event: {event_name}\ndata: {json.dumps(event, separators=(',', ':'))}\n\n"


@app.api_route("/api/hello", methods=["GET", "HEAD"])
async def hello_probe() -> Response:
    return Response(status_code=200)


@app.get("/health")
async def health() -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        selected_model = await model_id(client)
    return {"ok": True, "local_llm": LOCAL_LLM_BASE, "model": selected_model}


@app.post("/v1/messages/count_tokens")
async def count_tokens(request: Request) -> dict[str, int]:
    data = await request.json()
    serialized = json.dumps(data.get("system", "")) + json.dumps(data.get("messages", []))
    return {"input_tokens": max(1, len(serialized) // 4)}


@app.post("/v1/messages")
async def messages_proxy(request: Request):
    data = await request.json()
    async with httpx.AsyncClient(timeout=180.0) as client:
        try:
            payload: dict[str, Any] = {
                "model": await model_id(client),
                "messages": convert_messages(data),
                "temperature": data.get("temperature", 0.2),
                "max_tokens": min(int(data.get("max_tokens", LOCAL_MAX_OUTPUT_TOKENS)), LOCAL_MAX_OUTPUT_TOKENS),
                "stream": False,
            }
            tools = convert_tools(data)
            if tools:
                payload["tools"] = tools
                payload["tool_choice"] = explicitly_requested_single_tool(payload["messages"], tools) or convert_tool_choice(
                    data.get("tool_choice")
                )
            response = await client.post(f"{LOCAL_LLM_BASE}/chat/completions", json=payload)
            if response.status_code != 200:
                return JSONResponse(
                    status_code=502,
                    content={
                        "type": "error",
                        "error": {
                            "type": "api_error",
                            "message": f"Local LLM returned HTTP {response.status_code}: {response.text[:1000]}",
                        },
                    },
                )
            converted = anthropic_response(data, response.json())
            if data.get("stream"):
                return StreamingResponse(streaming_events(converted), media_type="text/event-stream")
            return JSONResponse(content=converted)
        except Exception as exc:
            return JSONResponse(
                status_code=502,
                content={"type": "error", "error": {"type": "api_error", "message": str(exc)}},
            )
