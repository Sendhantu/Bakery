#!/usr/bin/env python3
"""Minimal MCP stdio bridge for SweetCrumbs read-only context tools.

Run with:
    .venv/bin/python scripts/mcp_bakery_server.py

The server intentionally exposes curated summaries only. It does not provide
raw SQL access, arbitrary file reads, or write-capable admin actions.
"""

import json
import os
import sys
from contextlib import contextmanager


PROTOCOL_VERSION = os.environ.get("MCP_PROTOCOL_VERSION", "2025-06-18")
SERVER_INFO = {"name": "sweetcrumbs-bakery", "version": "0.1.0"}


TOOLS = [
    {
        "name": "customer.profile_summary",
        "description": "Read a safe summary for one customer profile.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "user_id": {"type": "integer", "description": "Customer user id."}
            },
            "required": ["user_id"],
        },
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "openWorldHint": False,
        },
    },
    {
        "name": "customer.recent_logins",
        "description": "Read recent login status timestamps for one customer.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "user_id": {"type": "integer", "description": "Customer user id."}
            },
            "required": ["user_id"],
        },
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "openWorldHint": False,
        },
    },
    {
        "name": "customer.recent_activity",
        "description": "Read recent product/search activity for one customer.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "user_id": {"type": "integer", "description": "Customer user id."}
            },
            "required": ["user_id"],
        },
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "openWorldHint": False,
        },
    },
    {
        "name": "customer.recent_orders",
        "description": "Read recent order summaries for one customer.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "user_id": {"type": "integer", "description": "Customer user id."}
            },
            "required": ["user_id"],
        },
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "openWorldHint": False,
        },
    },
    {
        "name": "catalog.search_products",
        "description": "Search active products with customer-aware recommendations.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query_text": {"type": "string", "description": "Natural search text."},
                "user_id": {"type": "integer", "description": "Optional customer user id."},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20},
            },
        },
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "openWorldHint": False,
        },
    },
    {
        "name": "catalog.checkout_addons",
        "description": "List optional party add-ons that can be suggested at checkout.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "minimum": 1, "maximum": 20}
            },
        },
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "openWorldHint": False,
        },
    },
]


@contextmanager
def bakery_app_context():
    from app import create_app
    from bootstrap import get_container

    config_name = os.environ.get("MCP_FLASK_CONFIG", "development")
    app = create_app(config_name, portal_role="customer")
    with app.app_context():
        yield get_container()


def dumps(payload):
    return json.dumps(payload, ensure_ascii=True, default=str, separators=(",", ":"))


def make_response(message_id, *, result=None, error=None):
    response = {"jsonrpc": "2.0", "id": message_id}
    if error is not None:
        response["error"] = error
    else:
        response["result"] = result or {}
    return response


def error_response(message_id, code, message):
    return make_response(message_id, error={"code": code, "message": message})


def tool_result(payload, *, is_error=False):
    return {
        "content": [{"type": "text", "text": json.dumps(payload, indent=2, default=str)}],
        "structuredContent": payload if isinstance(payload, dict) else {"result": payload},
        "isError": is_error,
    }


def list_tools():
    return {"tools": TOOLS}


def call_tool(name, arguments):
    arguments = arguments or {}
    valid_tools = {tool["name"] for tool in TOOLS}
    if name not in valid_tools:
        return tool_result({"error": f"Unknown tool: {name}"}, is_error=True)
    user_id = arguments.get("user_id")
    if name.startswith("customer.") and not arguments.get("user_id"):
        return tool_result({"error": "user_id is required"}, is_error=True)

    with bakery_app_context() as container:
        context = container.mcp_context_service
        if name == "catalog.search_products":
            products, message = context.search_products(
                arguments.get("query_text") or "",
                user_id=arguments.get("user_id"),
                limit=min(int(arguments.get("limit") or 8), 20),
            )
            return tool_result(
                {
                    "message": message,
                    "products": [context.compact_product(product) for product in products],
                }
            )

        if name == "catalog.checkout_addons":
            products = context.get_checkout_addons(
                limit=min(int(arguments.get("limit") or 6), 20)
            )
            return tool_result(
                {"checkout_addons": [context.compact_product(product) for product in products]}
            )

        if name.startswith("customer."):
            payload = context.safe_build_customer_context(user_id=user_id, limit=8)
            key_by_tool = {
                "customer.profile_summary": "customer",
                "customer.recent_logins": "recent_logins",
                "customer.recent_activity": "recent_activity",
                "customer.recent_orders": "recent_orders",
            }
            key = key_by_tool.get(name)
            if key:
                return tool_result({key: payload.get(key)})

    return tool_result({"error": f"Unknown tool: {name}"}, is_error=True)


def handle_request(message):
    message_id = message.get("id")
    method = message.get("method")
    params = message.get("params") or {}

    if method == "initialize":
        return make_response(
            message_id,
            result={
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": SERVER_INFO,
                "instructions": (
                    "Use read-only bakery context tools for customer support, "
                    "product search, recommendations, and checkout add-ons."
                ),
            },
        )
    if method == "tools/list":
        return make_response(message_id, result=list_tools())
    if method == "tools/call":
        name = params.get("name")
        if not name:
            return error_response(message_id, -32602, "Missing tool name")
        return make_response(
            message_id,
            result=call_tool(name, params.get("arguments") or {}),
        )
    if method in {"notifications/initialized", "notifications/cancelled"}:
        return None
    if method == "ping":
        return make_response(message_id, result={})
    return error_response(message_id, -32601, f"Method not found: {method}")


def handle_line(line):
    try:
        message = json.loads(line)
    except json.JSONDecodeError as exc:
        return error_response(None, -32700, f"Parse error: {exc}")

    if isinstance(message, list):
        responses = [
            response
            for item in message
            if isinstance(item, dict)
            for response in [handle_request(item)]
            if response is not None
        ]
        return responses or None
    if not isinstance(message, dict):
        return error_response(None, -32600, "Invalid JSON-RPC message")
    return handle_request(message)


def main():
    for raw_line in sys.stdin:
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        response = handle_line(raw_line)
        if response is None:
            continue
        sys.stdout.write(dumps(response) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
