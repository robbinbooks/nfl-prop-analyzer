#!/usr/bin/env python3
"""Build the Week board from nflverse schedule, roster, and weekly player stats.

Lines are a season-average baseline (nearest half-point), not sportsbook prices.
Hit rate is how often the player cleared that line. Matchup is how generous the
opponent has been to this stat, 100 = softest defense in the league.
"""

from __future__ import annotations

import csv
import json
import math
import re
import subprocess
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "web" / "data" / "board.json"
SEASON = 2026

SOURCES = {
    "games.csv": "https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv",
    "roster_2026.csv": "https://github.com/nflverse/nflverse-data/releases/download/rosters/roster_2026.csv",
    "stats_player_week_2026.csv": "https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_2026.csv",
    "snap_counts_2026.csv": "https://github.com/nflverse/nflverse-data/releases/download/snap_counts/snap_counts_2026.csv",
}

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

MARKETS = [
    {
        "id": "rec_yds",
        "label": "Rec Yds",
        "unit": "rec yds",
        "stat_label": "receiving yards",
        "positions": {"WR", "TE", "RB"},
        "value": lambda r: num(r, "receiving_yards"),
        "played": lambda r: num(r, "targets") > 0 or num(r, "receptions") > 0,
        "volume": lambda r: num(r, "targets"),
        "min_volume": 25,
        "min_games": 4,
        "group": "position",
        "count_snaps": True,
    },
    {
        "id": "receptions",
        "label": "Receptions",
        "unit": "rec",
        "stat_label": "receptions",
        "positions": {"WR", "TE", "RB"},
        "value": lambda r: num(r, "receptions"),
        "played": lambda r: num(r, "targets") > 0 or num(r, "receptions") > 0,
        "volume": lambda r: num(r, "targets"),
        "min_volume": 25,
        "min_games": 4,
        "group": "position",
        "count_snaps": True,
    },
    {
        "id": "rush_yds",
        "label": "Rush Yds",
        "unit": "rush yds",
        "stat_label": "rushing yards",
        "positions": {"RB", "QB", "WR"},
        "value": lambda r: num(r, "rushing_yards"),
        "played": lambda r: num(r, "carries") > 0,
        "volume": lambda r: num(r, "carries"),
        "min_volume": 25,
        "min_games": 4,
        "group": "position",
        "count_snaps": True,
        "snap_positions": {"RB", "QB", "WR"},
    },
    {
        "id": "rush_att",
        "label": "Rush Att",
        "unit": "rush att",
        "stat_label": "rushing attempts",
        "positions": {"RB", "QB", "WR"},
        "value": lambda r: num(r, "carries"),
        "played": lambda r: num(r, "carries") > 0,
        "volume": lambda r: num(r, "carries"),
        "min_volume": 25,
        "min_games": 4,
        "group": "position",
        "count_snaps": True,
        "snap_positions": {"RB", "QB", "WR"},
    },
    {
        "id": "pass_yds",
        "label": "Pass Yds",
        "unit": "pass yds",
        "stat_label": "passing yards",
        "positions": {"QB"},
        "value": lambda r: num(r, "passing_yards"),
        "played": lambda r: num(r, "attempts") > 0,
        "volume": lambda r: num(r, "attempts"),
        "min_volume": 120,
        "min_games": 4,
        "group": "QB",
    },
    {
        "id": "pass_tds",
        "label": "Pass TDs",
        "unit": "pass TD",
        "stat_label": "passing touchdowns",
        "positions": {"QB"},
        "value": lambda r: num(r, "passing_tds"),
        "played": lambda r: num(r, "attempts") > 0,
        "volume": lambda r: num(r, "attempts"),
        "min_volume": 120,
        "min_games": 4,
        "group": "QB",
    },
    {
        "id": "anytime_td",
        "label": "Anytime TD",
        "unit": "TD",
        "stat_label": "touchdowns",
        "positions": {"WR", "RB", "TE", "QB"},
        "value": lambda r: num(r, "rushing_tds") + num(r, "receiving_tds"),
        "played": lambda r: num(r, "carries") + num(r, "targets") + num(r, "attempts") > 0,
        "volume": lambda r: num(r, "carries") + num(r, "targets"),
        "min_volume": 15,
        "min_games": 4,
        "group": "position",
    },
]


def num(row: dict, key: str) -> float:
    raw = row.get(key) or 0
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def curl_bytes(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["curl", "-fsSL", "-o", str(dest), url],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"download failed: {url}")


def espn_player_id(athlete: dict) -> str:
    for link in athlete.get("links") or []:
        href = link.get("href") or ""
        match = re.search(r"/id/(\d+)", href)
        if match:
            return match.group(1)
    return ""


