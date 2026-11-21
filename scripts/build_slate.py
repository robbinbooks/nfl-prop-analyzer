#!/usr/bin/env python3
"""Build the Smart Money slate from the cached odds pull, nflverse, and Playbook.

Moneyline, spread, and total prices come from DraftKings. Public bet % and
money %, plus the injury report, come from one daily Playbook pull.
"""

from __future__ import annotations

import csv
import json
import subprocess
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "web" / "data" / "slate.json"
EVENTS = RAW / "sgo_events.json"
EASTERN = ZoneInfo("America/New_York")
SEASON = 2026

NICKNAMES = {
    "ARI": "Cardinals", "ATL": "Falcons", "BAL": "Ravens", "BUF": "Bills",
    "CAR": "Panthers", "CHI": "Bears", "CIN": "Bengals", "CLE": "Browns",
    "DAL": "Cowboys", "DEN": "Broncos", "DET": "Lions", "GB": "Packers",
    "HOU": "Texans", "IND": "Colts", "JAX": "Jaguars", "KC": "Chiefs",
    "LV": "Raiders", "LAC": "Chargers", "LA": "Rams", "LAR": "Rams", "MIA": "Dolphins",
    "MIN": "Vikings", "NE": "Patriots", "NO": "Saints", "NYG": "Giants",
    "NYJ": "Jets", "PHI": "Eagles", "PIT": "Steelers", "SEA": "Seahawks",
    "SF": "49ers", "TB": "Buccaneers", "TEN": "Titans", "WAS": "Commanders",
}

TO_GAME = {"LAR": "LA", "WSH": "WAS", "ARZ": "ARI", "JAC": "JAX"}
TO_LOGO = {"LA": "lar", "WAS": "wsh"}
HOME_CITY = {
    "ARI": "Glendale", "ATL": "Atlanta", "BAL": "Baltimore", "BUF": "Orchard Park",
    "CAR": "Charlotte", "CHI": "Chicago", "CIN": "Cincinnati", "CLE": "Cleveland",
    "DAL": "Arlington", "DEN": "Denver", "DET": "Detroit", "GB": "Green Bay",
    "HOU": "Houston", "IND": "Indianapolis", "JAX": "Jacksonville", "KC": "Kansas City",
    "LV": "Las Vegas", "LAC": "Inglewood", "LA": "Inglewood", "MIA": "Miami Gardens",
    "MIN": "Minneapolis", "NE": "Foxborough", "NO": "New Orleans", "NYG": "East Rutherford",
    "NYJ": "East Rutherford", "PHI": "Philadelphia", "PIT": "Pittsburgh", "SEA": "Seattle",
    "SF": "Santa Clara", "TB": "Tampa", "TEN": "Nashville", "WAS": "Landover",
}


def num(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def read_csv(name: str) -> list[dict]:
    with (RAW / name).open(newline="") as handle:
        return list(csv.DictReader(handle))


def game_code(code: str) -> str:
    code = (code or "").upper()
    return TO_GAME.get(code, code)


def show_team(code: str) -> str:
    return "LAR" if code == "LA" else code


def logo_url(code: str) -> str:
    slug = TO_LOGO.get(code, show_team(code).lower())
    return f"https://a.espncdn.com/i/teamlogos/nfl/500/{slug}.png"


def american(value) -> float | None:
    if value in (None, ""):
        return None
    text = str(value).replace("+", "")
    try:
        return float(text)
    except ValueError:
        return None


def implied(odds: float | None) -> float | None:
    if odds is None or odds == 0:
        return None
    if odds > 0:
        return 100.0 / (odds + 100.0)
    return abs(odds) / (abs(odds) + 100.0)


def devig(home_odds, away_odds) -> tuple[int | None, int | None]:
    home = implied(american(home_odds))
    away = implied(american(away_odds))
    if home is None or away is None or home + away == 0:
        return None, None
    home_share = round(100 * home / (home + away))
    return 100 - home_share, home_share


def spread_number(value) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace("+", ""))
    except ValueError:
        return None


def quote(odd: dict | None, book: str) -> dict:
    if not odd:
        return {}
    posted = (odd.get("byBookmaker") or {}).get(book) or {}
    if posted.get("available") is False:
        return {}
    return {
        "odds": posted.get("odds") or None,
        "spread": spread_number(posted.get("spread")),
        "total": spread_number(posted.get("overUnder")),
    }


