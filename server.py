"""
Neko Overlay Studio - Unified Server (FreeMode + MultiPK)
Chạy: pip install -r requirements.txt && python server.py
OBS Browser Sources:
- http://YOUR_SERVER:8000/overlay/popup  (FreeMode Popup)
- http://YOUR_SERVER:8000/overlay/pk     (MultiPK Battle Bar)
- http://YOUR_SERVER:8000/overlay/rank   (Bảng Xếp Hạng Rank)
- http://YOUR_SERVER:8000/overlay        (Overlay Đơn Giản)
Control panel:
- http://YOUR_SERVER:8000/control
"""

import asyncio
import json
import logging
import re
import uuid
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import requests
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import FileResponse, Response, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from TikTokLive import TikTokLiveClient
from TikTokLive.events import ConnectEvent, DisconnectEvent, GiftEvent

# Suppress TikTokLive error parse logs
logging.getLogger("TikTokLive").setLevel(logging.CRITICAL)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("neko-ovl-unified")

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="Neko Overlay Studio")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

GIFT_GRACE_SECONDS = 3

state = {
    "mode": "freemode",        # "freemode" | "multipk"
    "room": None,
    "connected": False,
    "last_error": None,
    "idols": [],
    "timer": {
        "duration": 180,
        "remaining": 180,
        "running": False,
        "finished": False,
        "finishing": False,
        "grace_remaining": 0,
        "grace_config": 3,
    },
    "gift_mode": "auto",        # "auto" | "manual"
    "accepting_gifts": False,
    "target": {
        "enabled": False,
        "score": 1000,
        "reached": False,
    },
    "pk": {
        "enabled": False,
        "num_positions": 3,
        "round": 1,
        "status": "standby",   # standby | running | paused | finished
        "positions": [],
        "assignments": {},
        "fog_enabled": False,
        "fog_duration": 0,
        "fog_active": False,
        "score_lock_duration": 5,
        "in_score_lock": False,
        "score_lock_remaining": 0,
    },
    "gift_catalog": [],
    "gift_catalog_username": "",
    "gift_catalog_error": None,
    "last_gift_debug": {},
}

sockets: list[WebSocket] = []
current_client: Optional[TikTokLiveClient] = None
current_task: Optional[asyncio.Task] = None
pk_assignments: dict[str, dict] = {}
pk_gift_streaks: dict[tuple[str, str], int] = {}

# --- Gift Database (MCAClone 5,195+ TikTok Gifts + Live Fetcher) ---
ALL_GIFTS: list[dict] = []
ALL_GIFTS_MAP: dict[str, dict] = {}
ALL_GIFTS_NAME_MAP: dict[str, dict] = {}

def load_offline_gifts():
    global ALL_GIFTS, ALL_GIFTS_MAP, ALL_GIFTS_NAME_MAP
    all_gifts_path = STATIC_DIR / "all_gifts.json"
    if all_gifts_path.exists():
        try:
            with open(all_gifts_path, "r", encoding="utf-8") as f:
                raw_list = json.load(f)
                for item in raw_list:
                    gid = str(item.get("gift_id") or item.get("id") or "").strip()
                    if not gid:
                        continue
                    name = str(item.get("gift_name") or item.get("name") or f"Gift #{gid}").strip()
                    diamonds = int(item.get("gift_price") or item.get("diamonds") or 1)
                    img = item.get("gift_icon") or item.get("img") or item.get("image") or ""
                    if not img and item.get("gift_icon_hash"):
                        img = f"https://p16-webcast.tiktokcdn.com/img/maliva/webcast-va/{item['gift_icon_hash']}~tplv-obj.png"
                    if not img:
                        img = "https://p19-webcast.tiktokcdn.com/img/maliva/webcast-va/8e1a5d66370c5586545e358e37c10d25~tplv-obj.png"
                    
                    entry = {
                        "id": gid,
                        "name": name,
                        "diamonds": max(1, diamonds),
                        "img": img,
                    }
                    if gid not in ALL_GIFTS_MAP:
                        ALL_GIFTS.append(entry)
                        ALL_GIFTS_MAP[gid] = entry
                        ALL_GIFTS_NAME_MAP[name.lower()] = entry
            logger.info(f"[Gift DB] Loaded {len(ALL_GIFTS)} gifts from all_gifts.json")
        except Exception as e:
            logger.error(f"[Gift DB] Error loading all_gifts.json: {e}")

    # Fallback/merge gifts.json if present
    gifts_path = STATIC_DIR / "gifts.json"
    if gifts_path.exists():
        try:
            with open(gifts_path, "r", encoding="utf-8") as f:
                raw_list = json.load(f)
                for item in raw_list:
                    gid = str(item.get("id") or item.get("gift_id") or "").strip()
                    if not gid or gid in ALL_GIFTS_MAP:
                        continue
                    name = str(item.get("name") or item.get("gift_name") or f"Gift #{gid}").strip()
                    diamonds = int(item.get("diamonds") or item.get("gift_price") or 1)
                    img = str(item.get("img") or item.get("gift_icon") or "").strip()
                    entry = {
                        "id": gid,
                        "name": name,
                        "diamonds": max(1, diamonds),
                        "img": img or "https://p19-webcast.tiktokcdn.com/img/maliva/webcast-va/8e1a5d66370c5586545e358e37c10d25~tplv-obj.png",
                    }
                    ALL_GIFTS.append(entry)
                    ALL_GIFTS_MAP[gid] = entry
                    ALL_GIFTS_NAME_MAP[name.lower()] = entry
        except Exception as e:
            logger.error(f"[Gift DB] Error loading gifts.json: {e}")

load_offline_gifts()