def current_outs(week: int, roster_rows: list[dict]) -> dict[str, dict]:
    """Game-status Out for this week. nflverse when the report is posted, otherwise ESPN."""
    injury_file = RAW / "injuries_2026.csv"
    try:
        curl_bytes(
            "https://github.com/nflverse/nflverse-data/releases/download/injuries/injuries_2026.csv",
            injury_file,
        )
    except RuntimeError as error:
        print(f"injury download skipped: {error}")

    outs: dict[str, dict] = {}
    if injury_file.exists():
        with injury_file.open(newline="") as handle:
            week_rows = [
                row for row in csv.DictReader(handle)
                if row.get("season_type") in ("", "REG") and row.get("week") == str(week)
            ]
        posted = [row for row in week_rows if (row.get("report_status") or "").strip()]
        if posted:
            for row in posted:
                if row["report_status"].strip().lower() != "out" or not row.get("gsis_id"):
                    continue
                outs[row["gsis_id"]] = {
                    "status": "Out",
                    "detail": (row.get("report_primary_injury") or "").strip(),
                }
            print(f"nflverse week {week} outs {len(outs)}")
            return outs

    ordered = sorted(roster_rows, key=lambda row: int(row.get("week") or 0))
    espn_to_gsis = {
        row["espn_id"]: row["gsis_id"]
        for row in ordered
        if row.get("espn_id") and row.get("gsis_id")
    }
    names = {
        (row.get("team"), (row.get("full_name") or "").lower()): row.get("gsis_id")
        for row in ordered
        if row.get("gsis_id")
    }
    espn_path = RAW / "espn_injuries.json"
    try:
        curl_bytes("https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries", espn_path)
    except RuntimeError as error:
        print(f"injury download skipped: {error}")
    if not espn_path.exists():
        return outs
    try:
        feed = json.loads(espn_path.read_text())
    except json.JSONDecodeError as error:
        print(f"injury feed skipped: {error}")
        return outs

    for team in feed.get("injuries") or []:
        for item in team.get("injuries") or []:
            if (item.get("status") or "").strip().lower() != "out":
                continue
            athlete = item.get("athlete") or {}
            gsis = espn_to_gsis.get(espn_player_id(athlete))
            if not gsis:
                abbr = ((athlete.get("team") or {}).get("abbreviation") or "").upper()
                if abbr == "WSH":
                    abbr = "WAS"
                if abbr == "LAR":
                    abbr = "LA"
                gsis = names.get((abbr, (athlete.get("displayName") or "").lower()))
            if not gsis:
                continue
            detail = ""
            details = item.get("details") or {}
            if isinstance(details, dict):
                detail = (details.get("type") or "").strip()
            outs[gsis] = {"status": "Out", "detail": detail}
    print(f"espn outs matched {len(outs)}")
    return outs


def download() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    for name, url in SOURCES.items():
        dest = RAW / name
        if dest.exists() and dest.stat().st_size > 0:
            continue
        print(f"downloading {name}")
        try:
            urllib.request.urlretrieve(url, dest)
        except Exception as error:
            print(f"download retry for {name}: {error}")
            curl_bytes(url, dest)


def canon_team(code: str) -> str:
    return "LA" if code == "LAR" else code


def offensive_snaps(roster_rows: list[dict]) -> dict[tuple[str, int], dict]:
    """Games with an offensive snap, keyed by gsis id and week.

    A receiving game with snaps but no target and no yard is still a played game.
    Special-teams and defensive snaps do not count.
    """
    pfr_to_gsis = {}
    name_team = {}
    for row in roster_rows:
        if row.get("pfr_id") and row.get("gsis_id"):
            pfr_to_gsis[row["pfr_id"]] = row["gsis_id"]
        if row.get("full_name") and row.get("gsis_id") and row.get("team"):
            name_team[(row["full_name"].lower(), row["team"])] = row["gsis_id"]

    played: dict[tuple[str, int], dict] = {}
    snap_file = RAW / "snap_counts_2026.csv"
    if not snap_file.exists():
        return played
    for snap in read_csv("snap_counts_2026.csv"):
        if snap.get("game_type") not in ("", "REG") or num(snap, "offense_snaps") <= 0:
            continue
        week = int(snap["week"])
        gsis = pfr_to_gsis.get(snap.get("pfr_player_id") or "")
        if not gsis:
            gsis = name_team.get(((snap.get("player") or "").lower(), snap.get("team")))
        if not gsis:
            continue
        played[(gsis, week)] = {
            "team": canon_team(snap.get("team") or ""),
            "opp": canon_team(snap.get("opponent") or ""),
        }
    return played


def read_csv(name: str) -> list[dict]:
    with (RAW / name).open(newline="") as handle:
        return list(csv.DictReader(handle))


def ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def nearest_half(avg: float) -> float:
    base = math.floor(avg)
    candidates = [c for c in (base - 0.5, base + 0.5, base + 1.5) if c > 0]
    if not candidates:
        return 0.5
    return min(candidates, key=lambda c: (abs(c - avg), c))


def generosity(per_game: dict[str, float]) -> tuple[dict[str, int], dict[str, int], int]:
    items = sorted(per_game.items(), key=lambda kv: (-kv[1], kv[0]))
    rank: dict[str, int] = {}
    index = 0
    while index < len(items):
        end = index
        while end + 1 < len(items) and items[end + 1][1] == items[index][1]:
            end += 1
        for cursor in range(index, end + 1):
            rank[items[cursor][0]] = index + 1
        index = end + 1
    count = len(items)
    scores = {
        team: round(100 * (count - place) / (count - 1)) if count > 1 else 50
        for team, place in rank.items()
    }
    return scores, rank, count


def fmt_num(value: float) -> str:
    if abs(value - round(value)) < 0.05:
        return str(int(round(value)))
    return f"{value:.1f}"


def show_team(code: str) -> str:
    return "LAR" if code == "LA" else code


def main() -> None:
    download()
    games = read_csv("games.csv")
    roster = read_csv("roster_2026.csv")
    stats = read_csv("stats_player_week_2026.csv")

    season_games = [
        game for game in games
        if game["season"] == str(SEASON) and game["game_type"] == "REG"
    ]
    open_weeks = sorted({int(game["week"]) for game in season_games if not game["home_score"]})
    current_week = open_weeks[0] if open_weeks else max(int(game["week"]) for game in season_games)
    played_games = [
        game for game in season_games
        if game["home_score"] and int(game["week"]) < current_week
    ]
    slate = [game for game in season_games if int(game["week"]) == current_week]
    slate_days = sorted(game["gameday"] for game in slate)

    team_game: dict[str, dict] = {}
    for game in slate:
        team_game[game["home_team"]] = {"opp": game["away_team"], "home": True}
        team_game[game["away_team"]] = {"opp": game["home_team"], "home": False}

    site: dict[tuple[int, str], bool] = {}
    for game in played_games:
        week = int(game["week"])
        site[(week, game["home_team"])] = True
        site[(week, game["away_team"])] = False

    games_played: dict[str, int] = defaultdict(int)
    for game in played_games:
        games_played[game["home_team"]] += 1
        games_played[game["away_team"]] += 1

    roster_now = {}
    for row in roster:
        if row.get("week") != str(current_week) or row.get("status") != "ACT":
            continue
        if not row.get("gsis_id"):
            continue
        roster_now[row["gsis_id"]] = row

    outs = current_outs(current_week, roster)

    by_player: dict[str, list[dict]] = defaultdict(list)
    for row in stats:
        if row.get("season_type") not in ("", "REG") or int(row["week"]) >= current_week:
            continue
        by_player[row["player_id"]].append(row)

    # Defense allowed, keyed by market id then position group then team.
    allowed_sum: dict[tuple[str, str], dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for row in stats:
        if row.get("season_type") not in ("", "REG") or int(row["week"]) >= current_week:
            continue
        defense = row["opponent_team"]
        position = row["position"] or ""
        for market in MARKETS:
            group = position if market["group"] == "position" else "QB"
            if market["group"] == "position" and position not in market["positions"]:
                continue
            if market["group"] == "QB" and position != "QB":
                continue
            allowed_sum[(market["id"], group)][defense] += market["value"](row)

    matchup_tables = {}
    for key, totals in allowed_sum.items():
        per_game = {
            team: total / games_played[team]
            for team, total in totals.items()
            if games_played[team]
        }
        scores, ranks, count = generosity(per_game)
        league = sum(per_game.values()) / len(per_game) if per_game else 0
        matchup_tables[key] = {
            "scores": scores,
            "ranks": ranks,
            "teams": count,
            "per_game": per_game,
            "league": league,
        }

    snaps = offensive_snaps(roster)
    print(f"offensive snap games {len(snaps)}")
    player_ids = set(by_player)
    player_ids.update(player_id for player_id, _week in snaps if player_id in roster_now)

    players = []
    for player_id in player_ids:
        rows = by_player.get(player_id, [])
        active = roster_now.get(player_id)
        if not active:
            continue
        rows.sort(key=lambda row: int(row["week"]))
        team = active["team"]
        game = team_game.get(team)
        if not game:
            continue
        latest = rows[-1] if rows else {}
        name = latest.get("player_display_name") or active.get("full_name") or latest.get("player_name")
        position = active.get("position") or latest.get("position")
        headshot = active.get("headshot_url") or latest.get("headshot_url") or ""
        stats_by_week = {int(row["week"]): row for row in rows}
        markets_out = {}
        for market in MARKETS:
            if position not in market["positions"]:
                continue
            logs = []
            volume = 0.0
            for row in rows:
                if not market["played"](row):
                    continue
                volume += market["volume"](row)
                logs.append({
                    "week": int(row["week"]),
                    "opp": show_team(row["opponent_team"]),
                    "home": site.get((int(row["week"]), row["team"]), False),
                    "value": market["value"](row),
                })
            snap_positions = market.get("snap_positions", market["positions"])
            if market.get("count_snaps") and position in snap_positions:
                # An offensive snap with no production in this stat is a played 0.
                # Receiving uses targets and yards. Rushing uses carries, for
                # running backs, quarterbacks, and receivers. A week already logged stays.
                seen = {entry["week"] for entry in logs}
                for week in range(1, current_week):
                    snap = snaps.get((player_id, week))
                    if not snap or week in seen:
                        continue
                    stat = stats_by_week.get(week, {})
                    logs.append({
                        "week": week,
                        "opp": show_team(snap["opp"]),
                        "home": site.get((week, snap["team"]), False),
                        "value": market["value"](stat),
                    })
                logs.sort(key=lambda entry: entry["week"])
            # Full sample stays on the board. One played game stays only when the
            # sportsbook has a line, so a new starter is not hidden.
            qualified = len(logs) >= market["min_games"] and volume >= market["min_volume"]
            if not qualified and not logs:
                continue
            # Home/away for past games is display-only; this week is what the card uses.
            values = [entry["value"] for entry in logs]
            average = sum(values) / len(values)
            group = position if market["group"] == "position" else "QB"
            table = matchup_tables.get((market["id"], group), {})
            opponent = game["opp"]
            per_game = table.get("per_game", {}).get(opponent)
            rank = table.get("ranks", {}).get(opponent)
            score = table.get("scores", {}).get(opponent, 50)
            teams = table.get("teams", 32)
            group_label = {"QB": "quarterbacks", "RB": "running backs", "WR": "wide receivers", "TE": "tight ends"}.get(group, "players")
            if per_game is None or rank is None:
                blurb = f"{NICKNAMES.get(opponent, opponent)} matchup is unavailable for this split."
            else:
                if rank <= 10:
                    place = f"{ordinal(rank)}-most"
                elif rank >= teams - 9:
                    place = f"{ordinal(teams - rank + 1)}-fewest"
                else:
                    place = f"{ordinal(rank)} of {teams}"
                blurb = (
                    f"{NICKNAMES.get(opponent, opponent)} allow {fmt_num(per_game)} "
                    f"{market['stat_label']} per game to {group_label}, "
                    f"{place} in the NFL."
                )
            markets_out[market["id"]] = {
                "line": nearest_half(average),
                "seasonAvg": round(average, 2),
                "qualified": qualified,
                "games": len(logs),
                "logs": logs,
                "matchup": {
                    "score": score,
                    "rank": rank,
                    "teams": teams,
                    "allowedPerGame": None if per_game is None else round(per_game, 2),
                    "leagueAvg": round(table.get("league", 0), 2),
                    "blurb": blurb,
                },
            }
        if not markets_out:
            continue
        players.append({
            "id": player_id,
            "name": name,
            "pos": position,
            "team": show_team(team),
            "club": NICKNAMES.get(team, ""),
            "opponent": show_team(game["opp"]),
            "home": game["home"],
            "headshot": headshot,
            "injury": outs.get(player_id),
            "markets": markets_out,
        })

    players.sort(key=lambda player: player["name"])
    payload = {
        "season": SEASON,
        "week": current_week,
        "throughWeek": current_week - 1,
        "slateStart": slate_days[0] if slate_days else "",
        "slateEnd": slate_days[-1] if slate_days else "",
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "nflverse weekly player stats, rosters, and schedules",
        "markets": [
            {"id": market["id"], "label": market["label"], "unit": market["unit"]}
            for market in MARKETS
        ],
        "players": players,
    }
    from attach_lines import attach

    attach(payload)
    for player in payload["players"]:
        player["markets"] = {
            market_id: market
            for market_id, market in player["markets"].items()
            if market.pop("qualified") or market.get("sportsbook")
        }
    payload["players"] = [player for player in payload["players"] if player["markets"]]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, separators=(",", ":")))
    kept = payload["players"]
    counts = {market["id"]: sum(1 for player in kept if market["id"] in player["markets"]) for market in MARKETS}
    print(f"week {current_week} players {len(kept)} teams {len({p['team'] for p in kept})} counts {counts}")
    print(f"wrote {OUT}")
    from build_slate import main as build_slate

    build_slate()


if __name__ == "__main__":
    main()
