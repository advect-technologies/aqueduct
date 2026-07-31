"""Lightweight local web UI served by aiohttp.

Plain HTML + vanilla JS. No build step, no framework.
All control actions go through controller.submit(Event).
Status is polled via GET /api/status.
"""

from __future__ import annotations

from aiohttp import web
from loguru import logger as log

from . import models
from .controller import IrrigationController

# ---------------------------------------------------------------------------
# HTML page
# ---------------------------------------------------------------------------

INDEX_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Irrigation Controller</title>
  <style>
    :root {
      --bg: #0f1419;
      --card: #1a2332;
      --border: #2d3a4f;
      --text: #e7ecf3;
      --muted: #8b9bb4;
      --green: #22c55e;
      --red: #ef4444;
      --yellow: #eab308;
      --fault: #f97316;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
      background: var(--bg);
      color: var(--text);
      min-height: 100vh;
      padding: 1.5rem;
    }
    header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 1.5rem;
      flex-wrap: wrap;
      gap: 0.75rem;
    }
    h1 { font-size: 1.4rem; font-weight: 600; }
    .status-bar {
      display: flex;
      gap: 1.25rem;
      align-items: center;
      font-size: 0.85rem;
      color: var(--muted);
    }
    .dot {
      width: 10px; height: 10px; border-radius: 50%;
      display: inline-block; margin-right: 0.35rem;
    }
    .dot.on    { background: var(--green); box-shadow: 0 0 6px var(--green); }
    .dot.off   { background: var(--muted); }
    .dot.fault { background: var(--fault); box-shadow: 0 0 6px var(--fault); }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
      gap: 1rem;
    }
    .card {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 1.1rem 1.25rem;
      display: flex;
      flex-direction: column;
      gap: 0.6rem;
    }
    .card.open { border-color: var(--green); }
    .card.disabled { opacity: 0.45; }
    .card-header {
      display: flex;
      justify-content: space-between;
      align-items: baseline;
    }
    .name { font-weight: 600; font-size: 1.05rem; }
    .zone { color: var(--muted); font-size: 0.8rem; }
    .meta { font-size: 0.8rem; color: var(--muted); }
    .actions {
      display: flex;
      gap: 0.5rem;
      margin-top: 0.4rem;
    }
    button {
      flex: 1;
      border: none;
      border-radius: 6px;
      padding: 0.55rem 0.8rem;
      font-size: 0.9rem;
      font-weight: 500;
      cursor: pointer;
      transition: opacity 0.15s;
    }
    button:hover { opacity: 0.9; }
    button:disabled { opacity: 0.4; cursor: not-allowed; }
    .btn-open  { background: var(--green); color: #052e16; }
    .btn-close { background: var(--red);   color: #450a0a; }
    .btn-all {
      background: var(--yellow);
      color: #422006;
      padding: 0.6rem 1.2rem;
      font-size: 0.95rem;
    }
    .footer {
      margin-top: 1.5rem;
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 0.75rem;
    }
    .toast {
      position: fixed;
      bottom: 1.25rem;
      right: 1.25rem;
      background: var(--card);
      border: 1px solid var(--border);
      padding: 0.7rem 1.1rem;
      border-radius: 8px;
      font-size: 0.9rem;
      opacity: 0;
      transition: opacity 0.25s;
      pointer-events: none;
      z-index: 50;
    }
    .toast.show { opacity: 1; }
    .state-IDLE   { color: var(--muted); }
    .state-ACTIVE { color: var(--green); }
    .state-FAULT  { color: var(--fault); }
    .state-INIT   { color: var(--muted); }
  </style>
</head>
<body>
  <header>
    <h1>Irrigation Controller</h1>
    <div class="status-bar">
      <span id="state">State: —</span>
      <span id="active">Active: none</span>
      <span id="uptime">Uptime: —</span>
    </div>
  </header>

  <div class="grid" id="valves"></div>

  <div class="footer">
    <button class="btn-all" id="close-all">Close All Valves</button>
    <span class="meta" id="last-update">Last update: —</span>
  </div>

  <div class="toast" id="toast"></div>

  <script>
    const $ = (sel) => document.querySelector(sel);

    function toast(msg) {
      const el = $("#toast");
      el.textContent = msg;
      el.classList.add("show");
      setTimeout(() => el.classList.remove("show"), 2200);
    }

    function fmtUptime(s) {
      const h = Math.floor(s / 3600);
      const m = Math.floor((s % 3600) / 60);
      const sec = Math.floor(s % 60);
      if (h > 0) return `${h}h ${m}m`;
      if (m > 0) return `${m}m ${sec}s`;
      return `${sec}s`;
    }

    async function api(path, method = "GET") {
      const r = await fetch(path, { method });
      return r.json();
    }

    function render(status) {
      const state = status.state;
      const active = status.active_zone_index;

      const stateEl = $("#state");
      stateEl.innerHTML = `State: <span class="state-${state}">${state}</span>` +
        (status.state_age_s != null ? ` (${fmtUptime(status.state_age_s)})` : "");

      if (state === "FAULT") {
        $("#active").innerHTML = '<span class="dot fault"></span>FAULT — all valves closed';
      } else if (active == null) {
        $("#active").innerHTML = '<span class="dot off"></span>Active: none';
      } else {
        $("#active").innerHTML = `<span class="dot on"></span>Active: zone ${active}`;
      }

      $("#uptime").textContent = "Uptime: " + fmtUptime(status.uptime_s);
      $("#last-update").textContent = "Last update: " + new Date().toLocaleTimeString();

      const container = $("#valves");
      container.innerHTML = "";
      for (const v of status.zones) {
        const card = document.createElement("div");
        card.className = "card"
          + (v.is_open ? " open" : "")
          + (v.enabled ? "" : " disabled");
        const canOpen  = v.enabled && !v.is_open && state !== "FAULT";
        const canClose = v.enabled && v.is_open;
        card.innerHTML = `
          <div class="card-header">
            <span class="name">${v.display_name}</span>
            <span class="zone">zone ${v.index}</span>
          </div>
          <div class="meta">
            Relay ${v.relay_num}${v.location ? " · " + v.location : ""}
            · <span class="dot ${v.is_open ? "on" : "off"}"></span>
            ${v.is_open ? "OPEN" : "closed"}
          </div>
          <div class="actions">
            <button class="btn-open"  data-zone="${v.index}" data-action="open"
                    ${canOpen ? "" : "disabled"}>Open</button>
            <button class="btn-close" data-zone="${v.index}" data-action="close"
                    ${canClose ? "" : "disabled"}>Close</button>
          </div>`;
        container.appendChild(card);
      }
    }

    async function refresh() {
      try {
        const status = await api("/api/status");
        render(status);
      } catch (e) {
        console.error(e);
        toast("Status fetch failed");
      }
    }

    document.addEventListener("click", async (e) => {
      const btn = e.target.closest("button");
      if (!btn) return;

      if (btn.id === "close-all") {
        await api("/api/close_all", "POST");
        toast("Close-all requested");
        setTimeout(refresh, 150);
        return;
      }

      const zone = btn.dataset.zone;
      const action = btn.dataset.action;
      if (!zone || !action) return;

      btn.disabled = true;
      const path = action === "open"
        ? `/api/valve/${zone}/open`
        : `/api/valve/${zone}/close`;
      await api(path, "POST");
      toast(`${action} zone ${zone} requested`);
      setTimeout(refresh, 150);
    });

    refresh();
    setInterval(refresh, 2000);
  </script>
</body>
</html>
"""


def create_app(controller: IrrigationController) -> web.Application:
    app = web.Application()

    async def index(_request: web.Request) -> web.Response:
        return web.Response(text=INDEX_HTML, content_type="text/html")

    async def status(_request: web.Request) -> web.Response:
        s = controller.get_status()
        payload = {
            "state": s.state.value,
            "state_age_s": s.state_age_s,
            "active_zone_index": s.active_zone_index,
            "uptime_s": s.uptime_s,
            "zones": [
                {
                    "index": z.index,
                    "display_name": z.display_name,
                    "relay_num": z.relay_num,
                    "enabled": z.enabled,
                    "location": z.location,
                    "is_open": z.is_open,
                }
                for z in s.zones
            ],
        }
        return web.json_response(payload)

    async def open_valve(request: web.Request) -> web.Response:
        zone = int(request.match_info["zone"])
        controller.submit(models.OpenValveEvent(zone_index=zone))
        return web.json_response({"ok": True, "action": "open", "zone": zone})

    async def close_valve(request: web.Request) -> web.Response:
        # CloseValveEvent is zone-less — closes whatever is currently open
        controller.submit(models.CloseValveEvent())
        return web.json_response({"ok": True, "action": "close"})

    async def close_all(_request: web.Request) -> web.Response:
        controller.submit(models.CloseValveEvent())
        return web.json_response({"ok": True, "action": "close_all"})

    app.router.add_get("/", index)
    app.router.add_get("/api/status", status)
    app.router.add_post("/api/valve/{zone}/open", open_valve)
    app.router.add_post("/api/valve/{zone}/close", close_valve)
    app.router.add_post("/api/close_all", close_all)

    return app


async def start_web(
    controller: IrrigationController, host: str, port: int
) -> web.AppRunner:
    app = create_app(controller)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    log.info(f"Web UI listening on http://{host}:{port}")
    return runner
