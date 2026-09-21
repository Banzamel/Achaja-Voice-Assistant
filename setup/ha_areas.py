"""Obszary w Home Assistant (WebSocket API): odczyt stanu i przypisywanie urzadzen/encji do pokoi.

Uzycie:
  ha_areas.py dump               zapisuje obszary, urzadzenia i encje do state/ha_registry.json
  ha_areas.py apply plan.json    przypisuje wg planu: [{"kind": "device"|"entity", "id": ..., "area_id": ...}]
                                 (area_id nieistniejacego obszaru -> obszar zostanie utworzony z nazwa "area_name")
"""
import asyncio
import json
import sys
from pathlib import Path

import aiohttp

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "state"


def ws_url():
    """Adres WebSocket HA z config.json (home_assistant.url)."""
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    url = cfg.get("home_assistant", {}).get("url")
    if not url:
        sys.exit("Brak home_assistant.url w config.json")
    return url.replace("https://", "wss://").replace("http://", "ws://").rstrip("/") + "/api/websocket"


class HA:
    def __init__(self, ws):
        self.ws, self.n = ws, 0

    async def call(self, msg_type, **data):
        self.n += 1
        await self.ws.send_json({"id": self.n, "type": msg_type, **data})
        while True:
            msg = await self.ws.receive_json()
            if msg.get("id") == self.n:
                if not msg.get("success", True):
                    raise RuntimeError(f"{msg_type}: {msg.get('error')}")
                return msg.get("result")


async def connect(session):
    ws = await session.ws_connect(ws_url())
    await ws.receive_json()  # auth_required
    token = (STATE / "ha_token.txt").read_text(encoding="utf-8").strip()
    await ws.send_json({"type": "auth", "access_token": token})
    if (await ws.receive_json()).get("type") != "auth_ok":
        raise RuntimeError("Autoryzacja HA nieudana")
    return HA(ws)


async def dump():
    async with aiohttp.ClientSession() as s:
        ha = await connect(s)
        areas = await ha.call("config/area_registry/list")
        devices = await ha.call("config/device_registry/list")
        entities = await ha.call("config/entity_registry/list")
        states = {st["entity_id"]: st for st in await ha.call("get_states")}
    area_name = {a["area_id"]: a["name"] for a in areas}
    dev_by_id = {d["id"]: d for d in devices}
    rows = []
    for e in entities:
        if e.get("disabled_by") or e.get("hidden_by") or e.get("entity_category"):
            continue
        dev = dev_by_id.get(e.get("device_id")) or {}
        area = e.get("area_id") or dev.get("area_id")
        st = states.get(e["entity_id"], {})
        rows.append({
            "entity_id": e["entity_id"],
            "name": st.get("attributes", {}).get("friendly_name") or e.get("name") or e.get("original_name"),
            "device_id": e.get("device_id"),
            "device": (dev.get("name_by_user") or dev.get("name")) if dev else None,
            "area": area_name.get(area),
            "area_from": "entity" if e.get("area_id") else ("device" if dev.get("area_id") else None),
        })
    out = {"areas": [{"area_id": a["area_id"], "name": a["name"]} for a in areas], "entities": rows}
    (STATE / "ha_registry.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


async def apply(plan):
    async with aiohttp.ClientSession() as s:
        ha = await connect(s)
        existing = {a["area_id"] for a in await ha.call("config/area_registry/list")}
        for step in plan:
            area_id = step["area_id"]
            if area_id not in existing:
                created = await ha.call("config/area_registry/create", name=step["area_name"])
                existing.add(created["area_id"])
                area_id = step["area_id"] = created["area_id"]
                print(f"Utworzono obszar {step['area_name']} ({area_id})")
            if step["kind"] == "device":
                await ha.call("config/device_registry/update", device_id=step["id"], area_id=area_id)
            else:
                await ha.call("config/entity_registry/update", entity_id=step["id"], area_id=area_id)
            print(f"{step['kind']} {step.get('label', step['id'])} -> {area_id}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if sys.argv[1] == "dump":
        data = asyncio.run(dump())
        print(f"obszary: {len(data['areas'])}, encje: {len(data['entities'])}")
    elif sys.argv[1] == "apply":
        asyncio.run(apply(json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))))
