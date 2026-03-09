"""MCP Gateway — REST API bridge to the dev-events MCP server."""

import json
import os
from datetime import date

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from mcp.client.session import ClientSession
from mcp.client.sse import sse_client
from openai import OpenAI
from pydantic import BaseModel

MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://mcp-server:8000/sse")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://model-runner.docker.internal/engines/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "ai/qwen3")

app = FastAPI(title="dev-events gateway")


async def _call_tool(name: str, arguments: dict) -> str:
    async with sse_client(MCP_SERVER_URL) as streams:
        async with ClientSession(*streams) as session:
            await session.initialize()
            result = await session.call_tool(name, arguments)
            return "\n".join(
                block.text for block in result.content if hasattr(block, "text")
            )


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_events",
            "description": "Fetch upcoming tech conferences from dev.events.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "Filter by topic (ai, devops, kubernetes, python, java, cloud, security, golang, rust, etc.).",
                    },
                    "region": {
                        "type": "string",
                        "description": "Continent code: EU, NA, AS, AF, SA, OC, ON (online).",
                    },
                    "country": {
                        "type": "string",
                        "description": "Two-letter country code (DE, US, GB, PL, FR, etc.).",
                    },
                    "city": {
                        "type": "string",
                        "description": "City name (e.g. Berlin, San_Francisco).",
                    },
                    "start_date": {
                        "type": "string",
                        "description": "Start of date range (YYYY-MM-DD).",
                    },
                    "end_date": {
                        "type": "string",
                        "description": "End of date range (YYYY-MM-DD).",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max events to return (default 20).",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_event_details",
            "description": "Get details for a specific conference by its URL slug.",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_slug": {
                        "type": "string",
                        "description": "Event slug from the URL (e.g. 'sql-konferenz-2026').",
                    },
                },
                "required": ["event_slug"],
            },
        },
    },
]

def _system_prompt() -> str:
    today = date.today().isoformat()
    return (
        f"You are a tech conference assistant. Today is {today}. "
        "Use the provided tools to search dev.events for upcoming conferences. "
        "Use dates in YYYY-MM-DD format, only future dates. "
        "Region codes: EU, NA, AS, AF, SA, OC, ON. "
        "Be concise. Format results clearly."
    )


class AskRequest(BaseModel):
    prompt: str


@app.post("/api/ask")
async def api_ask(req: AskRequest):
    client = OpenAI(base_url=LLM_BASE_URL, api_key="not-needed")
    messages = [
        {"role": "system", "content": _system_prompt()},
        {"role": "user", "content": req.prompt},
    ]

    response = client.chat.completions.create(
        model=LLM_MODEL,
        messages=messages,
        tools=TOOLS,
        max_tokens=8192,
        extra_body={"n_ctx": 8192},
    )

    msg = response.choices[0].message
    max_rounds = 5
    rounds = 0

    tool_outputs = []

    while msg.tool_calls and rounds < max_rounds:
        rounds += 1
        messages.append(msg)
        for tc in msg.tool_calls:
            args = json.loads(tc.function.arguments)
            tool_text = await _call_tool(tc.function.name, args)
            if tc.function.name == "get_events":
                tool_outputs.append(tool_text)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": tool_text,
                }
            )
        response = client.chat.completions.create(
            model=LLM_MODEL,
            messages=messages,
            tools=TOOLS,
            max_tokens=1024,
        extra_body={"n_ctx": 8192},
        )
        msg = response.choices[0].message

    return {
        "result": msg.content or "",
        "tool_data": "\n".join(tool_outputs) if tool_outputs else None,
    }


@app.get("/api/events")
async def api_events(
    topic: str = Query(None),
    region: str = Query(None),
    country: str = Query(None),
    city: str = Query(None),
    start_date: str = Query(None),
    end_date: str = Query(None),
    limit: int = Query(20, ge=1, le=100),
):
    args: dict = {"limit": limit}
    for key in ("topic", "region", "country", "city", "start_date", "end_date"):
        val = locals()[key]
        if val:
            args[key] = val
    text = await _call_tool("get_events", args)
    return {"result": text}


@app.get("/api/events/{slug}")
async def api_event_details(slug: str):
    text = await _call_tool("get_event_details", {"event_slug": slug})
    return {"result": text}


app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def root():
    return FileResponse("static/index.html")
