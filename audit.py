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
    "QB": 1, "RB": 2, "WR": 3, "TE": 1, "FLEX": 1, "K": 1, "D/ST": 1,
}

ALL_TIME_FILE = "league_history_alltime.json"
SEASONS_DATA_FILE = "seasons_data.json"
GLOBAL_DATA_FILE = "global_dashboard_data.json"

HISTORICAL_CHAMPIONS_OVERRIDE = {}


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


def extract_manager_from_label(team_label):
  if not team_label or team_label == "TBD":
    return "Unknown"
  if "(" in team_label and ")" in team_label:
    return team_label.split("(")[-1].split(")")[0].strip()
  return team_label.strip()


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
      key=lambda x: x.points, reverse=True,
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


def compute_records_and_payouts(weeks_obj):
  weekly_team_bounties, weekly_player_bounties, weekly_anchors = [], [], []
  sorted_weeks = sorted([int(w) for w in weeks_obj.keys()])

  for w in sorted_weeks:
    matchups = weeks_obj[str(w)]
    if not matchups: continue
    high_match = max(matchups, key=lambda x: x["actual"])
    weekly_team_bounties.append({"week": w, "team": high_match["team"], "pts": high_match["actual"], "opp": high_match["opp"], "opp_pts": high_match["opp_actual"]})

    starters_this_week = []
    for team_entry in matchups:
      team_name = team_entry["team"]
      for p in team_entry["players"]:
        if p["started"]:
          starters_this_week.append({"week": w, "player": p["name"], "pos": p["pos"], "pts": p["pts"], "team": team_name})

    if starters_this_week:
      top_player = max(starters_this_week, key=lambda x: x["pts"])
      weekly_player_bounties.append(top_player)
      weekly_anchors.append(min(starters_this_week, key=lambda x: x["pts"]))

  team_totals = {}
  for w in sorted_weeks:
    for m in weeks_obj[str(w)]:
      team_totals[m["team"]] = team_totals.get(m["team"], 0.0) + m["actual"]

  season_pf_leader = max(team_totals.items(), key=lambda x: x[1]) if team_totals else ("None", 0.0)
  season_high_team_game = max(weekly_team_bounties, key=lambda x: x["pts"]) if weekly_team_bounties else None
  season_high_player_game = max(weekly_player_bounties, key=lambda x: x["pts"]) if weekly_player_bounties else None

  season_payout_leaders = {
      "pf_leader_team": season_pf_leader[0],
      "pf_leader_pts": round(season_pf_leader[1], 2),
      "high_game_team": season_high_team_game["team"] if season_high_team_game else "None",
      "high_game_pts": season_high_team_game["pts"] if season_high_team_game else 0.0,
      "high_game_week": season_high_team_game["week"] if season_high_team_game else 0,
      "high_player": season_high_player_game["player"] if season_high_player_game else "None",
      "high_player_pts": season_high_player_game["pts"] if season_high_player_game else 0.0,
      "high_player_pos": season_high_player_game["pos"] if season_high_player_game else "",
      "high_player_team": season_high_player_game["team"] if season_high_player_game else "None",
      "high_player_week": season_high_player_game["week"] if season_high_player_game else 0,
  }
  return weekly_team_bounties, weekly_player_bounties, weekly_anchors, season_payout_leaders


def sync_historical_h2h(current_year):
  all_time = load_history(ALL_TIME_FILE, {"champions": {}, "matchups": {}, "finishes": {}, "h2h_ingested_years": []})
  if "matchups" not in all_time: all_time["matchups"] = {}
  if "h2h_ingested_years" not in all_time: all_time["h2h_ingested_years"] = []

  for y in range(2023, current_year):
    if y in all_time["h2h_ingested_years"]: continue
    try:
      past_league = League(league_id=LEAGUE_ID, year=y, espn_s2=ESPN_S2, swid=SWID)
      for w in range(1, 19):
        try:
          b_scores = past_league.box_scores(week=w)
          if not b_scores: continue
          for match in b_scores:
            h_act, a_act = round(match.home_score, 2), round(match.away_score, 2)
            if h_act == 0 and a_act == 0: continue
            h_mgr, a_mgr = get_manager_name(match.home_team), get_manager_name(match.away_team)
            if h_mgr == "Manager" and a_mgr == "Manager": continue
            pair = sorted([h_mgr, a_mgr])
            m_id = f"{y}_W{w}_{pair[0]}_vs_{pair[1]}"
            if m_id not in all_time["matchups"]:
              all_time["matchups"][m_id] = {"year": y, "week": w, "m1": h_mgr, "t1": match.home_team.team_name, "s1": h_act, "m2": a_mgr, "t2": match.away_team.team_name, "s2": a_act}
        except Exception: break
      all_time["h2h_ingested_years"].append(y)
    except Exception as e: print(f"Could not backfill Season {y} H2H: {e}")
  save_history(ALL_TIME_FILE, all_time)
  return all_time