def register_online_gift(gift_id: Any, gift_name: str, diamond_count: int = 1, gift_icon: str = "") -> dict:
    if not gift_id and not gift_name:
        return {}
    gid = str(gift_id or "").strip()
    gname = str(gift_name or "").strip()
    dcount = max(1, int(diamond_count or 1))
    icon = str(gift_icon or "").strip()

    entry = None
    if gid and gid in ALL_GIFTS_MAP:
        entry = ALL_GIFTS_MAP[gid]
    elif gname and gname.lower() in ALL_GIFTS_NAME_MAP:
        entry = ALL_GIFTS_NAME_MAP[gname.lower()]

    if entry:
        if dcount > 1 and entry.get("diamonds", 1) <= 1:
            entry["diamonds"] = dcount
        if icon and ("tiktokcdn.com" in icon or not entry.get("img")):
            entry["img"] = icon
        if gid and not entry.get("id"):
            entry["id"] = gid
            ALL_GIFTS_MAP[gid] = entry
        return entry

    new_entry = {
        "id": gid or str(int(time.time())),
        "name": gname or f"Gift #{gid}",
        "diamonds": dcount,
        "img": icon or "https://p19-webcast.tiktokcdn.com/img/maliva/webcast-va/8e1a5d66370c5586545e358e37c10d25~tplv-obj.png",
    }
    ALL_GIFTS.append(new_entry)
    ALL_GIFTS_MAP[new_entry["id"]] = new_entry
    if gname:
        ALL_GIFTS_NAME_MAP[gname.lower()] = new_entry
    return new_entry

async def fetch_tiktok_online_gifts() -> int:
    import urllib.request
    urls = [
        "https://webcast.tiktok.com/webcast/gift/list/?aid=1988",
        "https://raw.githubusercontent.com/zerodytrash/TikTok-Live-Connector/master/src/lib/tiktokGiftList.json"
    ]
    count_added = 0
    for url in urls:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
            loop = asyncio.get_running_loop()
            def _fetch():
                with urllib.request.urlopen(req, timeout=6) as response:
                    if response.status == 200:
                        return json.loads(response.read().decode('utf-8'))
                    return None
            data = await loop.run_in_executor(None, _fetch)
            if not data:
                continue
            gift_list = []
            if isinstance(data, dict):
                gift_list = data.get("data", {}).get("gifts", []) or data.get("gifts", [])
            elif isinstance(data, list):
                gift_list = data
            for item in gift_list:
                if isinstance(item, dict):
                    gid = item.get("id") or item.get("gift_id")
                    gname = item.get("name") or item.get("gift_name")
                    diamonds = item.get("diamond_count") or item.get("gift_price") or 1
                    img = ""
                    if isinstance(item.get("image"), dict):
                        urls = item.get("image", {}).get("url_list", [])
                        img = urls[0] if urls else ""
                    elif isinstance(item.get("image"), str):
                        img = item.get("image")
                    else:
                        img = item.get("gift_icon") or item.get("img") or ""
                    if gid or gname:
                        register_online_gift(gid, gname, diamonds, img)
                        count_added += 1
            if count_added > 0:
                logger.info(f"[Online Gift Fetcher] Fetched and updated {count_added} online gifts from {url}")
                break
        except Exception as e:
            logger.warning(f"[Online Gift Fetcher] Failed loading from {url}: {e}")
    return count_added

def default_pk_position(index: int) -> dict:
    return {
        "id": uuid.uuid4().hex[:8],
        "idol_id": "",
        "name": f"Player {index + 1}",
        "tiktok_id": "",
        "avatar": "",
        "gift_id": "",
        "gift_name": "",
        "gift_img": "",
        "gift_diamonds": 1,
        "score": 0,
        "win_streak": 0,
    }

def make_pk_positions(n: int) -> list[dict]:
    pos_colors = ["#ff56b0", "#03bef2", "#ffac3e", "#964bfa", "#ff3542"]
    positions = []
    for i in range(n):
        if i < len(state["pk"].get("positions", [])):
            p = state["pk"]["positions"][i]
            p["color"] = pos_colors[i % len(pos_colors)]
            positions.append(p)
        else:
            p = default_pk_position(i)
            p["color"] = pos_colors[i % len(pos_colors)]
            positions.append(p)
    return positions

state["pk"]["positions"] = make_pk_positions(3)

async def broadcast_state():
    if not sockets:
        return
    msg = json.dumps({"type": "state", "data": state}, ensure_ascii=False)
    dead = []
    for ws in sockets:
        try:
            await ws.send_text(msg)
        except Exception:
            dead.append(ws)
    for ws in dead:
        if ws in sockets:
            sockets.remove(ws)

async def broadcast_event(event_type: str, data: dict = None):
    if not sockets:
        return
    msg = json.dumps({"type": event_type, "data": data or {}}, ensure_ascii=False)
    dead = []
    for ws in sockets:
        try:
            await ws.send_text(msg)
        except Exception:
            dead.append(ws)
    for ws in dead:
        if ws in sockets:
            sockets.remove(ws)

def get_idol(idol_id: str) -> Optional[dict]:
    for i in state["idols"]:
        if i["id"] == idol_id:
            return i
    return None

def get_active_idol() -> Optional[dict]:
    for i in state["idols"]:
        if i.get("active"):
            return i
    return None

def sync_pk_from_idols():
    idols_by_id = {i["id"]: i for i in state["idols"]}
    for pos in state["pk"].get("positions", []):
        idol_id = pos.get("idol_id")
        if idol_id and idol_id in idols_by_id:
            idol = idols_by_id[idol_id]
            pos["name"] = idol.get("name") or pos["name"]
            pos["tiktok_id"] = idol.get("tiktok_id") or pos["tiktok_id"]
            pos["avatar"] = idol.get("avatar") or pos["avatar"]

def add_pk_points(position_id: str, points: int):
    for pos in state["pk"].get("positions", []):
        if pos.get("id") == position_id:
            pos["score"] = pos.get("score", 0) + points
            idol_id = pos.get("idol_id")
            if idol_id:
                idol = get_idol(idol_id)
                if idol:
                    idol["score"] = idol.get("score", 0) + points
            break

