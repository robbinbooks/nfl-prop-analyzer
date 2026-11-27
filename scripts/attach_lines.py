"""Attach one sportsbook's player props to the board.

DraftKings is the line for every card. FanDuel is used only when DraftKings
has no props in the feed. Novig is requested too, and used only if both of
those books are empty. The free SportsGameOdds plan includes DraftKings and
FanDuel. One slate pull is cached for the Eastern calendar day.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import unicodedata
import urllib.parse
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "raw" / "sgo_events.json"
KEY_FILE = ROOT / "data" / "sgo_api_key"
EASTERN = ZoneInfo("America/New_York")

# First book that actually returns props wins, and then every card uses it.
BOOKS = (
    ("draftkings", "DraftKings"),
    ("fanduel", "FanDuel"),
    ("novig", "Novig"),
)

OU_STATS = {
    "receiving_yards": "rec_yds",
    "receiving_receptions": "receptions",
    "rushing_yards": "rush_yds",
    "rushing_attempts": "rush_att",
    "passing_yards": "pass_yds",
    "passing_touchdowns": "pass_tds",
}

TEAM_ALIAS = {
    "ARZ": "ARI", "AZ": "ARI",
    "JAC": "JAX", "JAG": "JAX",
    "WSH": "WAS", "WFT": "WAS",
    "LA": "LAR",
    "NOR": "NO",
    "TAM": "TB", "TBB": "TB",
    "GNB": "GB",
    "KAN": "KC", "KCC": "KC",
    "NWE": "NE",
    "SFO": "SF",
    "SD": "LAC", "LVR": "LV", "OAK": "LV",
    "STL": "LAR",
}

NICKNAMES = {
    "CARDINALS": "ARI", "FALCONS": "ATL", "RAVENS": "BAL", "BILLS": "BUF",
    "PANTHERS": "CAR", "BEARS": "CHI", "BENGALS": "CIN", "BROWNS": "CLE",
    "COWBOYS": "DAL", "BRONCOS": "DEN", "LIONS": "DET", "PACKERS": "GB",
    "TEXANS": "HOU", "COLTS": "IND", "JAGUARS": "JAX", "CHIEFS": "KC",
    "RAIDERS": "LV", "CHARGERS": "LAC", "RAMS": "LAR", "DOLPHINS": "MIA",
    "VIKINGS": "MIN", "PATRIOTS": "NE", "SAINTS": "NO", "GIANTS": "NYG",
    "JETS": "NYJ", "EAGLES": "PHI", "STEELERS": "PIT", "SEAHAWKS": "SEA",
    "49ERS": "SF", "BUCCANEERS": "TB", "TITANS": "TEN", "COMMANDERS": "WAS",
}

SUFFIXES = {"JR", "SR", "II", "III", "IV", "V"}
ABBRS = set(NICKNAMES.values())


def load_key() -> str:
    env = os.environ.get("SPORTSGAMEODDS_API_KEY", "").strip()
    if env:
        return env
    if KEY_FILE.exists():
        return KEY_FILE.read_text().strip()
    return ""


def name_key(value: str) -> str:
    text = unicodedata.normalize("NFKD", value)
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.upper().replace(".", " ").replace("'", "").replace("-", " ")
    text = re.sub(r"[^A-Z0-9 ]", " ", text)
    parts = [part for part in text.split() if part and part not in SUFFIXES]
    compact: list[str] = []
    letters = ""
    for part in parts:
        if len(part) == 1:
            letters += part
            continue
        if letters:
            compact.append(letters)
            letters = ""
        compact.append(part)
    if letters:
        compact.append(letters)
    return " ".join(compact)


def player_id_key(player_id: str) -> str:
    base = re.sub(r"_\d+_[A-Z0-9]+$", "", player_id)
    return name_key(base.replace("_", " "))


def team_abbr(side: dict) -> str:
    names = side.get("names") or {}
    short = (names.get("short") or "").upper()
    if short in ABBRS:
        return short
    if short in TEAM_ALIAS:
        return TEAM_ALIAS[short]
    medium = (names.get("medium") or "").upper()
    long_name = (names.get("long") or "").upper()
    for nickname, abbr in NICKNAMES.items():
        if nickname in medium or nickname in long_name or nickname in short:
            return abbr
    return TEAM_ALIAS.get(short, short)


def today() -> str:
    return datetime.now(EASTERN).date().isoformat()


def fetch_events(api_key: str, slate_start: str, slate_end: str) -> list[dict]:
    if CACHE.exists():
        cached = json.loads(CACHE.read_text())
        if cached.get("fetchedOn") == today() and cached.get("events"):
            print(f"using SportsGameOdds cache from {cached['fetchedOn']}")
            return cached["events"]

    start = datetime.fromisoformat(slate_start).replace(tzinfo=EASTERN) - timedelta(hours=6)
    end = datetime.fromisoformat(slate_end).replace(tzinfo=EASTERN) + timedelta(days=1)
    books = ",".join(book_id for book_id, _label in BOOKS)
    events = request_events(api_key, books, start, end)
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps({"fetchedOn": today(), "events": events}))
    print(f"fetched {len(events)} NFL events")
    return events


def request_events(api_key: str, books: str, start: datetime, end: datetime) -> list[dict]:
    events: list[dict] = []
    cursor = ""
    while True:
        params = {
            "leagueID": "NFL",
            "oddsAvailable": "true",
            "finalized": "false",
            "includeAltLines": "false",
            "bookmakerID": books,
            "startsAfter": start.isoformat(),
            "startsBefore": end.isoformat(),
            "limit": "20",
        }
        if cursor:
            params["cursor"] = cursor
        url = "https://api.sportsgameodds.com/v2/events?" + urllib.parse.urlencode(params)
        result = subprocess.run(
            ["curl", "-sS", "-w", "\n%{http_code}", "-H", f"x-api-key: {api_key}", url],
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "SportsGameOdds request failed")
        body, _, status = result.stdout.rpartition("\n")
        if status not in {"200", "201"}:
            if "novig" in books and status in {"400", "403"}:
                print("Novig is not on this key. Retrying DraftKings and FanDuel.")
                return request_events(api_key, "draftkings,fanduel", start, end)
            raise RuntimeError(f"SportsGameOdds HTTP {status}: {body[:500]}")
        payload = json.loads(body)
        events.extend(payload.get("data") or [])
        cursor = payload.get("nextCursor") or ""
        if not cursor:
            return events


def quote_for(odd: dict, book_id: str) -> dict | None:
    posted = (odd.get("byBookmaker") or {}).get(book_id) or {}
    if not posted.get("available", True):
        return None
    odds = posted.get("odds") or odd.get("bookOdds")
    if not odds:
        return None
    if odd.get("betTypeID") == "yn":
        line = 0.5
    else:
        raw = posted.get("overUnder") or odd.get("bookOverUnder")
        if raw in (None, ""):
            return None
        line = float(raw)
    return {
        "line": line,
        "odds": str(odds),
        "updatedAt": posted.get("lastUpdatedAt") or "",
    }


def relevant(odd: dict) -> str | None:
    if odd.get("periodID") != "game":
        return None
    entity = odd.get("statEntityID") or ""
    if entity in {"", "all", "home", "away"}:
        return None
    stat = odd.get("statID")
    side = odd.get("sideID")
    if stat in OU_STATS and side == "over":
        return OU_STATS[stat]
    if stat == "touchdowns" and odd.get("betTypeID") == "yn" and side == "yes":
        return "anytime_td"
    if stat == "firstTouchdown" and odd.get("betTypeID") == "yn" and side == "yes":
        return "first_td"
    return None


def index_players(players: list[dict]) -> tuple[dict, dict]:
    by_team: dict[tuple[str, str], list[dict]] = defaultdict(list)
    by_name: dict[str, list[dict]] = defaultdict(list)
    for player in players:
        key = name_key(player["name"])
        by_team[(player["team"], key)].append(player)
        by_name[key].append(player)
    return by_team, by_name


def match_player(player_id: str, teams: set[str], by_team: dict, by_name: dict) -> dict | None:
    key = player_id_key(player_id)
    on_slate = []
    for team in teams:
        on_slate.extend(by_team.get((team, key), []))
    if len(on_slate) == 1:
        return on_slate[0]
    named = by_name.get(key, [])
    if len(named) == 1:
        return named[0]
    return None


def choose_book(events: list[dict]) -> tuple[str, str]:
    counts = {book_id: 0 for book_id, _label in BOOKS}
    for event in events:
        for odd in (event.get("odds") or {}).values():
            market = relevant(odd)
            if not market:
                continue
            for book_id, _label in BOOKS:
                if quote_for(odd, book_id):
                    counts[book_id] += 1
    for book_id, label in BOOKS:
        if counts[book_id]:
            print("book coverage " + ", ".join(f"{name}={count}" for name, count in counts.items()))
            return book_id, label
    print("book coverage " + ", ".join(f"{name}={count}" for name, count in counts.items()))
    return "", ""


def attach(payload: dict) -> dict:
    api_key = load_key()
    if not api_key:
        print("No SportsGameOdds key. Put it in data/sgo_api_key or SPORTSGAMEODDS_API_KEY.")
        payload["lines"] = {"label": None, "matched": 0}
        return payload

    events = fetch_events(api_key, payload["slateStart"], payload["slateEnd"])
    book_id, label = choose_book(events)
    by_team, by_name = index_players(payload["players"])
    matched = 0
    if book_id:
        for event in events:
            teams = {
                team_abbr(event.get("teams", {}).get(side, {}))
                for side in ("home", "away")
            }
            for odd in (event.get("odds") or {}).values():
                market_id = relevant(odd)
                if not market_id:
                    continue
                quote = quote_for(odd, book_id)
                if not quote:
                    continue
                player = match_player(odd.get("playerID") or odd.get("statEntityID") or "", teams, by_team, by_name)
                if not player or market_id not in player["markets"]:
                    continue
                market = player["markets"][market_id]
                market["line"] = quote["line"]
                market["sportsbook"] = {
                    "book": book_id,
                    "label": label,
                    "line": quote["line"],
                    "odds": quote["odds"],
                    "updatedAt": quote["updatedAt"],
                }
                matched += 1

    payload["lines"] = {
        "book": book_id or None,
        "label": label or None,
        "fetchedOn": today(),
        "matched": matched,
    }
    payload["source"] = (
        f"nflverse weekly player stats, rosters, and schedules; "
        f"{label or 'no sportsbook'} lines via SportsGameOdds"
    )
    print(f"attached {matched} {label or 'sportsbook'} lines")
    return payload


def _self_test() -> None:
    players = [{
        "id": "00-1",
        "name": "Amon-Ra St. Brown",
        "team": "DET",
        "markets": {"rec_yds": {"line": 80.5, "seasonAvg": 80}},
    }, {
        "id": "00-2",
        "name": "D.J. Moore",
        "team": "CHI",
        "markets": {"rec_yds": {"line": 60.5, "seasonAvg": 60}},
    }]
    by_team, by_name = index_players(players)
    assert match_player("AMON_RA_ST_BROWN_1_NFL", {"DET", "TB"}, by_team, by_name)["id"] == "00-1"
    assert match_player("DJ_MOORE_1_NFL", {"CHI", "MIA"}, by_team, by_name)["id"] == "00-2"
    odd = {
        "statID": "receiving_yards",
        "statEntityID": "AMON_RA_ST_BROWN_1_NFL",
        "playerID": "AMON_RA_ST_BROWN_1_NFL",
        "periodID": "game",
        "betTypeID": "ou",
        "sideID": "over",
        "bookOverUnder": "84.5",
        "byBookmaker": {"draftkings": {"available": True, "odds": "-115", "overUnder": "84.5"}},
    }
    assert relevant(odd) == "rec_yds"
    attempts = dict(odd, statID="rushing_attempts", bookOverUnder="13.5")
    attempts["byBookmaker"] = {"draftkings": {"available": True, "odds": "-115", "overUnder": "13.5"}}
    assert relevant(attempts) == "rush_att"
    assert quote_for(attempts, "draftkings")["line"] == 13.5
    assert quote_for(odd, "draftkings")["line"] == 84.5
    anytime = {
        "statID": "touchdowns",
        "statEntityID": "AMON_RA_ST_BROWN_1_NFL",
        "periodID": "game",
        "betTypeID": "yn",
        "sideID": "yes",
        "byBookmaker": {"draftkings": {"available": True, "odds": "-140"}},
    }
    assert relevant(anytime) == "anytime_td"
    assert quote_for(anytime, "draftkings")["line"] == 0.5
    first = dict(anytime, statID="firstTouchdown")
    assert relevant(first) == "first_td"
    assert quote_for(first, "draftkings")["line"] == 0.5
    assert team_abbr({"names": {"short": "KC", "medium": "Chiefs"}}) == "KC"
    assert team_abbr({"names": {"short": "WSH", "medium": "Commanders"}}) == "WAS"
    print("attach_lines self-test ok")


if __name__ == "__main__":
    _self_test()