def sync_champions_and_finishes(current_year):
  all_time = load_history(ALL_TIME_FILE, {"champions": {}, "matchups": {}, "finishes": {}, "h2h_ingested_years": []})
  if "champions" not in all_time: all_time["champions"] = {}
  if "finishes" not in all_time: all_time["finishes"] = {}
  all_time["champions"].update(HISTORICAL_CHAMPIONS_OVERRIDE)

  for y in range(2023, current_year + 1):
    y_str = str(y)
    try:
      past_league = League(league_id=LEAGUE_ID, year=y, espn_s2=ESPN_S2, swid=SWID)
      
      # Robust extraction of standings prioritizing final_standing or regular standing
      ranked_teams = sorted(past_league.teams, key=lambda t: (getattr(t, "final_standing", 99) if getattr(t, "final_standing", 0) > 0 else 99, getattr(t, "standing", 99), -getattr(t, "points_for", 0)))
      season_finishes = {get_manager_name(t): (getattr(t, "final_standing", 0) if 0 < getattr(t, "final_standing", 0) <= len(past_league.teams) else idx) for idx, t in enumerate(ranked_teams, 1) if get_manager_name(t) != "Manager"}
      all_time["finishes"][y_str] = season_finishes

      gold_team = next((t for t in past_league.teams if getattr(t, "final_standing", 0) == 1), None)
      silver_team = next((t for t in past_league.teams if getattr(t, "final_standing", 0) == 2), None)
      bronze_team = next((t for t in past_league.teams if getattr(t, "final_standing", 0) == 3), None)
      remaining = [t for t in past_league.teams if t != gold_team and t != silver_team and t != bronze_team]
      remaining.sort(key=lambda t: (getattr(t, "final_standing", 99) if getattr(t, "final_standing", 0) > 0 else 99, getattr(t, "standing", 99), -getattr(t, "points_for", 0)))

      if not gold_team and ranked_teams: gold_team = ranked_teams[0]
      if not silver_team and len(ranked_teams) > 1: silver_team = ranked_teams[1]
      if not bronze_team and len(ranked_teams) > 2: bronze_team = ranked_teams[2]

      last_team = ranked_teams[-1] if ranked_teams else None

      def format_champ_entry(t):
        if not t: return "TBD"
        mgr = get_manager_name(t)
        return f"{t.team_name} ({mgr})" if mgr != "Manager" else t.team_name

      all_time["champions"][y_str] = {
          "gold": format_champ_entry(gold_team),
          "silver": format_champ_entry(silver_team),
          "bronze": format_champ_entry(bronze_team),
          "last": format_champ_entry(last_team)
      }
    except Exception as e: print(f"Historical query for Season {y} skipped: {e}")

  save_history(ALL_TIME_FILE, all_time)
  return all_time["champions"], all_time.get("finishes", {})


def compute_all_time_leaderboard(champions, current_managers, finishes_data):
  mgr_stats = {m: {"manager": m, "is_current": True, "gold": 0, "silver": 0, "bronze": 0, "last": 0, "total_podiums": 0, "most_recent": "No Podiums Yet", "finishes": []} for m in current_managers}
  for y in sorted([int(y) for y in champions.keys()]):
    p = champions[str(y)]
    for m, cat in [(extract_manager_from_label(p.get("gold")), "gold"), (extract_manager_from_label(p.get("silver")), "silver"), (extract_manager_from_label(p.get("bronze")), "bronze"), (extract_manager_from_label(p.get("last")), "last")]:
      if m != "Unknown":
        if m not in mgr_stats: mgr_stats[m] = {"manager": m, "is_current": False, "gold": 0, "silver": 0, "bronze": 0, "last": 0, "total_podiums": 0, "most_recent": "No Podiums Yet", "finishes": []}
        if cat != "last":
          mgr_stats[m][cat] += 1
          mgr_stats[m]["total_podiums"] += 1
          mgr_stats[m]["most_recent"] = f"🥇 Gold ({y})" if cat == "gold" else (f"🥈 Silver ({y})" if cat == "silver" else f"🥉 Bronze ({y})")
        else:
          mgr_stats[m]["last"] += 1
          mgr_stats[m]["most_recent"] = f"💩 League Bitch ({y})"

  for y_str, y_finishes in finishes_data.items():
    for m, place in y_finishes.items():
      if m not in mgr_stats: mgr_stats[m] = {"manager": m, "is_current": False, "gold": 0, "silver": 0, "bronze": 0, "last": 0, "total_podiums": 0, "most_recent": "No Podiums Yet", "finishes": []}
      mgr_stats[m]["finishes"].append(place)

  for m, data in mgr_stats.items():
    if data["finishes"]:
      data["avg_finish"] = round(sum(data["finishes"]) / len(data["finishes"]), 1)
      data["seasons_count"] = len(data["finishes"])
      data["avg_sort"] = data["avg_finish"]
    else:
      data["avg_finish"], data["seasons_count"], data["avg_sort"] = None, 0, 999.0

  return sorted(mgr_stats.values(), key=lambda x: (-x["gold"], -x["silver"], -x["bronze"], -x["total_podiums"], x["avg_sort"], x["last"], x["manager"]))