def reset_pk_assignments():
    pk_assignments.clear()
    state["pk"]["assignments"] = {}

def get_gift_id(event: GiftEvent) -> str:
    gid = getattr(event, "gift_id", None)
    if gid is not None:
        return str(gid)
    gift = getattr(event, "gift", None)
    if gift is not None:
        g_id = getattr(gift, "id", None) or getattr(gift, "gift_id", None)
        if g_id is not None:
            return str(g_id)
    return ""

def get_gift_diamonds(event: GiftEvent) -> int:
    gift = getattr(event, "gift", None)
    if gift:
        cnt = getattr(gift, "diamond_count", None)
        if cnt is not None and int(cnt) > 0:
            return max(1, int(cnt))
    gid = get_gift_id(event)
    if gid and gid in ALL_GIFTS_MAP:
        return ALL_GIFTS_MAP[gid].get("diamonds", 1)
    return 1

def get_sender_key(event: GiftEvent) -> str:
    user = getattr(event, "user", None)
    if user:
        uid = getattr(user, "user_id", None) or getattr(user, "id", None)
        if uid:
            return f"id:{uid}"
        name = getattr(user, "unique_id", None) or getattr(user, "nickname", None)
        if name:
            return f"name:{name}"
    return "unknown"

def get_sender_name(event: GiftEvent) -> str:
    user = getattr(event, "user", None)
    if user:
        return getattr(user, "nickname", None) or getattr(user, "unique_id", None) or "Fan"
    return "Fan"

def find_position_by_trigger_gift(gift_id: str) -> Optional[dict]:
    if not gift_id:
        return None
    for pos in state["pk"].get("positions", []):
        if str(pos.get("gift_id", "")).strip() == str(gift_id).strip():
            return pos
    return None

def route_pk_gift(event: GiftEvent, diamonds: int) -> Optional[str]:
    gift_id = get_gift_id(event)
    sender_key = get_sender_key(event)
    positions = state["pk"].get("positions", [])
    if not positions:
        return None

    pos = find_position_by_trigger_gift(gift_id)
    if pos:
        pk_assignments[sender_key] = {"position_id": pos["id"]}
        state["pk"]["assignments"][sender_key] = pos["id"]
        add_pk_points(pos["id"], diamonds)
        return pos["id"]

    assigned = pk_assignments.get(sender_key)
    if assigned and assigned.get("position_id"):
        pos_id = assigned["position_id"]
        if any(p["id"] == pos_id for p in positions):
            add_pk_points(pos_id, diamonds)
            return pos_id

    fallback = min(positions, key=lambda p: p.get("score", 0))
    pk_assignments[sender_key] = {"position_id": fallback["id"]}
    state["pk"]["assignments"][sender_key] = fallback["id"]
    add_pk_points(fallback["id"], diamonds)
    return fallback["id"]

async def disconnect_room():
    global current_client, current_task
    if current_client:
        try:
            await current_client.disconnect()
        except Exception:
            try:
                await current_client.stop()
            except Exception:
                pass
        current_client = None
    if current_task and not current_task.done():
        current_task.cancel()
        current_task = None
    state["connected"] = False
    state["room"] = None
    state["last_error"] = None
    reset_pk_assignments()
    pk_gift_streaks.clear()
    await broadcast_state()

async def connect_room(unique_id: str):
    global current_client, current_task
    await disconnect_room()
    unique_id = normalize_tiktok_id(unique_id)
    if not unique_id:
        state["last_error"] = "TikTok ID không hợp lệ"
        await broadcast_state()
        return

    client = TikTokLiveClient(unique_id=unique_id)

    @client.on(ConnectEvent)
    async def on_connect(_event):
        logger.info(f"Connected to TikTok Live room @{unique_id}")
        state["connected"] = True
        state["room"] = unique_id
        state["last_error"] = None
        raw_catalog = getattr(client, "gift_info", None) or getattr(client, "available_gifts", None)
        catalog = _normalize_gift_catalog(raw_catalog) if raw_catalog else []
        if catalog:
            state["gift_catalog"] = catalog
            state["gift_catalog_username"] = unique_id
            state["gift_catalog_error"] = None
        await broadcast_state()

    @client.on(DisconnectEvent)
    async def on_disconnect(_event):
        logger.warning(f"Disconnected from room @{unique_id}")
        state["connected"] = False
        await broadcast_state()

    @client.on(GiftEvent)
    async def on_gift(event: GiftEvent):
        is_mode_pk = (state.get("mode") == "multipk")
        accepting = state["accepting_gifts"]
        in_grace = state["timer"].get("finishing")
        in_score_lock = state["pk"].get("in_score_lock")

        if not accepting and not in_grace and not in_score_lock:
            return

        gift_id = get_gift_id(event)
        sender_key = get_sender_key(event)
        sender_name = get_sender_name(event)
        repeat_count = max(1, int(getattr(event, "repeat_count", 1) or 1))
        diamond_count = get_gift_diamonds(event)
        streaking = bool(getattr(event, "streaking", False))

        streak_key = (sender_key, gift_id or "unknown")
        previous_repeat = pk_gift_streaks.get(streak_key, 0)
        if repeat_count > previous_repeat:
            effective_repeat = repeat_count - previous_repeat
            pk_gift_streaks[streak_key] = repeat_count
        else:
            effective_repeat = 0

        if not streaking:
            pk_gift_streaks.pop(streak_key, None)

        diamonds = effective_repeat * diamond_count
        if diamonds <= 0:
            return

        # Register/learn gift dynamically in memory catalog
        g_obj = getattr(event, "gift", None)
        if g_obj:
            g_name = getattr(g_obj, "name", None) or getattr(g_obj, "gift_name", None) or ""
            g_img = getattr(g_obj, "image", None)
            if isinstance(g_img, dict):
                urls = g_img.get("url_list", [])
                g_icon = urls[0] if urls else ""
            elif isinstance(g_img, str):
                g_icon = g_img
            else:
                g_icon = getattr(g_obj, "gift_icon", "") or ""
            register_online_gift(gift_id, g_name, diamond_count, g_icon)

        state["last_gift_debug"] = {
            "gift_id": gift_id,
            "diamonds": diamonds,
            "repeat_count": repeat_count,
            "user": sender_name,
            "mode": state.get("mode"),
        }

        # MultiPK mode
        if is_mode_pk:
            route_pk_gift(event, diamonds)
            await broadcast_state()
            return

        # FreeMode mode
        idol = get_active_idol()
        if not idol:
            await broadcast_state()
            return

        idol["score"] = idol.get("score", 0) + diamonds
        user_gifts = idol.setdefault("user_gifts", {})
        if sender_name not in user_gifts:
            user_gifts[sender_name] = {"name": sender_name, "score": 0}
        user_gifts[sender_name]["score"] += diamonds

        tgt = state.get("target", {})
        if tgt.get("enabled") and not tgt.get("reached"):
            if idol["score"] >= tgt.get("score", 0):
                tgt["reached"] = True
                await broadcast_event("target_reached", {
                    "idol_id": idol["id"],
                    "idol_name": idol["name"],
                    "score": idol["score"],
                    "target": tgt.get("score", 0),
                })

        await broadcast_state()

    current_client = client
    state["room"] = unique_id
    current_task = asyncio.create_task(_run_client(client))
    await broadcast_state()

