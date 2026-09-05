import json
import os
import statistics
from espn_api.football import League

LEAGUE_ID = int(os.environ["LEAGUE_ID"])
SWID = os.environ["SWID"]
ESPN_S2 = os.environ["ESPN_S2"]

YEAR_ENV = os.environ.get("YEAR", "").strip()
WEEK_ENV = os.environ.get("WEEK", "").strip()

YEAR = int(YEAR_ENV) if YEAR_ENV else 2026
WEEK = int(WEEK_ENV) if WEEK_ENV else None

ROSTER_SLOTS = {
    "QB": 1,
    "RB": 2,
    "WR": 3,
    "TE": 1,
    "FLEX": 1,
    "K": 1,
    "D/ST": 1,
}

ALL_TIME_FILE = "league_history_alltime.json"
SEASONS_DATA_FILE = "seasons_data.json"


def get_manager_name(team):
  if hasattr(team, "owners") and team.owners:
    owner = team.owners[0]
    if isinstance(owner, dict):
      first = owner.get("firstName", "")
      last = owner.get("lastName", "")
      full = f"{first} {last}".strip()
      return full if full else owner.get("displayName", "Manager")
    return str(owner)
  return getattr(team, "owner", "Manager")


def audit_roster(lineup, slots, actual_score):
  qbs = sorted([p for p in lineup if p.position == "QB"], key=lambda x: x.points, reverse=True)
  rbs = sorted([p for p in lineup if p.position == "RB"], key=lambda x: x.points, reverse=True)
  wrs = sorted([p for p in lineup if p.position == "WR"], key=lambda x: x.points, reverse=True)
  tes = sorted([p for p in lineup if p.position == "TE"], key=lambda x: x.points, reverse=True)
  ks = sorted([p for p in lineup if p.position == "K"], key=lambda x: x.points, reverse=True)
  dsts = sorted([p for p in lineup if p.position in ["D/ST", "DEF"]], key=lambda x: x.points, reverse=True)

  optimal_ids = set()
  for p in qbs[: slots.get("QB", 1)]: optimal_ids.add(p.playerId)
  for p in rbs[: slots.get("RB", 2)]: optimal_ids.add(p.playerId)
  for p in wrs[: slots.get("WR", 3)]: optimal_ids.add(p.playerId)
  for p in tes[: slots.get("TE", 1)]: optimal_ids.add(p.playerId)

  flex_pool = sorted(
      rbs[slots.get("RB", 2) :] + wrs[slots.get("WR", 3) :] + tes[slots.get("TE", 1) :],
      key=lambda x: x.points,
      reverse=True,
  )
  for p in flex_pool[: slots.get("FLEX", 1)]: optimal_ids.add(p.playerId)
  for p in ks[: slots.get("K", 1)]: optimal_ids.add(p.playerId)
  for p in dsts[: slots.get("D/ST", 1)]: optimal_ids.add(p.playerId)

  players_data = []
  for p in lineup:
    started = p.slot_position not in ["BE", "IR"]
    is_optimal = p.playerId in optimal_ids
    pts = round(p.points, 2)
    proj = round(getattr(p, "projected_points", 0.0), 2)
    pos_clean = "D/ST" if p.position in ["D/ST", "DEF"] else p.position

    if started and is_optimal: audit = "Smart Start"
    elif not started and not is_optimal: audit = "Correct Bench"
    elif not started and is_optimal: audit = "Costly Bench"
    else: audit = "Starter Bust"

    players_data.append({"name": p.name, "pos": pos_clean, "started": started, "audit": audit, "pts": pts, "proj": proj})

  calc_optimal = round(sum(p.points for p in lineup if p.playerId in optimal_ids), 2)
  return players_data, max(actual_score, calc_optimal)


def load_history(filepath, default_data):
  if os.path.exists(filepath):
    with open(filepath, "r") as f:
      return json.load(f)
  return default_data


def save_history(filepath, data):
  with open(filepath, "w") as f:
    json.dump(data, f, indent=2)


def main():
  global WEEK
  print(f"Connecting to ESPN Fantasy API for League {LEAGUE_ID} (Season {YEAR})...")
  league = League(league_id=LEAGUE_ID, year=YEAR, espn_s2=ESPN_S2, swid=SWID)

  if not WEEK:
    WEEK = max(1, getattr(league, "current_week", 1) - 1)
    print(f"Auto-detected completed week: Week {WEEK}")

  history_file = f"league_history_{YEAR}.json"
  history = load_history(history_file, {"year": YEAR, "weeks": {}})

  for w in range(1, WEEK + 1):
    w_str = str(w)
    box_scores = league.box_scores(week=w)
    if not box_scores:
      continue

    w_teams = []
    for match in box_scores:
      h_act, a_act = round(match.home_score, 2), round(match.away_score, 2)
      h_proj = round(sum(p.projected_points for p in match.home_lineup if p.slot_position not in ["BE", "IR"]), 2)
      a_proj = round(sum(p.projected_points for p in match.away_lineup if p.slot_position not in ["BE", "IR"]), 2)

      h_players, h_opt = audit_roster(match.home_lineup, ROSTER_SLOTS, h_act)
      a_players, a_opt = audit_roster(match.away_lineup, ROSTER_SLOTS, a_act)

      h_mgr, a_mgr = get_manager_name(match.home_team), get_manager_name(match.away_team)
      home_label = f"{match.home_team.team_name} ({h_mgr})" if h_mgr != "Manager" else match.home_team.team_name
      away_label = f"{match.away_team.team_name} ({a_mgr})" if a_mgr != "Manager" else match.away_team.team_name

      w_teams.append({
          "team": home_label, "manager": h_mgr, "opp": away_label, "opp_manager": a_mgr,
          "actual": h_act, "proj": h_proj, "diff": round(h_act - h_proj, 2),
          "opp_actual": a_act, "opp_proj": a_proj, "optimal": h_opt,
          "result": "W" if h_act > a_act else ("L" if h_act < a_act else "T"),
          "coach_eff": round((h_act / h_opt) * 100, 1) if h_opt > 0 else 100.0,
          "players": h_players,
      })
      w_teams.append({
          "team": away_label, "manager": a_mgr, "opp": home_label, "opp_manager": h_mgr,
          "actual": a_act, "proj": a_proj, "diff": round(a_act - a_proj, 2),
          "opp_actual": h_act, "opp_proj": h_proj, "optimal": a_opt,
          "result": "W" if a_act > h_act else ("L" if a_act < h_act else "T"),
          "coach_eff": round((a_act / a_opt) * 100, 1) if a_opt > 0 else 100.0,
          "players": a_players,
      })

    all_scores = [t["actual"] for t in w_teams]
    total_opps = len(w_teams) - 1
    for t in w_teams:
      t["all_play_w"] = sum(1 for s in all_scores if t["actual"] > s)
      t["all_play_l"] = sum(1 for s in all_scores if t["actual"] < s)
      t["luck_delta"] = round((1.0 if t["result"] == "W" else 0.0) - (t["all_play_w"] / total_opps), 3)

    history["weeks"][w_str] = w_teams

  save_history(history_file, history)

  seasons_data = load_history(SEASONS_DATA_FILE, {})
  seasons_data[str(YEAR)] = history.get("weeks", {})
  save_history(SEASONS_DATA_FILE, seasons_data)
  print("Data engine execution complete. seasons_data.json updated.")


if __name__ == "__main__":
  main()