def main():
  global WEEK
  print(f"Connecting to ESPN Fantasy API for League {LEAGUE_ID} (Season {YEAR})...")
  league = League(league_id=LEAGUE_ID, year=YEAR, espn_s2=ESPN_S2, swid=SWID)

  if not WEEK:
    WEEK = max(1, getattr(league, "current_week", 1) - 1)
    print(f"Auto-detected completed week: Week {WEEK}")

  current_managers = sorted(list(set(get_manager_name(t) for t in league.teams if get_manager_name(t) != "Manager")))

  history_file = f"league_history_{YEAR}.json"
  history = load_history(history_file, {"year": YEAR, "weeks": {}})

  for w in range(1, WEEK + 1):
    w_str = str(w)
    box_scores = league.box_scores(week=w)
    if not box_scores: continue

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

  all_time_data = sync_historical_h2h(YEAR)
  champions, finishes_data = sync_champions_and_finishes(YEAR)
  leaderboard = compute_all_time_leaderboard(champions, current_managers, finishes_data)
  
  prior_year_str = str(YEAR - 1)
  reigning = champions.get(prior_year_str, {})
  reigning["year"] = prior_year_str

  seasons_data = load_history(SEASONS_DATA_FILE, {})
  seasons_data[str(YEAR)] = history.get("weeks", {})
  save_history(SEASONS_DATA_FILE, seasons_data)

  season_payouts_all = {}
  weekly_bounties_all = {}
  weekly_player_bounties_all = {}
  weekly_anchors_all = {}
  for yr_key, weeks_dict in seasons_data.items():
    tb, pb, an, sp = compute_records_and_payouts(weeks_dict)
    season_payouts_all[yr_key] = sp
    weekly_bounties_all[yr_key] = tb
    weekly_player_bounties_all[yr_key] = pb
    weekly_anchors_all[yr_key] = an

  # Compute All-Time League Records across all seasons
  all_time_high_team = {"team": "None", "pts": 0.0, "week": 0, "year": 0}
  all_time_high_player = {"player": "None", "team": "None", "pts": 0.0, "week": 0, "year": 0, "pos": ""}
  all_time_high_season_pf = {"team": "None", "pts": 0.0, "year": 0}
  all_time_high_pa = {"team": "None", "pa": 0.0, "opp": "None", "week": 0, "year": 0}

  for yr_key, weeks_dict in seasons_data.items():
    yr_int = int(yr_key)
    team_season_pf = {}
    for w_str, matchups in weeks_dict.items():
      w_int = int(w_str)
      for m in matchups:
        # Track team points against
        if m["opp_actual"] > all_time_high_pa["pa"]:
          all_time_high_pa = {"team": m["team"], "pa": m["opp_actual"], "opp": m["opp"], "week": w_int, "year": yr_int}

        team_season_pf[m["team"]] = team_season_pf.get(m["team"], 0.0) + m["actual"]
        if m["actual"] > all_time_high_team["pts"]:
          all_time_high_team = {"team": m["team"], "pts": m["actual"], "week": w_int, "year": yr_int}

        for p in m.get("players", []):
          if p["started"] and p["pts"] > all_time_high_player["pts"]:
            all_time_high_player = {"player": p["name"], "team": m["team"], "pts": p["pts"], "week": w_int, "year": yr_int, "pos": p["pos"]}

    for tm, pf_val in team_season_pf.items():
      if pf_val > all_time_high_season_pf["pts"]:
        all_time_high_season_pf = {"team": tm, "pts": round(pf_val, 2), "year": yr_int}

  global_bundle = {
      "seasons_data": seasons_data,
      "champions": champions,
      "leaderboard": leaderboard,
      "reigning": reigning,
      "current_managers": current_managers,
      "matchups": all_time_data.get("matchups", {}),
      "season_payouts": season_payouts_all,
      "weekly_bounties": weekly_bounties_all,
      "weekly_player_bounties": weekly_player_bounties_all,
      "weekly_anchors": weekly_anchors_all,
      "all_time_records": {
          "high_team_game": all_time_high_team,
          "high_player_game": all_time_high_player,
          "high_season_pf": all_time_high_season_pf,
          "high_points_against": all_time_high_pa
      }
  }
  save_history(GLOBAL_DATA_FILE, global_bundle)
  print("Data engine execution complete. All-time records & weekly lists compiled.")


if __name__ == "__main__":
  main()
