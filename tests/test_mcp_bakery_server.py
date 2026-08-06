from scripts import mcp_bakery_server


def test_mcp_initialize_response_advertises_tools():
    response = mcp_bakery_server.handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize"}
    )

    assert response["id"] == 1
    assert response["result"]["capabilities"]["tools"]["listChanged"] is False
    assert response["result"]["serverInfo"]["name"] == "sweetcrumbs-bakery"


def test_mcp_tools_list_exposes_read_only_context_tools():
    response = mcp_bakery_server.handle_request(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
    )

    tools = response["result"]["tools"]
    names = {tool["name"] for tool in tools}
    assert "catalog.search_products" in names
    assert "catalog.checkout_addons" in names
    assert "customer.recent_orders" in names
    assert all(tool["annotations"]["readOnlyHint"] is True for tool in tools)


def test_mcp_unknown_tool_returns_tool_error(monkeypatch):
    def fail_if_app_context_is_built():
        raise AssertionError("unknown tools should not boot the Flask app")

    monkeypatch.setattr(
        mcp_bakery_server,
        "bakery_app_context",
        fail_if_app_context_is_built,
    )

    response = mcp_bakery_server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "admin.delete_everything", "arguments": {}},
        }
    )

    assert response["result"]["isError"] is True
    assert "Unknown tool" in response["result"]["structuredContent"]["error"]