async def _run_client(client: TikTokLiveClient):
    try:
        await client.start()
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.error(f"TikTokLive client error: {e}")
        state["connected"] = False
        state["last_error"] = str(e)
        await broadcast_state()

async def timer_loop():
    while True:
        await asyncio.sleep(1)
        t = state["timer"]
        pk = state["pk"]
        is_mode_pk = (state.get("mode") == "multipk")

        if is_mode_pk:
            if pk.get("in_score_lock"):
                lock_rem = pk.get("score_lock_remaining", 0) - 1
                pk["score_lock_remaining"] = max(0, lock_rem)
                if pk["score_lock_remaining"] <= 0:
                    pk["in_score_lock"] = False
                    t["finished"] = True
                    t["running"] = False
                    state["accepting_gifts"] = False
                    if pk["status"] == "running":
                        pk["status"] = "finished"
                await broadcast_state()
                continue

            if not t["running"] or t["remaining"] <= 0:
                continue

            t["remaining"] -= 1
            if pk.get("fog_enabled"):
                dur = int(pk.get("fog_duration", 0))
                pk["fog_active"] = (dur == 0) or (t["remaining"] <= dur)
            else:
                pk["fog_active"] = False

            if t["remaining"] <= 0:
                t["remaining"] = 0
                t["running"] = False
                lock_sec = int(pk.get("score_lock_duration", 0))
                if lock_sec > 0 and pk["status"] == "running":
                    pk["in_score_lock"] = True
                    pk["score_lock_remaining"] = lock_sec
                else:
                    t["finished"] = True
                    state["accepting_gifts"] = False
                    if pk["status"] == "running":
                        pk["status"] = "finished"
            await broadcast_state()

        else:
            changed = False
            if t["running"] and t["remaining"] > 0:
                t["remaining"] -= 1
                changed = True
                if t["remaining"] <= 0:
                    t["remaining"] = 0
                    t["running"] = False
                    if state["gift_mode"] == "auto":
                        t["finishing"] = True
                        t["grace_remaining"] = int(t.get("grace_config", 3))
                    else:
                        t["finished"] = True

            elif t.get("finishing") and t.get("grace_remaining", 0) > 0:
                t["grace_remaining"] -= 1
                changed = True
                if t["grace_remaining"] <= 0:
                    t["finishing"] = False
                    t["finished"] = True
                    if state["gift_mode"] == "auto":
                        state["accepting_gifts"] = False

            if changed:
                await broadcast_state()

@app.on_event("startup")
async def on_startup():
    asyncio.create_task(timer_loop())
    asyncio.create_task(fetch_tiktok_online_gifts())

# --- Web pages ---
@app.get("/health")
def health():
    return {"status": "ok", "mode": state.get("mode")}

@app.get("/")
@app.get("/control")
def control_page():
    return FileResponse(str(STATIC_DIR / "control.html"))

@app.get("/overlay/popup")
def overlay_popup_page():
    return FileResponse(str(STATIC_DIR / "overlay_popup.html"))

@app.get("/overlay/pk")
def overlay_pk_page():
    return FileResponse(str(STATIC_DIR / "overlay_pk.html"))

@app.get("/overlay/rank")
def overlay_rank_page():
    return FileResponse(str(STATIC_DIR / "overlay_rank.html"))

@app.get("/overlay")
def overlay_page():
    return FileResponse(str(STATIC_DIR / "overlay.html"))

@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    sockets.append(ws)
    await ws.send_text(json.dumps({"type": "state", "data": state}, ensure_ascii=False))
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        if ws in sockets:
            sockets.remove(ws)

# --- APIs ---
@app.get("/api/state")
def api_get_state():
    return state

class ModePayload(BaseModel):
    mode: str

@app.post("/api/mode")
async def api_set_mode(payload: ModePayload):
    m = str(payload.mode).strip().lower()
    if m in ["freemode", "multipk"]:
        state["mode"] = m
        if m == "multipk":
            state["pk"]["enabled"] = True
            sync_pk_from_idols()
        await broadcast_state()
        return {"ok": True, "mode": m}
    return {"ok": False, "error": "Chế độ không hợp lệ"}

class RoomPayload(BaseModel):
    unique_id: str

