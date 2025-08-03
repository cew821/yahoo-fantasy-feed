import os, json, time, pathlib
from datetime import datetime, timedelta, timezone
from dateutil import tz
import requests

BASE = "https://fantasysports.yahooapis.com/fantasy/v2"

CLIENT_ID = os.environ["YAHOO_CLIENT_ID"]
CLIENT_SECRET = os.environ["YAHOO_CLIENT_SECRET"]
REFRESH_TOKEN = os.environ["YAHOO_REFRESH_TOKEN"]

OUTDIR = pathlib.Path("data")
OUTDIR.mkdir(exist_ok=True)

def get_access_token():
    r = requests.post(
        "https://api.login.yahoo.com/oauth2/get_token",
        auth=(CLIENT_ID, CLIENT_SECRET),
        data={
            "grant_type": "refresh_token",
            "refresh_token": REFRESH_TOKEN,
            "redirect_uri": "https://oauth.pstmn.io/v1/browser-callback",
        },
        timeout=30,
    )
    if r.status_code != 200:
        # Print error details to help diagnose (no secrets revealed)
        print("Yahoo token endpoint error:", r.status_code, r.text)
        r.raise_for_status()
    return r.json()["access_token"]


def yget(path, params=None):
    params = params or {}
    params["format"] = "json"
    headers = {"Authorization": f"Bearer {get_access_token()}"}
    r = requests.get(f"{BASE}/{path}", params=params, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()

def et_now():
    return datetime.now(tz.gettz("US/Eastern"))

def roster_date_for_tomorrow_et():
    return (et_now() + timedelta(days=1)).strftime("%Y-%m-%d")

def discover_league_and_team():
    """
    Correct discovery: ask for TEAMS (not leagues). This endpoint returns team_key(s).
    We then derive league_key from team_key.
    """
    j = yget("users;use_login=1/games;game_keys=mlb/teams")
    # Walk the nested JSON to find the first team_key
    def find_team_key(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k == "team_key":
                    return v
                found = find_team_key(v)
                if found:
                    return found
        elif isinstance(obj, list):
            for it in obj:
                found = find_team_key(it)
                if found:
                    return found
        return None

    team_key = find_team_key(j)
    if not team_key:
        raise RuntimeError("Could not find team_key in users→games→teams response")

    # league_key is the part before ".t.#"
    if ".t." not in team_key:
        raise RuntimeError(f"team_key looks unexpected: {team_key}")
    league_key = team_key.split(".t.")[0]
    return league_key, team_key


def save_json(path, obj):
    p = OUTDIR / path
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, indent=2))
    tmp.replace(p)

def save_pretty_json(path, obj):
    p = OUTDIR / path
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, indent=2))
    tmp.replace(p)

def fetch_all():
    league_key, team_key = discover_league_and_team()
    save_json("keys.json", {"league_key": league_key, "team_key": team_key})

    # Roster for tomorrow (Daily–Tomorrow league)
    date_str = roster_date_for_tomorrow_et()
    roster = yget(f"team/{team_key}/roster;date={date_str}/players")
    save_json(f"roster_{date_str}.json", roster)
    save_json("roster_latest.json", roster)

       # Free agents pages (25 per page) — grab up to 300, stop early if <25 returned
    start = 0
    max_pages = 12
    for _ in range(max_pages):
        fa = yget(
            f"league/{league_key}/players;status=FA;sort=AR;sort_type=lastweek;start={start};count=25"
        )
        save_json(f"fa_p{start}.json", fa)

        # Robust stop: read the count of players returned
        # Yahoo returns nested structures; count may live at fantasy_content->league->players->count
        def find_count(obj):
            if isinstance(obj, dict):
                # common pattern
                if "count" in obj and isinstance(obj["count"], int):
                    return obj["count"]
                for v in obj.values():
                    c = find_count(v)
                    if c is not None:
                        return c
            elif isinstance(obj, list):
                for it in obj:
                    c = find_count(it)
                    if c is not None:
                        return c
            return None

        cnt = find_count(fa)
        if not cnt or cnt < 25:
            break
        start += 25


if __name__ == "__main__":
    fetch_all()
    print("Done.")
