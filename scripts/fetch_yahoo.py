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
    # Get the user's MLB leagues, pick the most recent
    j = yget("users;use_login=1/games;game_keys=mlb/leagues")
    # Walk the JSON to find the first league_key and team_key
    # Yahoo JSON is nested; do a small DFS to find keys
    def find_keys(obj):
        league_key, team_key = None, None
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k == "league_key":
                    league_key = v
                if k == "team_key":
                    team_key = v
                lk, tk = find_keys(v)
                league_key = league_key or lk
                team_key = team_key or tk
        elif isinstance(obj, list):
            for it in obj:
                lk, tk = find_keys(it)
                if lk and not league_key: league_key = lk
                if tk and not team_key: team_key = tk
        return league_key, team_key
    lk, tk = find_keys(j)
    if not lk or not tk:
        raise RuntimeError("Could not discover league_key/team_key from Yahoo response")
    return lk, tk

def save_json(path, obj):
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

    # Free agents pages (25 per page) — grab first 150 to start
    start = 0
    max_pages = 6
    for i in range(max_pages):
        fa = yget(f"league/{league_key}/players;status=FA;sort=AR;sort_type=lastweek;start={start};count=25")
        save_json(f"fa_p{start}.json", fa)
        # stop early if fewer than 25 returned
        # cheap check: string length; robust parsing later
        blob = json.dumps(fa)
        if blob.count('"player"') < 25:
            break
        start += 25

if __name__ == "__main__":
    fetch_all()
    print("Done.")
