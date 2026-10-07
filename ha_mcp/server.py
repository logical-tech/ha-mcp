# /// script
# requires-python = ">=3.11"
# dependencies = ["mcp>=2", "httpx", "websockets"]
# ///
"""Home Assistant MCP server: REST + WebSocket passthrough, so anything the HA UI can do, the agent can do."""
import functools
import json
import os
import sys

import httpx
import websockets
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

if os.environ.get("SUPERVISOR_TOKEN"):  # running as an HA app: Supervisor proxies Core, no user token needed
    URL, WS_URL, TOKEN = "http://supervisor/core", "ws://supervisor/core/websocket", os.environ["SUPERVISOR_TOKEN"]
else:  # running on a laptop
    URL = os.environ["HA_URL"].rstrip("/")  # e.g. https://ha.example.com
    TOKEN = os.environ["HA_TOKEN"]  # long-lived access token (Profile > Security)
    WS_URL = "ws" + URL[4:] + "/api/websocket"  # http->ws, https->wss
HEADERS = {"Authorization": f"Bearer {TOKEN}"}

mcp = MCPServer("home-assistant")


def tool(fn):
    """Register fn as a tool; surface real error text to the agent (the SDK hides non-ToolError messages)."""
    @functools.wraps(fn)
    async def wrapper(*a, **kw):
        try:
            return await fn(*a, **kw)
        except ToolError:
            raise
        except Exception as e:
            raise ToolError(f"{type(e).__name__}: {e}") from e
    return mcp.tool()(wrapper)


@tool
async def ha_states(domain: str = "", search: str = "") -> str:
    """Compact list of entities: entity_id | state | friendly_name.
    Filter by domain (e.g. "light") and/or case-insensitive substring of entity_id/name.
    Use ha_rest GET /api/states/<entity_id> for full attributes."""
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.get(f"{URL}/api/states", headers=HEADERS)
        r.raise_for_status()
    rows = []
    for s in r.json():
        name = s["attributes"].get("friendly_name", "")
        if domain and not s["entity_id"].startswith(domain + "."):
            continue
        if search and search.lower() not in f"{s['entity_id']} {name}".lower():
            continue
        rows.append(f"{s['entity_id']} | {s['state']} | {name}")
    return "\n".join(rows) or "no match"


@tool
async def ha_rest(method: str, path: str, body: dict | list | None = None) -> str:
    """Call the Home Assistant REST API. Returns "<status>\\n<body>".
    Useful paths:
      GET  /api/config, /api/services, /api/states/<entity_id>, /api/error_log
      GET  /api/history/period/<iso>?filter_entity_id=x, /api/logbook/<iso>
      POST /api/services/<domain>/<service>  body: {"entity_id": "...", ...}
      POST /api/template  body: {"template": "{{ states('sun.sun') }}"}
      POST /api/states/<entity_id>  body: {"state": "...", "attributes": {}}
      GET/POST/DELETE /api/config/automation/config/<id>  (automation YAML-as-JSON; reload automation after)
      GET/POST/DELETE /api/config/script/config/<id>, /api/config/scene/config/<id>
      POST /api/config/core/check_config
    Supervisor API (HA app mode only): prefix the path with /supervisor, e.g.
      GET  /supervisor/addons, /supervisor/addons/<slug>/info, /supervisor/store, /supervisor/backups
      POST /supervisor/store/repositories {"repository": "<git url>"}, /supervisor/store/reload
      POST /supervisor/store/addons/<slug>/install, /supervisor/addons/<slug>/uninstall|start|stop|restart|update
      POST /supervisor/addons/<slug>/options {"auto_update": true}, /supervisor/backups/new/partial {"name", "addons": [...]}"""
    if path.startswith("/supervisor/"):
        if not os.environ.get("SUPERVISOR_TOKEN"):
            raise ToolError("Supervisor API is only reachable when running as an HA app")
        url = "http://supervisor" + path.removeprefix("/supervisor")
    else:
        url = URL + path
    async with httpx.AsyncClient(timeout=300) as c:  # installs/backups can be slow
        r = await c.request(method.upper(), url, headers=HEADERS, json=body)
    return f"{r.status_code}\n{r.text}"


@tool
async def ha_ws(type: str, payload: dict | None = None) -> str:
    """Send one Home Assistant WebSocket command and return its result (JSON).
    `type` is the command, `payload` its extra fields. Covers everything REST doesn't, e.g.:
      config/entity_registry/list | get | update {entity_id, name, area_id, disabled_by, new_entity_id...}
      config/device_registry/list | update {device_id, area_id, name_by_user}
      config/area_registry/list | create {name} | update | delete
      config/floor_registry/list, config/label_registry/list | create
      config_entries/get, config_entries/flow/... , config_entries/disable
      lovelace/dashboards/list, lovelace/config {url_path}, lovelace/config/save {url_path, config}
      search/related {item_type, item_id}, get_services, get_config, system_health/info
      homeassistant/expose_entity {assistants, entity_ids, should_expose}
      supervisor/api {endpoint: "/addons", method: "get"}  (HA OS / Supervised only)"""
    # ponytail: one connection per call; keep a persistent one if latency ever matters
    async with websockets.connect(WS_URL, max_size=None) as ws:
        await ws.recv()  # auth_required
        await ws.send(json.dumps({"type": "auth", "access_token": TOKEN}))
        auth = json.loads(await ws.recv())
        if auth["type"] != "auth_ok":
            raise ToolError(f"auth failed: {auth}")
        await ws.send(json.dumps({"id": 1, "type": type, **(payload or {})}))
        while True:
            msg = json.loads(await ws.recv())
            if msg.get("id") == 1 and msg["type"] == "result":
                if not msg["success"]:
                    raise ToolError(json.dumps(msg["error"]))
                return json.dumps(msg.get("result"), ensure_ascii=False)


if __name__ == "__main__":
    opts_file = "/data/options.json"  # HA app options
    opts = json.load(open(opts_file)) if os.path.exists(opts_file) else {}
    secret = opts.get("secret") or os.environ.get("MCP_SECRET")
    if not secret:
        mcp.run()  # stdio, for local MCP clients
        sys.exit()
    if len(secret) < 32:
        sys.exit("secret must be at least 32 chars: anyone with the URL controls your home")
    # ponytail: auth = unguessable URL path (what claude.ai custom connectors can do without OAuth).
    # Upgrade to OAuth if the URL ever needs to be shared or rotated per client.
    mcp.run("streamable-http", host="0.0.0.0", port=int(os.environ.get("PORT", 8099)),
            streamable_http_path=f"/{secret}", stateless_http=True)