def rank_map(values: dict[str, float], higher_better: bool) -> dict[str, int]:
    ordered = sorted(values, key=lambda team: values[team], reverse=higher_better)
    ranks = {}
    index = 0
    while index < len(ordered):
        end = index
        while end + 1 < len(ordered) and values[ordered[end + 1]] == values[ordered[index]]:
            end += 1
        for cursor in range(index, end + 1):
            ranks[ordered[cursor]] = index + 1
        index = end + 1
    return ranks


def weather_phrase(code: int) -> str:
    if code == 0:
        return "Clear"
    if code in (1, 2, 3):
        return "Cloudy"
    if code in (45, 48):
        return "Fog"
    if code in (51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82):
        return "Rain"
    if code in (71, 73, 75, 77, 85, 86):
        return "Snow"
    if code in (95, 96, 99):
        return "Storms"
    return "Forecast"


def curl_json(url: str) -> dict | None:
    result = subprocess.run(
        ["curl", "-fsSL", "--max-time", "20", url],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout:
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def forecast_for(city: str, start: datetime) -> dict | None:
    if start.astimezone(EASTERN) < datetime.now(EASTERN):
        return None
    found = curl_json(
        "https://geocoding-api.open-meteo.com/v1/search?"
        + f"name={city.replace(' ', '%20')}&count=1&language=en&format=json"
    )
    results = (found or {}).get("results") or []
    if not results:
        return None
    place = results[0]
    forecast = curl_json(
        "https://api.open-meteo.com/v1/forecast?"
        f"latitude={place['latitude']}&longitude={place['longitude']}"
        "&hourly=temperature_2m,precipitation,wind_speed_10m,weather_code"
        "&temperature_unit=fahrenheit&wind_speed_unit=mph&precipitation_unit=inch"
        "&timezone=America%2FNew_York&forecast_days=7"
    )
    hourly = (forecast or {}).get("hourly") or {}
    times = hourly.get("time") or []
    if not times:
        return None
    target = start.astimezone(EASTERN).strftime("%Y-%m-%dT%H:00")
    if target not in times:
        return None
    index = times.index(target)
    temp = hourly["temperature_2m"][index]
    wind = hourly["wind_speed_10m"][index]
    rain = hourly["precipitation"][index]
    code = int(hourly["weather_code"][index] or 0)
    label = weather_phrase(code)
    bits = [f"{round(temp)}°"]
    if wind and wind >= 10:
        bits.append(f"{round(wind)} mph")
    if rain and rain >= 0.01:
        bits.append(label if label in ("Rain", "Snow", "Storms") else "Precip")
    elif label != "Clear":
        bits.append(label)
    return {
        "tempF": round(temp),
        "windMph": round(wind or 0),
        "precipIn": round(rain or 0, 2),
        "label": label,
        "summary": " · ".join(bits),
    }


def team_profile(code: str, season_games: list[dict], offense: dict, defense: dict, recent_rows: dict, injuries: dict, qb: str) -> dict:
    played = []
    for game in season_games:
        if game["home_team"] != code and game["away_team"] != code:
            continue
        if not game["home_score"]:
            continue
        home = game["home_team"] == code
        points_for = num(game["home_score"] if home else game["away_score"])
        points_against = num(game["away_score"] if home else game["home_score"])
        spread = spread_number(game.get("spread_line"))
        total = spread_number(game.get("total_line"))
        home_margin = num(game["home_score"]) - num(game["away_score"])
        cover = None
        if spread is not None:
            adjusted = home_margin + spread
            if home:
                cover = "push" if adjusted == 0 else ("win" if adjusted > 0 else "loss")
            else:
                cover = "push" if adjusted == 0 else ("win" if adjusted < 0 else "loss")
        total_result = None
        if total is not None:
            combined = num(game["home_score"]) + num(game["away_score"])
            total_result = "push" if combined == total else ("over" if combined > total else "under")
        played.append({
            "home": home,
            "pf": points_for,
            "pa": points_against,
            "cover": cover,
            "total": total_result,
            "week": int(game["week"]),
            "opp": show_team(game["away_team"] if home else game["home_team"]),
            "result": "T" if points_for == points_against else ("W" if points_for > points_against else "L"),
        })

    def tally(rows, key):
        wins = sum(1 for row in rows if row[key] == "win" or (key == "result" and row[key] == "W"))
        losses = sum(1 for row in rows if row[key] == "loss" or (key == "result" and row[key] == "L"))
        pushes = sum(1 for row in rows if row[key] in ("push", "T"))
        return wins, losses, pushes

    def record(rows):
        wins, losses, ties = tally(rows, "result")
        text = f"{wins}-{losses}"
        return f"{text}-{ties}" if ties else text

    games = len(played) or 1
    return {
        "abbr": show_team(code),
        "code": code,
        "name": NICKNAMES.get(code, code),
        "logo": logo_url(code),
        "qb": qb,
        "record": record(played),
        "homeRecord": record([row for row in played if row["home"]]),
        "awayRecord": record([row for row in played if not row["home"]]),
        "ppg": round(sum(row["pf"] for row in played) / games, 1),
        "papg": round(sum(row["pa"] for row in played) / games, 1),
        "ats": "%d-%d" % tally(played, "cover")[:2],
        "overs": sum(1 for row in played if row["total"] == "over"),
        "unders": sum(1 for row in played if row["total"] == "under"),
        "recent": [
            {
                "week": row["week"],
                "opp": row["opp"],
                "home": row["home"],
                "result": row["result"],
                "pf": int(row["pf"]),
                "pa": int(row["pa"]),
            }
            for row in played[-5:][::-1]
        ],
        "injuries": injuries.get(code, []),
        "rates": {
            "pass": offense[code]["pass"] / games,
            "rush": offense[code]["rush"] / games,
            "passAllowed": defense[code]["pass"] / games,
            "rushAllowed": defense[code]["rush"] / games,
            "yards": (offense[code]["pass"] + offense[code]["rush"]) / games,
            "yardsAllowed": (defense[code]["pass"] + defense[code]["rush"]) / games,
        },
    }


def main() -> None:
    games = [
        game for game in read_csv("games.csv")
        if game["season"] == str(SEASON) and game["game_type"] == "REG"
    ]
    played = [game for game in games if game["home_score"]]
    current_week = min(int(game["week"]) for game in games if not game["home_score"])
    slate = [game for game in games if int(game["week"]) == current_week]
    events = json.loads(EVENTS.read_text()).get("events") or [] if EVENTS.exists() else []

    offense = defaultdict(lambda: {"pass": 0.0, "rush": 0.0})
    for row in read_csv("stats_player_week_2026.csv"):
        if row.get("season_type") not in ("", "REG") or int(row["week"]) >= current_week:
            continue
        team = row["team"]
        offense[team]["pass"] += num(row.get("passing_yards"))
        offense[team]["rush"] += num(row.get("rushing_yards"))
    week_yards = defaultdict(lambda: {"pass": 0.0, "rush": 0.0})
    for row in read_csv("stats_player_week_2026.csv"):
        if row.get("season_type") not in ("", "REG") or int(row["week"]) >= current_week:
            continue
        key = (row["team"], int(row["week"]))
        week_yards[key]["pass"] += num(row.get("passing_yards"))
        week_yards[key]["rush"] += num(row.get("rushing_yards"))
    defense = defaultdict(lambda: {"pass": 0.0, "rush": 0.0})
    for game in played:
        if int(game["week"]) >= current_week:
            continue
        week = int(game["week"])
        away = week_yards[(game["away_team"], week)]
        home = week_yards[(game["home_team"], week)]
        defense[game["home_team"]]["pass"] += away["pass"]
        defense[game["home_team"]]["rush"] += away["rush"]
        defense[game["away_team"]]["pass"] += home["pass"]
        defense[game["away_team"]]["rush"] += home["rush"]

    teams = sorted({game["home_team"] for game in played} | {game["away_team"] for game in played})
    per_game = {}
    for team in teams:
        count = sum(1 for game in played if int(game["week"]) < current_week and team in (game["home_team"], game["away_team"])) or 1
        per_game[team] = count
    ranks = {
        "offense": rank_map({team: (offense[team]["pass"] + offense[team]["rush"]) / per_game[team] for team in teams}, True),
        "defense": rank_map({team: (defense[team]["pass"] + defense[team]["rush"]) / per_game[team] for team in teams}, False),
        "passOff": rank_map({team: offense[team]["pass"] / per_game[team] for team in teams}, True),
        "rushOff": rank_map({team: offense[team]["rush"] / per_game[team] for team in teams}, True),
        "passDef": rank_map({team: defense[team]["pass"] / per_game[team] for team in teams}, False),
        "rushDef": rank_map({team: defense[team]["rush"] / per_game[team] for team in teams}, False),
    }

    outs = defaultdict(list)
    injury_file = RAW / "injuries_2026.csv"
    roster = read_csv("roster_2026.csv")
    names = {
        row["gsis_id"]: row.get("full_name") or ""
        for row in roster
        if row.get("gsis_id") and row.get("week") == str(current_week)
    }
    if injury_file.exists():
        for row in read_csv("injuries_2026.csv"):
            if row.get("week") != str(current_week) or (row.get("report_status") or "").lower() != "out":
                continue
            outs[row["team"]].append({
                "name": names.get(row.get("gsis_id"), row.get("full_name") or "Player"),
                "detail": (row.get("report_primary_injury") or "").strip(),
            })

    by_pair = {}
    for event in events:
        home = game_code(((event.get("teams") or {}).get("home") or {}).get("names", {}).get("short"))
        away = game_code(((event.get("teams") or {}).get("away") or {}).get("names", {}).get("short"))
        by_pair[(away, home)] = event

    forecasts = {}
    cards = []
    for game in sorted(slate, key=lambda item: (item["gameday"], item.get("gametime") or "")):
        event = by_pair.get((game["away_team"], game["home_team"]))
        odds = (event or {}).get("odds") or {}
        home_names = (((event or {}).get("teams") or {}).get("home") or {}).get("names") or {}
        venue = (((event or {}).get("info") or {}).get("venue") or {})
        clock = (game.get("gametime") or "").strip()
        start_raw = ((event or {}).get("status") or {}).get("startsAt")
        if start_raw:
            # The odds feed has the flexed kickoff. The schedule file can still
            # show the time from before a window change.
            start = datetime.fromisoformat(start_raw.replace("Z", "+00:00"))
        elif game.get("gameday") and clock:
            start = datetime.fromisoformat(f"{game['gameday']}T{clock}").replace(tzinfo=EASTERN)
        else:
            start = datetime.now(EASTERN)
        kick = start.astimezone(EASTERN)
        indoors = (game.get("roof") or "").lower() in ("dome", "closed")
        city = venue.get("city") or HOME_CITY.get(game["home_team"], "")
        if game["home_team"] == "SF" and "mexico" in (venue.get("city") or "").lower():
            city = venue["city"]
        weather = None
        if not indoors and city:
            if city not in forecasts:
                cast = forecast_for(city, start)
                if cast:
                    forecasts[city] = cast
            weather = forecasts.get(city)

        def side_market(side: str) -> dict:
            ml = odds.get(f"points-{side}-game-ml-{side}")
            sp = odds.get(f"points-{side}-game-sp-{side}")
            return {
                "moneyline": {
                    "draftkings": quote(ml, "draftkings").get("odds"),
                    "fanduel": quote(ml, "fanduel").get("odds"),
                    "open": (ml or {}).get("openBookOdds"),
                },
                "spread": {
                    "draftkings": quote(sp, "draftkings").get("spread"),
                    "draftkingsOdds": quote(sp, "draftkings").get("odds"),
                    "fanduel": quote(sp, "fanduel").get("spread"),
                    "fanduelOdds": quote(sp, "fanduel").get("odds"),
                    "open": spread_number((sp or {}).get("openBookSpread")),
                    "openOdds": (sp or {}).get("openBookOdds"),
                },
            }

        over = odds.get("points-all-game-ou-over")
        under = odds.get("points-all-game-ou-under")
        away_m = side_market("away")
        home_m = side_market("home")
        implied_away, implied_home = devig(
            home_m["moneyline"]["draftkings"],
            away_m["moneyline"]["draftkings"],
        )
        open_away, open_home = devig(home_m["moneyline"]["open"], away_m["moneyline"]["open"])
        total_now = quote(over, "draftkings").get("total")
        total_open = spread_number((over or {}).get("openBookOverUnder"))
        signals = []
        if implied_home is not None and open_home is not None:
            opened_home = open_home >= 50
            now_home = implied_home >= 50
            if opened_home != now_home:
                signals.append({
                    "id": "flip",
                    "label": "Favorite flipped",
                    "detail": "The moneyline favorite changed between the open and the current number.",
                })
            elif abs(implied_home - open_home) >= 8:
                signals.append({
                    "id": "ml-move",
                    "label": "Moneyline move",
                    "detail": f"No-vig home price moved from {open_home}% to {implied_home}%.",
                })
        if home_m["spread"]["open"] is not None and home_m["spread"]["draftkings"] is not None:
            delta = home_m["spread"]["draftkings"] - home_m["spread"]["open"]
            if abs(delta) >= 1.5:
                signals.append({
                    "id": "spread-move",
                    "label": "Spread move",
                    "detail": f"Home spread moved from {home_m['spread']['open']:+g} to {home_m['spread']['draftkings']:+g}.",
                })
        if total_open is not None and total_now is not None and abs(total_now - total_open) >= 1.5:
            signals.append({
                "id": "total-move",
                "label": "Total move",
                "detail": f"Total moved from {total_open:g} to {total_now:g}.",
            })

        def pack(code: str, qb: str) -> dict:
            profile = team_profile(code, played, offense, defense, {}, outs, qb)
            count = per_game[code]
            profile["ranks"] = {key: ranks[key].get(code) for key in ranks}
            profile["teams"] = len(teams)
            profile["passYpg"] = round(offense[code]["pass"] / count, 1)
            profile["rushYpg"] = round(offense[code]["rush"] / count, 1)
            profile["passAllowed"] = round(defense[code]["pass"] / count, 1)
            profile["rushAllowed"] = round(defense[code]["rush"] / count, 1)
            profile["color"] = ((((event or {}).get("teams") or {}).get("home" if code == game["home_team"] else "away") or {}).get("colors") or {}).get("primary") or "#7eb6ff"
            profile.pop("rates", None)
            return profile

        cards.append({
            "id": game["game_id"],
            "kickoff": kick.strftime("%a %-I:%M %p ET"),
            "date": kick.strftime("%b %-d"),
            "stadium": venue.get("name") or game.get("stadium") or "",
            "city": city,
            "roof": game.get("roof") or "",
            "indoors": indoors,
            "weather": None if indoors else weather,
            "away": pack(game["away_team"], game.get("away_qb_name") or ""),
            "home": pack(game["home_team"], game.get("home_qb_name") or ""),
            "implied": {"away": implied_away, "home": implied_home, "openAway": open_away, "openHome": open_home},
            "money": None,
            "tickets": None,
            "total": {
            "line": total_now,
            "fanduelLine": quote(over, "fanduel").get("total"),
            "open": total_open,
                "over": {
                    "draftkings": quote(over, "draftkings").get("odds"),
                    "fanduel": quote(over, "fanduel").get("odds"),
                    "open": (over or {}).get("openBookOdds"),
                },
                "under": {
                    "draftkings": quote(under, "draftkings").get("odds"),
                    "fanduel": quote(under, "fanduel").get("odds"),
                    "open": (under or {}).get("openBookOdds"),
                },
            },
            "awayMarket": away_m,
            "homeMarket": home_m,
            "signals": signals,
            "final": {
                "away": int(game["away_score"]) if game.get("away_score") else None,
                "home": int(game["home_score"]) if game.get("home_score") else None,
            },
        })

    from playbook import apply_public, public_slate

    handle = apply_public(cards, public_slate())
    payload = {
        "season": SEASON,
        "week": current_week,
        "throughWeek": current_week - 1,
        "generatedAt": datetime.now(EASTERN).strftime("%Y-%m-%dT%H:%M:%S%z"),
        "book": "DraftKings",
        "handleAvailable": handle,
        "games": cards,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, separators=(",", ":")))
    print(f"week {current_week} games {len(cards)} wrote {OUT}")


if __name__ == "__main__":
    main()
