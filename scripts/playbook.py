"""Daily Playbook pull for public betting splits and the NFL injury report.

One splits call and one injuries call cover the whole slate. The result is
cached for the Eastern day so a rebuild does not spend the free allowance again.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "raw" / "playbook.json"
KEY_FILE = ROOT / "data" / "playbook_api_key"
EASTERN = ZoneInfo("America/New_York")

NICKNAMES = {
    "CARDINALS": "ARI", "FALCONS": "ATL", "RAVENS": "BAL", "BILLS": "BUF",
    "PANTHERS": "CAR", "BEARS": "CHI", "BENGALS": "CIN", "BROWNS": "CLE",
    "COWBOYS": "DAL", "BRONCOS": "DEN", "LIONS": "DET", "PACKERS": "GB",
    "TEXANS": "HOU", "COLTS": "IND", "JAGUARS": "JAX", "CHIEFS": "KC",
    "RAIDERS": "LV", "CHARGERS": "LAC", "RAMS": "LA", "DOLPHINS": "MIA",
    "VIKINGS": "MIN", "PATRIOTS": "NE", "SAINTS": "NO", "GIANTS": "NYG",
    "JETS": "NYJ", "EAGLES": "PHI", "STEELERS": "PIT", "SEAHAWKS": "SEA",
    "49ERS": "SF", "BUCCANEERS": "TB", "TITANS": "TEN", "COMMANDERS": "WAS",
}
TO_GAME = {"LAR": "LA", "WSH": "WAS", "ARZ": "ARI", "JAC": "JAX"}
LISTED = {"out", "doubtful"}


def today() -> str:
    return datetime.now(EASTERN).date().isoformat()


def load_key() -> str:
    env = os.environ.get("PLAYBOOK_API_KEY", "").strip()
    if env:
        return env
    if KEY_FILE.exists():
        return KEY_FILE.read_text().strip()
    return ""


def team_code(name: str) -> str:
    text = (name or "").upper().replace(".", "").strip()
    if not text:
        return ""
    if text in TO_GAME:
        return TO_GAME[text]
    if text in set(NICKNAMES.values()) or text in {"LA", "WAS", "ARI", "JAX"}:
        return text
    for nickname, code in NICKNAMES.items():
        if text == nickname or text.endswith(" " + nickname):
            return code
    return ""


def percent(node: dict, key: str) -> int | None:
    if not isinstance(node, dict) or node.get(key) is None:
        return None
    try:
        return int(round(float(node[key])))
    except (TypeError, ValueError):
        return None


def side_split(block: dict) -> dict:
    bets = (block or {}).get("bets") or {}
    money = (block or {}).get("money") or {}
    return {
        "away": percent(money, "awayPercent"),
        "home": percent(money, "homePercent"),
        "awayTickets": percent(bets, "awayPercent"),
        "homeTickets": percent(bets, "homePercent"),
    }


def parse_splits(payload: dict) -> dict:
    parsed = {}
    for row in payload.get("data") or []:
        away = team_code(row.get("awayTeamName") or row.get("awayTeam") or "")
        home = team_code(row.get("homeTeamName") or row.get("homeTeam") or "")
        markets = row.get("splits") or {}
        moneyline = side_split(markets.get("moneyline") or {})
        if not away or not home or moneyline["away"] is None or moneyline["home"] is None:
            continue
        total = markets.get("total") or {}
        parsed[(away, home)] = {
            "money": {"away": moneyline["away"], "home": moneyline["home"]},
            "tickets": {"away": moneyline["awayTickets"], "home": moneyline["homeTickets"]},
            "spread": side_split(markets.get("spread") or {}),
            "total": {
                "over": percent(total.get("money") or {}, "overPercent"),
                "under": percent(total.get("money") or {}, "underPercent"),
                "overTickets": percent(total.get("bets") or {}, "overPercent"),
                "underTickets": percent(total.get("bets") or {}, "underPercent"),
            },
        }
    return parsed


def parse_injuries(payload: dict) -> dict:
    listed = {}
    for team in payload.get("data") or []:
        code = team_code(team.get("teamAbbr") or team.get("team") or "")
        if not code:
            continue
        players = []
        for player in team.get("players") or []:
            status = (player.get("gameDesignation") or player.get("status") or "").strip()
            if status.lower() not in LISTED:
                continue
            reason = (player.get("reason") or "").strip()
            players.append({
                "name": player.get("name") or "Player",
                "detail": f"{status} · {reason}" if reason else status,
            })
        listed[code] = players
    return listed


def request_json(path: str, api_key: str) -> dict | None:
    url = f"https://api.playbook-api.com/v1/{path}?league=NFL"
    result = subprocess.run(
        ["curl", "-sS", "--max-time", "30", "-w", "\n%{http_code}", "-H", f"x-api-key: {api_key}", url],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        print(f"Playbook {path} request failed")
        return None
    body, _, status = result.stdout.rpartition("\n")
    if status != "200":
        print(f"Playbook {path} HTTP {status}")
        return None
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        print(f"Playbook {path} returned invalid JSON")
        return None


def public_slate() -> dict | None:
    cached = {}
    if CACHE.exists():
        try:
            cached = json.loads(CACHE.read_text())
        except json.JSONDecodeError:
            cached = {}
    fresh = cached.get("fetchedOn") == today()
    splits_raw = cached.get("splits") if fresh else None
    injuries_raw = cached.get("injuries") if fresh else None
    if fresh and splits_raw is not None and injuries_raw is not None:
        print(f"using Playbook cache from {cached['fetchedOn']}")
    else:
        api_key = load_key()
        if not api_key:
            print("No Playbook key. Public splits stay off. Add data/playbook_api_key or PLAYBOOK_API_KEY.")
            return None
        if splits_raw is None:
            splits_raw = request_json("splits", api_key)
        if injuries_raw is None:
            injuries_raw = request_json("injuries", api_key)
        if splits_raw is None and injuries_raw is None:
            return None
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps({
            "fetchedOn": today(),
            "splits": splits_raw,
            "injuries": injuries_raw,
        }))
    splits = parse_splits(splits_raw or {})
    injuries = parse_injuries(injuries_raw) if injuries_raw is not None else None
    print(f"Playbook splits {len(splits)} injuries {'yes' if injuries is not None else 'no'}")
    return {"splits": splits, "injuries": injuries}


def apply_public(cards: list[dict], public: dict | None) -> bool:
    if not public:
        return False
    splits = public.get("splits") or {}
    injuries = public.get("injuries")
    matched = 0
    for card in cards:
        away = card["away"]["code"]
        home = card["home"]["code"]
        split = splits.get((away, home))
        if split:
            matched += 1
            card["money"] = split["money"]
            card["tickets"] = split["tickets"]
            card["spreadSplit"] = split["spread"]
            card["totalSplit"] = split["total"]
            card["signals"].extend(public_signals(card, split))
        if injuries is not None:
            card["away"]["injuries"] = injuries.get(away, [])
            card["home"]["injuries"] = injuries.get(home, [])
    print(f"Playbook matched {matched} games")
    return matched > 0


def public_signals(card: dict, split: dict) -> list[dict]:
    money = split["money"]
    tickets = split["tickets"]
    signals = []
    if money["away"] is not None and max(money["away"], money["home"]) >= 80:
        side = "away" if money["away"] >= money["home"] else "home"
        signals.append({
            "id": "heavy",
            "label": "Heavy Money",
            "detail": f"{money[side]}% of moneyline money is on the {card[side]['name']}.",
        })
    if None not in (money["away"], tickets["away"], tickets["home"]):
        gap = abs(money["away"] - tickets["away"])
        if gap >= 15:
            signals.append({
                "id": "diverge",
                "label": "Money/Ticket Divergence",
                "detail": f"Moneyline money and tickets differ by {gap} points.",
            })
    return signals