@app.post("/api/room")
async def api_connect_room(payload: RoomPayload):
    await connect_room(payload.unique_id)
    return {"ok": True}

@app.post("/api/room/disconnect")
async def api_disconnect_room():
    await disconnect_room()
    return {"ok": True}

def _obj_value(obj, *keys, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        for k in keys:
            if k in obj and obj[k] is not None:
                return obj[k]
        return default
    for k in keys:
        if hasattr(obj, k):
            v = getattr(obj, k)
            if v is not None:
                return v
    return default

def _gift_image_url(gift):
    img = _obj_value(gift, "image", "icon", "img")
    if isinstance(img, str):
        return img
    return _obj_value(img, "url_list", "urls", "url", "image_url", default="") or ""

def _normalize_gift_catalog(raw):
    if raw is None:
        return []
    values = list(raw.values()) if isinstance(raw, dict) else list(raw) if isinstance(raw, (list, tuple, set)) else []
    result = []
    seen = set()
    for item in values:
        gid = _obj_value(item, "id", "gift_id")
        if gid is None:
            continue
        gid_str = str(gid)
        if gid_str in seen:
            continue
        seen.add(gid_str)
        name = _obj_value(item, "name", "gift_name", default=f"Gift #{gid_str}")
        diamonds = int(_obj_value(item, "diamond_count", "diamonds", default=1) or 1)
        img = _gift_image_url(item)
        if isinstance(img, list) and img:
            img = img[0]
        result.append({
            "id": gid_str,
            "name": str(name),
            "diamonds": diamonds,
            "img": str(img or ""),
        })
    result.sort(key=lambda g: (g["diamonds"], int(g["id"]) if g["id"].isdigit() else 0))
    return result

async def fetch_gift_catalog_for_user(username: str):
    username = normalize_tiktok_id(username)
    if not username:
        raise ValueError("Thiếu TikTok ID")
    client = TikTokLiveClient(unique_id=username)
    try:
        method = getattr(client, "fetch_gift_info", None) or getattr(client, "get_gifts", None)
        if callable(method):
            raw = await method()
            catalog = _normalize_gift_catalog(raw)
            if catalog:
                return catalog
        await client.start(fetch_gift_info=True)
        raw = getattr(client, "gift_info", None) or getattr(client, "available_gifts", None)
        return _normalize_gift_catalog(raw)
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass

@app.get("/api/tiktok/gifts")
async def api_tiktok_gifts(
    username: str = "",
    q: str = "",
    min_diamonds: int = 0,
    max_diamonds: int = 0,
    limit: int = 0,
    offset: int = 0
):
    target_user = username.strip()
    if target_user and target_user != state.get("gift_catalog_username"):
        try:
            gifts = await fetch_gift_catalog_for_user(target_user)
            if gifts:
                for ug in gifts:
                    register_online_gift(ug.get("id"), ug.get("name"), ug.get("diamonds"), ug.get("img"))
                state["gift_catalog"] = gifts
                state["gift_catalog_username"] = target_user
                state["gift_catalog_error"] = None
                await broadcast_state()
        except Exception as exc:
            state["gift_catalog_error"] = str(exc)

    results = ALL_GIFTS
    if q:
        q_term = q.strip().lower()
        results = [g for g in results if q_term in g.get("name", "").lower() or q_term == str(g.get("id", ""))]
    if min_diamonds > 0:
        results = [g for g in results if g.get("diamonds", 1) >= min_diamonds]
    if max_diamonds > 0:
        results = [g for g in results if g.get("diamonds", 1) <= max_diamonds]

    total = len(results)
    if limit > 0:
        results = results[offset:offset + limit]

    return {
        "ok": True,
        "total": total,
        "count": len(results),
        "gifts": results
    }

@app.post("/api/tiktok/gifts/refresh")
async def api_tiktok_gifts_refresh():
    try:
        count = await fetch_tiktok_online_gifts()
        return {
            "ok": True,
            "added_or_updated": count,
            "total": len(ALL_GIFTS),
            "message": f"Đã nạp và đồng bộ {len(ALL_GIFTS)} quà tặng TikTok!"
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

def normalize_tiktok_id(raw: str) -> str:
    if not raw:
        return ""
    text = raw.strip()
    match = re.search(r"tiktok\.com/@([A-Za-z0-9_.-]+)", text, re.IGNORECASE)
    if match:
        return match.group(1).lstrip("@").strip()
    return text.lstrip("@").strip()

def _ensure_tiktok_cookies(session: requests.Session):
    if "ttwid" in session.cookies:
        return
    try:
        session.get("https://www.tiktok.com/", timeout=5)
    except Exception:
        pass

def _looks_like_block_page(html: str) -> bool:
    if not html:
        return False
    lower = html.lower()
    return "verify you are human" in lower or "captcha" in lower or "secsdk-captcha" in lower

def _find_tiktok_user_info(data):
    if isinstance(data, dict):
        for k in ("userInfo", "user"):
            val = data.get(k)
            if isinstance(val, dict) and ("user" in val or "avatarLarger" in val or "avatarMedium" in val):
                return val.get("user", val)
        for v in data.values():
            found = _find_tiktok_user_info(v)
            if found:
                return found
    elif isinstance(data, list):
        for item in data:
            found = _find_tiktok_user_info(item)
            if found:
                return found
    return None

def _extract_tiktok_json(html: str) -> Optional[dict]:
    m = re.search(r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except Exception:
            pass
    m = re.search(r'<script id="SIGI_STATE"[^>]*>(.*?)</script>', html, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except Exception:
            pass
    return None

def _fallback_regex_avatar(html: str) -> Optional[str]:
    patterns = [
        r'"avatarLarger":\s*"(https:[^"\s\\]+)"',
        r'"avatarMedium":\s*"(https:[^"\s\\]+)"',
        r'"avatarThumb":\s*"(https:[^"\s\\]+)"',
    ]
    for pat in patterns:
        m = re.search(pat, html)
        if m:
            return m.group(1).replace(r"\u002F", "/").replace(r"\/", "/")
    return None

_avatar_cache: dict[str, str] = {}

def fetch_tiktok_avatar(unique_id: str) -> Optional[str]:
    clean = normalize_tiktok_id(unique_id)
    if not clean:
        return None
    if clean in _avatar_cache:
        return _avatar_cache[clean]

    import urllib.request
    import urllib.parse
    import html as htmllib

    # Social media crawler User-Agents: TikTok allows them to read OpenGraph meta without CAPTCHA
    uas = [
        "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
        "Twitterbot/1.0",
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    ]

    for ua in uas:
        for target_url in [f"https://www.tiktok.com/@{clean}", f"https://www.tiktok.com/@{clean}/live"]:
            try:
                headers = {
                    "User-Agent": ua,
                    "Accept-Language": "en-US,en;q=0.9",
                    "Referer": "https://www.tiktok.com/"
                }
                req = urllib.request.Request(target_url, headers=headers)
                with urllib.request.urlopen(req, timeout=4) as resp:
                    content = resp.read().decode("utf-8", errors="ignore")
                    # 1. High-res OpenGraph image meta tag
                    og = re.findall(r'<meta\s+property="og:image"\s+content="([^"]+)"', content)
                    if not og:
                        og = re.findall(r'https://[^"\'\s<>]+avt-[^"\'\s<>]+', content)
                    if not og:
                        og = re.findall(r'"(?:avatarLarger|avatarMedium|avatarThumb|userAvatar)":\s*"([^"]+)"', content)
                    if og:
                        raw_url = htmllib.unescape(og[0]).replace(r"\/", "/")
                        proxy_url = f"/api/avatar/proxy?url={urllib.parse.quote(raw_url)}"
                        _avatar_cache[clean] = proxy_url
                        logger.info(f"[TikTok Avatar] Resolved avatar for @{clean}: {raw_url[:60]}...")
                        return proxy_url
            except Exception as ex:
                pass

    return None

@app.get("/api/avatar/proxy")
def api_avatar_proxy(url: Optional[str] = None):
    if not url:
        raise HTTPException(status_code=400, detail="Missing url")
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://www.tiktok.com/"
        }
        resp = requests.get(url, headers=headers, timeout=6)
        if resp.status_code == 200:
            c_type = resp.headers.get("Content-Type", "image/jpeg")
            return Response(content=resp.content, media_type=c_type, headers={"Cache-Control": "public, max-age=86400"})
    except Exception:
        pass
    return RedirectResponse(url)

@app.get("/api/tiktok/avatar")
def api_tiktok_avatar(unique_id: str):
    av = fetch_tiktok_avatar(unique_id)
    return {"avatar": av}

@app.post("/api/idol/fill_avatars")
def api_fill_avatars():
    updated = 0
    for idol in state["idols"]:
        if not idol.get("avatar") and idol.get("tiktok_id"):
            av = fetch_tiktok_avatar(idol["tiktok_id"])
            if av:
                idol["avatar"] = av
                updated += 1
    if updated > 0:
        sync_pk_from_idols()
        asyncio.create_task(broadcast_state())
    return {"updated": updated}

class IdolPayload(BaseModel):
    name: str
    avatar: Optional[str] = ""
    tiktok_id: Optional[str] = ""

@app.post("/api/idol")
async def api_add_idol(payload: IdolPayload):
    name = payload.name.strip()
    if not name:
        return {"error": "Tên không được để trống"}
    tiktok_id = normalize_tiktok_id(payload.tiktok_id or "")
    avatar = payload.avatar.strip() if payload.avatar else ""
    if not avatar and tiktok_id:
        avatar = fetch_tiktok_avatar(tiktok_id) or ""

    idol = {
        "id": uuid.uuid4().hex[:8],
        "name": name,
        "avatar": avatar,
        "tiktok_id": tiktok_id,
        "score": 0,
        "active": len(state["idols"]) == 0,
        "eliminated": False,
        "user_gifts": {},
    }
    state["idols"].append(idol)
    sync_pk_from_idols()
    await broadcast_state()
    return {"ok": True, "idol": idol}

class BatchPayload(BaseModel):
    names: list[str]

@app.post("/api/idol/batch")
async def api_add_batch(payload: BatchPayload):
    added = []
    first = len(state["idols"]) == 0
    for n in payload.names:
        clean = n.strip()
        if not clean:
            continue
        idol = {
            "id": uuid.uuid4().hex[:8],
            "name": clean,
            "avatar": "",
            "tiktok_id": "",
            "score": 0,
            "active": first and len(added) == 0,
            "eliminated": False,
            "user_gifts": {},
        }
        state["idols"].append(idol)
        added.append(idol)
    sync_pk_from_idols()
    await broadcast_state()
    return {"ok": True, "added": len(added)}

class BulkDeletePayload(BaseModel):
    ids: list[str]

@app.post("/api/idol/bulk_delete")
async def api_bulk_delete(payload: BulkDeletePayload):
    to_delete = set(payload.ids)
    state["idols"] = [i for i in state["idols"]]
    state["idols"] = [i for i in state["idols"] if i["id"] not in to_delete]
    if state["idols"] and not any(i.get("active") for i in state["idols"]):
        state["idols"][0]["active"] = True
    sync_pk_from_idols()
    await broadcast_state()
    return {"ok": True, "remaining": len(state["idols"])}

@app.delete("/api/idol/all")
@app.post("/api/idol/all/delete")
async def api_delete_all_idols():
    state["idols"] = []
    sync_pk_from_idols()
    await broadcast_state()
    return {"ok": True}

@app.delete("/api/idol/{idol_id}")
async def api_remove_idol(idol_id: str):
    state["idols"] = [i for i in state["idols"] if i["id"] != idol_id]
    if state["idols"] and not any(i.get("active") for i in state["idols"]):
        state["idols"][0]["active"] = True
    sync_pk_from_idols()
    await broadcast_state()
    return {"ok": True}

@app.post("/api/idol/{idol_id}/active")
async def api_set_active(idol_id: str):
    for i in state["idols"]:
        i["active"] = (i["id"] == idol_id)
    await broadcast_state()
    return {"ok": True}

class PointsPayload(BaseModel):
    points: int

@app.post("/api/idol/{idol_id}/points")
async def api_add_points(idol_id: str, payload: PointsPayload):
    idol = get_idol(idol_id)
    if idol:
        idol["score"] = max(0, idol.get("score", 0) + payload.points)
        sync_pk_from_idols()
        await broadcast_state()
        return {"ok": True, "score": idol["score"]}
    return {"error": "Not found"}

class ScorePayload(BaseModel):
    score: int

@app.post("/api/idol/{idol_id}/set_score")
async def api_set_score(idol_id: str, payload: ScorePayload):
    idol = get_idol(idol_id)
    if idol:
        idol["score"] = max(0, payload.score)
        sync_pk_from_idols()
        await broadcast_state()
        return {"ok": True, "score": idol["score"]}
    return {"error": "Not found"}

@app.post("/api/idol/{idol_id}/reset")
async def api_reset_idol(idol_id: str):
    idol = get_idol(idol_id)
    if idol:
        idol["score"] = 0
        idol["user_gifts"] = {}
        sync_pk_from_idols()
        await broadcast_state()
        return {"ok": True}
    return {"error": "Not found"}

@app.post("/api/idol/{idol_id}/eliminate")
async def api_eliminate(idol_id: str):
    idol = get_idol(idol_id)
    if idol:
        idol["eliminated"] = True
        if idol.get("active"):
            idol["active"] = False
            for cand in state["idols"]:
                if not cand.get("eliminated"):
                    cand["active"] = True
                    break
        await broadcast_state()
        return {"ok": True}
    return {"error": "Not found"}

@app.post("/api/idol/{idol_id}/revive")
async def api_revive(idol_id: str):
    idol = get_idol(idol_id)
    if idol:
        idol["eliminated"] = False
        await broadcast_state()
        return {"ok": True}
    return {"error": "Not found"}

class DurationPayload(BaseModel):
    duration: int

@app.post("/api/timer/duration")
async def api_set_duration(payload: DurationPayload):
    d = max(1, payload.duration)
    state["timer"]["duration"] = d
    state["timer"]["remaining"] = d
    state["timer"]["finished"] = False
    state["timer"]["finishing"] = False
    await broadcast_state()
    return {"ok": True, "duration": d}

@app.post("/api/timer/start")
async def api_timer_start():
    t = state["timer"]
    if t["remaining"] <= 0:
        t["remaining"] = t["duration"]
    t["running"] = True
    t["finished"] = False
    t["finishing"] = False
    if state["gift_mode"] == "auto":
        state["accepting_gifts"] = True
    await broadcast_state()
    return {"ok": True}

@app.post("/api/timer/pause")
async def api_timer_pause():
    state["timer"]["running"] = False
    if state["gift_mode"] == "auto":
        state["accepting_gifts"] = False
    await broadcast_state()
    return {"ok": True}

@app.post("/api/timer/reset")
async def api_timer_reset():
    t = state["timer"]
    t["running"] = False
    t["remaining"] = t["duration"]
    t["finished"] = False
    t["finishing"] = False
    t["grace_remaining"] = 0
    if state["gift_mode"] == "auto":
        state["accepting_gifts"] = False
    await broadcast_state()
    return {"ok": True}

class GracePayload(BaseModel):
    seconds: int

@app.post("/api/timer/grace")
async def api_set_grace(payload: GracePayload):
    sec = max(0, min(60, payload.seconds))
    state["timer"]["grace_config"] = sec
    await broadcast_state()
    return {"ok": True, "grace_config": sec}

@app.post("/api/timer/finish")
async def api_timer_finish():
    t = state["timer"]
    t["running"] = False
    t["remaining"] = 0
    t["finished"] = True
    t["finishing"] = False
    t["grace_remaining"] = 0
    if state["gift_mode"] == "auto":
        state["accepting_gifts"] = False
    await broadcast_state()
    return {"ok": True}

class GiftModePayload(BaseModel):
    mode: str

@app.post("/api/gifts/mode")
async def api_set_gift_mode(payload: GiftModePayload):
    m = payload.mode
    if m in ("auto", "manual"):
        state["gift_mode"] = m
        if m == "auto":
            state["accepting_gifts"] = state["timer"]["running"]
        await broadcast_state()
        return {"ok": True, "gift_mode": m}
    return {"error": "Invalid mode"}

@app.post("/api/gifts/start")
async def api_gifts_start():
    state["accepting_gifts"] = True
    await broadcast_state()
    return {"ok": True}

@app.post("/api/gifts/stop")
async def api_gifts_stop():
    state["accepting_gifts"] = False
    await broadcast_state()
    return {"ok": True}

class TargetPayload(BaseModel):
    enabled: bool
    score: int

@app.post("/api/target")
async def api_set_target(payload: TargetPayload):
    state["target"]["enabled"] = payload.enabled
    state["target"]["score"] = max(1, payload.score)
    active = get_active_idol()
    if active and active.get("score", 0) >= state["target"]["score"]:
        state["target"]["reached"] = True
    else:
        state["target"]["reached"] = False
    await broadcast_state()
    return {"ok": True, "target": state["target"]}

@app.post("/api/target/reset")
async def api_reset_target():
    state["target"]["reached"] = False
    await broadcast_state()
    return {"ok": True}

# --- MultiPK APIs ---
class PkSetupPayload(BaseModel):
    num_positions: int
    positions: list[dict]

@app.post("/api/pk/setup")
async def api_pk_setup(payload: PkSetupPayload):
    n = max(2, min(5, payload.num_positions))
    state["pk"]["num_positions"] = n
    pos_colors = ["#ff56b0", "#03bef2", "#ffac3e", "#964bfa", "#ff3542"]
    new_positions = []
    for i, p in enumerate(payload.positions[:n]):
        pos_entry = {
            "id": p.get("id") or uuid.uuid4().hex[:8],
            "idol_id": p.get("idol_id", ""),
            "name": p.get("name", f"Player {i+1}"),
            "tiktok_id": p.get("tiktok_id", ""),
            "avatar": p.get("avatar", ""),
            "gift_id": str(p.get("gift_id", "")),
            "gift_name": str(p.get("gift_name", "")),
            "gift_img": str(p.get("gift_img", "")),
            "gift_diamonds": int(p.get("gift_diamonds", 1) or 1),
            "score": int(p.get("score", 0)),
            "win_streak": int(p.get("win_streak", 0)),
            "color": pos_colors[i % len(pos_colors)],
        }
        new_positions.append(pos_entry)
    while len(new_positions) < n:
        new_positions.append(default_pk_position(len(new_positions)))
    state["pk"]["positions"] = new_positions
    sync_pk_from_idols()
    await broadcast_state()
    return {"ok": True, "pk": state["pk"]}

class PkSelectPayload(BaseModel):
    position_id: str
    idol_id: str

@app.post("/api/pk/select")
async def api_pk_select(payload: PkSelectPayload):
    idol = get_idol(payload.idol_id)
    if not idol:
        return {"error": "Idol không tồn tại"}
    for pos in state["pk"].get("positions", []):
        if pos["id"] == payload.position_id:
            pos["idol_id"] = idol["id"]
            pos["name"] = idol["name"]
            pos["tiktok_id"] = idol.get("tiktok_id", "")
            pos["avatar"] = idol.get("avatar", "")
            break
    await broadcast_state()
    return {"ok": True, "pk": state["pk"]}

@app.post("/api/pk/start")
async def api_pk_start():
    state["pk"]["status"] = "running"
    state["pk"]["enabled"] = True
    state["pk"]["in_score_lock"] = False
    state["accepting_gifts"] = True
    t = state["timer"]
    if t["remaining"] <= 0:
        t["remaining"] = t["duration"]
    t["running"] = True
    t["finished"] = False
    await broadcast_state()
    return {"ok": True}

@app.post("/api/pk/pause")
async def api_pk_pause():
    state["pk"]["status"] = "paused"
    state["accepting_gifts"] = False
    state["timer"]["running"] = False
    await broadcast_state()
    return {"ok": True}

@app.post("/api/pk/end")
async def api_pk_end():
    state["pk"]["status"] = "finished"
    state["pk"]["in_score_lock"] = False
    state["accepting_gifts"] = False
    t = state["timer"]
    t["running"] = False
    t["remaining"] = 0
    t["finished"] = True
    await broadcast_state()
    return {"ok": True}

@app.post("/api/pk/reset")
async def api_pk_reset():
    state["pk"]["status"] = "standby"
    state["pk"]["in_score_lock"] = False
    state["accepting_gifts"] = False
    for p in state["pk"].get("positions", []):
        p["score"] = 0
    reset_pk_assignments()
    pk_gift_streaks.clear()
    t = state["timer"]
    t["running"] = False
    t["remaining"] = t["duration"]
    t["finished"] = False
    await broadcast_state()
    return {"ok": True}

class PkPointsPayload(BaseModel):
    position_id: str
    points: int

@app.post("/api/pk/points")
async def api_pk_points(payload: PkPointsPayload):
    add_pk_points(payload.position_id, payload.points)
    await broadcast_state()
    return {"ok": True}

class PkFogPayload(BaseModel):
    enabled: bool
    duration: int = 0

@app.post("/api/pk/fog")
async def api_pk_fog(payload: PkFogPayload):
    state["pk"]["fog_enabled"] = payload.enabled
    state["pk"]["fog_duration"] = max(0, payload.duration)
    if not payload.enabled:
        state["pk"]["fog_active"] = False
    await broadcast_state()
    return {"ok": True, "pk": state["pk"]}

class PkScoreLockPayload(BaseModel):
    duration: int

@app.post("/api/pk/score_lock")
async def api_pk_score_lock(payload: PkScoreLockPayload):
    state["pk"]["score_lock_duration"] = max(0, payload.duration)
    await broadcast_state()
    return {"ok": True, "pk": state["pk"]}

@app.post("/api/reset_all")
async def api_reset_all():
    state["timer"]["running"] = False
    state["timer"]["remaining"] = state["timer"]["duration"]
    state["timer"]["finished"] = False
    state["timer"]["finishing"] = False
    state["timer"]["grace_remaining"] = 0
    state["accepting_gifts"] = False
    state["target"]["reached"] = False
    for idol in state["idols"]:
        idol["score"] = 0
        idol["eliminated"] = False
        idol["user_gifts"] = {}
    for pos in state["pk"].get("positions", []):
        pos["score"] = 0
    reset_pk_assignments()
    pk_gift_streaks.clear()
    await broadcast_state()
    return {"ok": True}

if __name__ == "__main__":
    import uvicorn
    print("=" * 60)
    print("   🐱 Neko Overlay Studio (Unified FreeMode + MultiPK)")
    print("   Control Panel: http://localhost:8000/control")
    print("   FreeMode Popup: http://localhost:8000/overlay/popup")
    print("   MultiPK Battle: http://localhost:8000/overlay/pk")
    print("   Leaderboard:    http://localhost:8000/overlay/rank")
    print("=" * 60)
    uvicorn.run(app, host="0.0.0.0", port=8000)
