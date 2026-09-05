import json
import os
import statistics
from espn_api.football import League

# Credentials pulled from GitHub Secrets
LEAGUE_ID = int(os.environ["LEAGUE_ID"])
SWID = os.environ["SWID"]
ESPN_S2 = os.environ["ESPN_S2"]

YEAR_ENV = os.environ.get("YEAR", "").strip()
WEEK_ENV = os.environ.get("WEEK", "").strip()

YEAR = int(YEAR_ENV) if YEAR_ENV else 2026
WEEK = int(WEEK_ENV) if WEEK_ENV else None

# League Roster Setup (1 QB, 2 RB, 3 WR, 1 TE, 1 FLEX, 1 K, 1 D/ST)
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


def compute_records_and_payouts(history):
  weekly_team_bounties, weekly_player_bounties, weekly_anchors = [], [], []
  position_records = {pos: {"pts": -99.0, "player": "None", "team": "None", "week": 0} for pos in ["QB", "RB", "WR", "TE", "K", "D/ST"]}
  sorted_weeks = sorted([int(w) for w in history["weeks"].keys()])

  for w in sorted_weeks:
    matchups = history["weeks"][str(w)]
    if not matchups: continue
    high_match = max(matchups, key=lambda x: x["actual"])
    weekly_team_bounties.append({"week": w, "team": high_match["team"], "pts": high_match["actual"], "opp": high_match["opp"], "opp_pts": high_match["opp_actual"]})

    starters_this_week = []
    for team_entry in matchups:
      team_name = team_entry["team"]
      for p in team_entry["players"]:
        if p["started"]:
          starters_this_week.append({"week": w, "player": p["name"], "pos": p["pos"], "pts": p["pts"], "team": team_name})
          if p["pos"] in position_records and p["pts"] > position_records[p["pos"]]["pts"]:
            position_records[p["pos"]] = {"pts": p["pts"], "player": p["name"], "team": team_name, "week": w}

    if starters_this_week:
      weekly_player_bounties.append(max(starters_this_week, key=lambda x: x["pts"]))
      weekly_anchors.append(min(starters_this_week, key=lambda x: x["pts"]))

  season_high_team_game = max(weekly_team_bounties, key=lambda x: x["pts"]) if weekly_team_bounties else None
  team_totals = {}
  for w in sorted_weeks:
    for m in history["weeks"][str(w)]:
      team_totals[m["team"]] = team_totals.get(m["team"], 0.0) + m["actual"]

  season_pf_leader = max(team_totals.items(), key=lambda x: x[1]) if team_totals else ("None", 0.0)
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
  return weekly_team_bounties, weekly_player_bounties, weekly_anchors, position_records, season_payout_leaders


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


def sync_champions_and_finishes(current_year):
  all_time = load_history(ALL_TIME_FILE, {"champions": {}, "matchups": {}, "finishes": {}, "h2h_ingested_years": []})
  if "champions" not in all_time: all_time["champions"] = {}
  if "finishes" not in all_time: all_time["finishes"] = {}
  all_time["champions"].update(HISTORICAL_CHAMPIONS_OVERRIDE)

  for y in range(2023, current_year + 1):
    y_str = str(y)
    try:
      past_league = League(league_id=LEAGUE_ID, year=y, espn_s2=ESPN_S2, swid=SWID)
      curr_wk = getattr(past_league, "current_week", 1)
      if y == current_year:
        standings = [getattr(t, "final_standing", 0) for t in past_league.teams]
        if curr_wk <= 17 or not any(s == 1 for s in standings):
          all_time["champions"].pop(y_str, None)
          all_time["finishes"].pop(y_str, None)
          continue

      ranked_teams = sorted(past_league.teams, key=lambda t: (getattr(t, "final_standing", 99) if getattr(t, "final_standing", 0) > 0 else 99, getattr(t, "standing", 99), -getattr(t, "points_for", 0)))
      season_finishes = {get_manager_name(t): (getattr(t, "final_standing", 0) if 0 < getattr(t, "final_standing", 0) <= len(past_league.teams) else idx) for idx, t in enumerate(ranked_teams, 1) if get_manager_name(t) != "Manager"}
      all_time["finishes"][y_str] = season_finishes

      if all_time["champions"].get(y_str, {}).get("gold") and all_time["champions"][y_str].get("gold") != "TBD": continue

      gold_team = next((t for t in past_league.teams if getattr(t, "final_standing", 0) == 1), None)
      silver_team = next((t for t in past_league.teams if getattr(t, "final_standing", 0) == 2), None)
      bronze_team = next((t for t in past_league.teams if getattr(t, "final_standing", 0) == 3), None)
      remaining = [t for t in past_league.teams if t != gold_team and t != silver_team]
      remaining.sort(key=lambda t: (getattr(t, "final_standing", 99) if getattr(t, "final_standing", 0) > 0 else 99, getattr(t, "standing", 99), -getattr(t, "points_for", 0)))

      if not gold_team and past_league.teams: gold_team = remaining.pop(0)
      if not silver_team and remaining: silver_team = remaining.pop(0)
      if not bronze_team and remaining: bronze_team = remaining.pop(0)

      valid_standings = [t for t in past_league.teams if getattr(t, "final_standing", 0) > 0]
      last_team = max(valid_standings, key=lambda t: t.final_standing) if valid_standings else max(past_league.teams, key=lambda t: (getattr(t, "standing", 0), -getattr(t, "points_for", 0)))

      def format_champ_entry(t):
        if not t: return "TBD"
        mgr = get_manager_name(t)
        return f"{t.team_name} ({mgr})" if mgr != "Manager" else t.team_name

      all_time["champions"][y_str] = {"gold": format_champ_entry(gold_team), "silver": format_champ_entry(silver_team), "bronze": format_champ_entry(bronze_team), "last": format_champ_entry(last_team)}
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


def get_reigning_badges(champions, current_year):
  prior_year_str = str(current_year - 1)
  prior_podium = champions.get(prior_year_str, {})
  return {"year": prior_year_str, "gold": prior_podium.get("gold", ""), "silver": prior_podium.get("silver", ""), "bronze": prior_podium.get("bronze", ""), "last": prior_podium.get("last", "")}


def render_team_badge(team_label, reigning):
  if not reigning: return team_label
  yr_short = reigning.get("year", "25")[-2:]
  def matches(target, label):
    if not target or target == "TBD": return False
    t_clean, l_clean = target.lower().strip(), label.lower().strip()
    if t_clean in l_clean or l_clean in t_clean: return True
    if "(" in target and ")" in target:
      mgr = target.split("(")[-1].split(")")[0].strip().lower()
      if mgr and mgr != "manager" and mgr in l_clean: return True
    return False

  medals = ""
  if matches(reigning.get("gold"), team_label): medals += f' <span class="badge badge-champ">🥇 \'{yr_short} Champ</span>'
  elif matches(reigning.get("silver"), team_label): medals += f' <span class="badge badge-silver">🥈 \'{yr_short} Runner-Up</span>'
  elif matches(reigning.get("bronze"), team_label): medals += f' <span class="badge badge-bronze">🥉 \'{yr_short} 3rd Pl</span>'
  elif matches(reigning.get("last"), team_label): medals += f' <span class="badge badge-bitch">💩 \'{yr_short} League Bitch</span>'
  return f"{team_label}{medals}"


def update_and_compute_h2h(history, current_year):
  all_time = load_history(ALL_TIME_FILE, {"champions": {}, "matchups": {}, "finishes": {}, "h2h_ingested_years": []})
  if "matchups" not in all_time: all_time["matchups"] = {}

  for w_str, matchups in history["weeks"].items():
    w = int(w_str)
    for m in matchups:
      mgr, opp_mgr = m.get("manager", "Unknown"), m.get("opp_manager", "Unknown")
      if mgr == "Unknown" or opp_mgr == "Unknown": continue
      pair = sorted([mgr, opp_mgr])
      match_id = f"{current_year}_W{w}_{pair[0]}_vs_{pair[1]}"
      if match_id not in all_time["matchups"]:
        all_time["matchups"][match_id] = {"year": current_year, "week": w, "m1": mgr, "t1": m["team"], "s1": m["actual"], "m2": opp_mgr, "t2": m["opp"], "s2": m["opp_actual"]}

  save_history(ALL_TIME_FILE, all_time)
  rivalries, managers_set, season_log = {}, set(), []

  for m_id, g in all_time["matchups"].items():
    m1, m2, s1, s2, y, w = g["m1"], g["m2"], g["s1"], g["s2"], g["year"], g["week"]
    managers_set.add(m1); managers_set.add(m2)
    pair_key = tuple(sorted([m1, m2]))
    if pair_key not in rivalries:
      rivalries[pair_key] = {"m1": pair_key[0], "m2": pair_key[1], "m1_wins": 0, "m2_wins": 0, "ties": 0, "m1_pf": 0.0, "m2_pf": 0.0, "season_m1_wins": 0, "season_m2_wins": 0, "season_ties": 0, "last_meet": None}
    r = rivalries[pair_key]
    r["last_meet"] = {"year": y, "week": w, "m1": m1, "s1": s1, "m2": m2, "s2": s2}

    if s1 > s2:
      if m1 == r["m1"]: r["m1_wins"] += 1
      else: r["m2_wins"] += 1
      if y == current_year:
        if m1 == r["m1"]: r["season_m1_wins"] += 1
        else: r["season_m2_wins"] += 1
    elif s2 > s1:
      if m2 == r["m2"]: r["m2_wins"] += 1
      else: r["m1_wins"] += 1
      if y == current_year:
        if m2 == r["m2"]: r["season_m2_wins"] += 1
        else: r["season_m1_wins"] += 1
    else:
      r["ties"] += 1
      if y == current_year: r["season_ties"] += 1

    if m1 == r["m1"]: r["m1_pf"] += s1; r["m2_pf"] += s2
    else: r["m1_pf"] += s2; r["m2_pf"] += s1

    if y == current_year:
      season_log.append({"week": w, "m1": m1, "t1": g["t1"], "s1": s1, "m2": m2, "t2": g["t2"], "s2": s2, "margin": round(abs(s1 - s2), 2), "winner": m1 if s1 > s2 else (m2 if s2 > s1 else "Tie"), "winner_team": g["t1"] if s1 >= s2 else g["t2"], "winner_score": max(s1, s2), "loser_team": g["t2"] if s1 >= s2 else g["t1"], "loser_score": min(s1, s2)})

  season_log.sort(key=lambda x: (x["week"], -x["margin"]))
  return rivalries, sorted(list(managers_set)), season_log


def compute_trends(history):
  team_trends = {}
  weeks_sorted = sorted([int(w) for w in history["weeks"].keys()])
  for w in weeks_sorted:
    for entry in history["weeks"][str(w)]:
      team = entry["team"]
      if team not in team_trends:
        team_trends[team] = {"team": team, "actual_w": 0, "actual_l": 0, "all_play_w": 0, "all_play_l": 0, "pf": 0.0, "pa": 0.0, "eff_history": [], "pine_tax": 0.0, "opp_over_proj_count": 0, "curr_opp_surge_streak": 0, "cardiac_w": 0, "cardiac_l": 0, "scores": []}
      s = team_trends[team]
      act, opp_act = entry["actual"], entry["opp_actual"]
      s["pf"] += act; s["pa"] += opp_act; s["scores"].append(act)
      if entry["result"] == "W": s["actual_w"] += 1
      elif entry["result"] == "L": s["actual_l"] += 1
      if abs(act - opp_act) <= 5.00:
        if entry["result"] == "W": s["cardiac_w"] += 1
        elif entry["result"] == "L": s["cardiac_l"] += 1
      s["all_play_w"] += entry["all_play_w"]; s["all_play_l"] += entry["all_play_l"]
      s["eff_history"].append(entry["coach_eff"]); s["pine_tax"] += round(entry["optimal"] - act, 2)
      if round(opp_act - entry.get("opp_proj", opp_act), 2) > 0:
        s["opp_over_proj_count"] += 1; s["curr_opp_surge_streak"] += 1
      else: s["curr_opp_surge_streak"] = 0

  total_weeks = len(weeks_sorted)
  for team, s in team_trends.items():
    tot_ap = s["all_play_w"] + s["all_play_l"]
    tot_act = s["actual_w"] + s["actual_l"]
    s["all_play_pct"] = (s["all_play_w"] / tot_ap) if tot_ap > 0 else 0.0
    s["luck_delta"] = round(((s["actual_w"] / tot_act) if tot_act > 0 else 0.0) - s["all_play_pct"], 3)
    s["avg_eff"] = round(sum(s["eff_history"]) / len(s["eff_history"]), 1) if s["eff_history"] else 100.0
    s["avg_pa"] = round(s["pa"] / total_weeks, 2) if total_weeks else 0.0
    s["pine_tax"] = round(s["pine_tax"], 2)
    pf_sq, pa_sq = s["pf"] ** 2, s["pa"] ** 2
    denom = pf_sq + pa_sq
    s["pyth_wins"] = round((pf_sq / denom) * tot_act, 1) if denom > 0 else 0.0
    s["pyth_delta"] = round(s["actual_w"] - s["pyth_wins"], 1)
    if len(s["scores"]) > 1:
      sd = round(statistics.stdev(s["scores"]), 1)
      s["volatility_sd"] = sd
      s["volatility_tag"] = "Boom/Bust" if sd >= 18.0 else ("Steady Floor" if sd <= 12.0 else "Balanced")
    else:
      s["volatility_sd"], s["volatility_tag"] = 0.0, "Baseline"
  return team_trends, total_weeks


def generate_html_report(week_num, current_week_data, trends_data, total_weeks, weekly_team_bounties, weekly_player_bounties, weekly_anchors, position_records, season_payout_leaders, champions, leaderboard, reigning, rivalries, managers_list, current_managers, season_log):
  seasons_data = load_history(SEASONS_DATA_FILE, {})
  history_file = f"league_history_{YEAR}.json"
  curr_history = load_history(history_file, {"year": YEAR, "weeks": {}})
  seasons_data[str(YEAR)] = curr_history.get("weeks", {})
  save_history(SEASONS_DATA_FILE, seasons_data)

  serialized_seasons = json.dumps(seasons_data)
  serialized_reigning = json.dumps(reigning)
  active_meta = json.dumps({"year": str(YEAR), "week": str(week_num)})

  sorted_week = sorted(current_week_data, key=lambda x: (x["all_play_w"], x["actual"]), reverse=True)
  sorted_trends = sorted(trends_data.values(), key=lambda x: (x["all_play_w"], x["pf"]), reverse=True)

  buzzsaw = min(current_week_data, key=lambda x: x["luck_delta"], default={"team": "None", "actual": 0.0, "opp": "None", "opp_actual": 0.0, "all_play_w": 0, "all_play_l": 0, "luck_delta": 0.0})
  horseshoe = max(current_week_data, key=lambda x: x["luck_delta"], default={"team": "None", "actual": 0.0, "opp": "None", "opp_actual": 0.0, "all_play_w": 0, "all_play_l": 0, "luck_delta": 0.0})
  tactician = max(current_week_data, key=lambda x: x["coach_eff"], default={"team": "None", "coach_eff": 100.0, "actual": 0.0, "optimal": 0.0})

  all_blunders = [{"team": t["team"], **p} for t in current_week_data for p in t["players"] if p["audit"] == "Costly Bench"]
  all_blunders.sort(key=lambda x: x["pts"], reverse=True)

  curr_bounty = next((b for b in weekly_team_bounties if b["week"] == week_num), None) or (weekly_team_bounties[-1] if weekly_team_bounties else None)
  curr_anchor = next((a for a in weekly_anchors if a["week"] == week_num), None) or (weekly_anchors[-1] if weekly_anchors else None)
  blowout_game = max(season_log, key=lambda x: x["margin"]) if season_log else None
  heartbreaker_game = min(season_log, key=lambda x: x["margin"]) if season_log else None

  html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0" />
  <title>The Deflaters // League Engine</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;600;700;800&display=swap" rel="stylesheet">
  <style>
    :root {{
      --bg: #070a13; --surface: #111827; --card: #151f32; --border: #24324d;
      --text: #f1f5f9; --muted: #94a3b8; --dim: #475569; --accent: #38bdf8;
      --green: #10b981; --green-bg: rgba(16, 185, 129, 0.12);
      --red: #f43f5e; --red-bg: rgba(244, 63, 94, 0.12);
      --amber: #f59e0b; --amber-bg: rgba(245, 158, 11, 0.12);
      --purple: #a855f7; --purple-bg: rgba(168, 85, 247, 0.12);
      --gold: #fbbf24; --gold-bg: rgba(251, 191, 36, 0.15);
      --silver: #cbd5e1; --silver-bg: rgba(203, 213, 225, 0.15);
      --bronze: #d97706; --bronze-bg: rgba(217, 119, 6, 0.15);
      --th-bg: #0d1424;
    }}
    body.light-mode {{
      --bg: #f8fafc; --surface: #ffffff; --card: #ffffff; --border: #e2e8f0;
      --text: #0f172a; --muted: #64748b; --dim: #94a3b8; --accent: #0284c7;
      --green: #059669; --green-bg: rgba(5, 150, 105, 0.12);
      --red: #e11d48; --red-bg: rgba(225, 29, 72, 0.12);
      --amber: #d97706; --amber-bg: rgba(217, 119, 6, 0.12);
      --purple: #7c3aed; --purple-bg: rgba(124, 58, 237, 0.12);
      --gold: #b45309; --gold-bg: rgba(245, 158, 11, 0.15);
      --silver: #475569; --silver-bg: rgba(100, 116, 139, 0.15);
      --bronze: #9a3412; --bronze-bg: rgba(194, 65, 12, 0.15);
      --th-bg: #f1f5f9;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    html, body {{
      max-width: 100%; overflow-x: hidden; background-color: var(--bg); color: var(--text);
      font-family: 'Plus Jakarta Sans', -apple-system, sans-serif; line-height: 1.5; transition: background-color 0.2s, color 0.2s;
    }}
    body {{ padding: 16px 12px; }}
    .wrapper {{ max-width: 1080px; width: 100%; margin: 0 auto; display: flex; flex-direction: column; gap: 20px; }}
    
    .header {{
      background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
      border: 1px solid var(--border); border-radius: 18px; padding: 20px;
      display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 16px;
    }}
    .header h1 {{ font-size: 22px; font-weight: 800; color: #fff; }}
    .header .subtitle {{ color: var(--accent); font-weight: 700; text-transform: uppercase; font-size: 11px; letter-spacing: 1.5px; margin-bottom: 2px; }}
    .header-controls {{ display: flex; flex-direction: column; gap: 8px; align-items: flex-end; }}
    
    /* PILL NAVIGATION STYLES */
    .pill-group {{ display: flex; align-items: center; gap: 6px; flex-wrap: wrap; justify-content: flex-end; }}
    .pill-label {{ font-size: 10px; font-weight: 800; text-transform: uppercase; color: var(--muted); margin-right: 4px; }}
    .pill {{
      background: var(--surface); border: 1px solid var(--border); color: var(--muted);
      padding: 4px 10px; border-radius: 8px; font-size: 11px; font-weight: 700; cursor: pointer; transition: all 0.2s;
    }}
    .pill:hover {{ border-color: var(--accent); color: var(--text); }}
    .pill.active {{ background: var(--accent); color: #070a13; border-color: var(--accent); font-weight: 800; }}

    .theme-toggle-btn {{
      background: rgba(255, 255, 255, 0.1); border: 1px solid rgba(255, 255, 255, 0.2);
      color: #fff; padding: 5px 12px; border-radius: 16px; font-size: 11px; font-weight: 700;
      cursor: pointer; display: inline-flex; align-items: center; gap: 6px; transition: all 0.2s; margin-top: 4px;
    }}
    .theme-toggle-btn:hover {{ background: rgba(255, 255, 255, 0.2); }}

    .awards-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; }}
    .award-card {{ background: var(--card); border: 1px solid var(--border); border-radius: 14px; padding: 16px; display: flex; flex-direction: column; justify-content: space-between; box-shadow: 0 2px 4px rgba(0,0,0,0.04); }}
    .award-card.red {{ border-left: 4px solid var(--red); }}
    .award-card.green {{ border-left: 4px solid var(--green); }}
    .award-card.blue {{ border-left: 4px solid var(--accent); }}
    .award-card.gold {{ border-left: 4px solid var(--gold); }}
    .award-card.zinc {{ border-left: 4px solid var(--dim); }}
    .award-tag {{ font-size: 11px; font-weight: 800; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 6px; }}
    .award-title {{ font-size: 16px; font-weight: 800; color: var(--text); margin-bottom: 4px; word-break: break-word; }}
    .award-desc {{ font-size: 13px; color: var(--muted); line-height: 1.4; }}

    .tab-bar {{ display: flex; flex-wrap: wrap; gap: 6px; background: var(--surface); padding: 6px; border-radius: 14px; border: 1px solid var(--border); }}
    .tab-btn {{
      flex: 1 1 auto; min-width: 120px; padding: 10px 14px; background: transparent; border: 1px solid transparent;
      border-radius: 10px; color: var(--muted); font-family: inherit; font-size: 12px; font-weight: 700;
      cursor: pointer; text-align: center; transition: all 0.2s;
    }}
    .tab-btn.active {{ background: var(--card); color: var(--text); border-color: var(--border); box-shadow: 0 2px 8px rgba(0,0,0,0.08); }}

    .table-container {{ background: var(--card); border: 1px solid var(--border); border-radius: 16px; width: 100%; overflow: hidden; box-shadow: 0 2px 4px rgba(0,0,0,0.04); }}
    .responsive-table {{ width: 100%; border-collapse: collapse; text-align: left; font-size: 13px; }}
    .responsive-table th {{ background: var(--th-bg); color: var(--muted); font-weight: 700; font-size: 11px; text-transform: uppercase; padding: 12px 14px; border-bottom: 1px solid var(--border); }}
    .responsive-table th .sub-th {{ display: block; font-size: 9px; color: var(--dim); font-weight: normal; text-transform: none; margin-top: 2px; }}
    .responsive-table td {{ padding: 12px 14px; border-bottom: 1px solid var(--border); vertical-align: middle; }}
    .responsive-table tr:last-child td {{ border-bottom: none; }}
    .responsive-table tr:hover td {{ background: rgba(125,125,125,0.03); }}

    @media (max-width: 768px) {{
      .responsive-table thead {{ display: none; }}
      .responsive-table, .responsive-table tbody, .responsive-table tr, .responsive-table td {{ display: block; width: 100%; }}
      .responsive-table tr {{ background: var(--card); border-bottom: 1px solid var(--border); padding: 12px 14px; }}
      .responsive-table tr:last-child {{ border-bottom: none; }}
      .responsive-table td {{ display: flex; justify-content: space-between; align-items: center; padding: 6px 0; border-bottom: 1px solid rgba(125,125,125,0.08); font-size: 13px; }}
      .responsive-table td:last-child {{ border-bottom: none; }}
      .responsive-table td::before {{ content: attr(data-label); font-weight: 700; font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px; margin-right: 12px; text-align: left; flex-shrink: 0; }}
      .responsive-table td.team-cell {{ display: flex; justify-content: flex-start; align-items: center; font-size: 15px; font-weight: 800; color: var(--text); padding-bottom: 8px; margin-bottom: 4px; border-bottom: 1px solid var(--border); }}
      .responsive-table td.team-cell::before {{ display: none; }}
      .rank-num {{ display: inline-flex; align-items: center; justify-content: center; width: 22px; height: 22px; background: rgba(125,125,125,0.12); border-radius: 50%; font-size: 11px; font-weight: 800; color: var(--accent); margin-right: 8px; flex-shrink: 0; }}
    }}

    .badge {{ display: inline-flex; align-items: center; padding: 3px 8px; border-radius: 6px; font-size: 11px; font-weight: 800; gap: 4px; flex-wrap: wrap; }}
    .badge-win {{ background: var(--green-bg); color: var(--green); }}
    .badge-loss {{ background: var(--red-bg); color: var(--red); }}
    .badge-lucky {{ background: var(--green-bg); color: var(--green); }}
    .badge-unlucky {{ background: var(--red-bg); color: var(--red); }}
    .badge-neutral {{ background: rgba(125,125,125,0.08); color: var(--muted); }}
    .badge-gold {{ background: var(--gold-bg); color: var(--gold); border: 1px solid rgba(251, 191, 36, 0.4); }}
    .badge-champ {{ background: var(--gold-bg); color: var(--gold); border: 1px solid rgba(251, 191, 36, 0.4); font-size: 10px; padding: 2px 6px; }}
    .badge-silver {{ background: var(--silver-bg); color: var(--silver); border: 1px solid rgba(203, 213, 225, 0.4); font-size: 10px; padding: 2px 6px; }}
    .badge-bronze {{ background: var(--bronze-bg); color: var(--bronze); border: 1px solid rgba(217, 119, 6, 0.4); font-size: 10px; padding: 2px 6px; }}
    .badge-bitch {{ background: rgba(239, 68, 68, 0.15); color: #ef4444; border: 1px solid rgba(239, 68, 68, 0.4); font-size: 10px; padding: 2px 6px; }}

    .podium-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 14px; padding: 16px; }}
    .podium-card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 14px; padding: 16px; }}
    .podium-year {{ font-size: 17px; font-weight: 800; color: var(--text); margin-bottom: 10px; border-bottom: 1px solid var(--border); padding-bottom: 6px; }}
    .podium-row {{ display: flex; align-items: center; justify-content: space-between; padding: 6px 0; font-size: 13px; }}
    
    .records-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px; margin-bottom: 20px; }}
    .record-card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 12px; text-align: center; }}
    .record-pos {{ font-size: 11px; font-weight: 800; color: var(--accent); text-transform: uppercase; margin-bottom: 2px; }}
    .record-pts {{ font-size: 20px; font-weight: 800; color: var(--text); }}
    .record-holder {{ font-size: 11px; color: var(--muted); margin-top: 4px; word-break: break-word; }}

    .glossary-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 14px; padding: 16px; }}
    .glossary-card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 14px; padding: 16px; }}
    .glossary-title {{ font-size: 15px; font-weight: 800; color: var(--text); margin-bottom: 6px; display: flex; align-items: center; gap: 6px; }}
    .glossary-desc {{ font-size: 13px; color: var(--muted); line-height: 1.5; }}

    .filter-header {{ padding: 14px 16px; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; }}
    .filter-control {{ display: flex; align-items: center; gap: 8px; width: 100%; max-width: 260px; }}
    .select-dropdown {{
      flex: 1; width: 100%; background: var(--surface); color: var(--text); border: 1px solid var(--border);
      padding: 8px 12px; border-radius: 8px; font-size: 13px; font-weight: 700; cursor: pointer; outline: none;
    }}
    .h2h-scope-bar {{ display: inline-flex; background: var(--surface); padding: 3px; border-radius: 10px; border: 1px solid var(--border); }}
    .scope-btn {{ background: transparent; border: 1px solid transparent; color: var(--muted); padding: 6px 12px; border-radius: 8px; font-size: 12px; font-weight: 700; cursor: pointer; transition: all 0.2s; }}
    .scope-btn.active {{ background: var(--card); color: var(--text); border-color: var(--border); box-shadow: 0 1px 4px rgba(0,0,0,0.15); }}
  </style>
</head>
<body>

<script id="seasons-data-payload" type="application/json">
{serialized_seasons}
</script>

<script id="reigning-badges-data" type="application/json">
{serialized_reigning}
</script>

<script id="active-meta-data" type="application/json">
{active_meta}
</script>

<div class="wrapper">
  <div class="header">
    <div>
      <div class="subtitle">The Deflaters Analytics Lab</div>
      <h1 id="headerSummaryTitle">WEEK {week_num} SUMMARY</h1>
    </div>
    <div class="header-controls">
      <div class="pill-group" id="seasonPillsContainer">
        <span class="pill-label">Season:</span>
      </div>
      <div class="pill-group" id="weekPillsContainer">
        <span class="pill-label">Week:</span>
      </div>
      <button id="theme-toggle" class="theme-toggle-btn" onclick="toggleTheme()">☀️ Light Mode</button>
    </div>
  </div>

  <!-- AWARDS & SUPERLATIVES GRID (TOP 5) -->
  <div class="awards-grid" id="dynamicAwardsGrid">
    <div class="award-card gold">
      <div>
        <div class="award-tag" style="color: var(--gold);">💰 Week {curr_bounty['week'] if curr_bounty else week_num} Team Bounty</div>
        <div class="award-title">{render_team_badge(curr_bounty['team'] if curr_bounty else 'None', reigning)}</div>
        <div class="award-desc">Paced the entire league with <b>{curr_bounty['pts']:.2f} pts</b> to take down the weekly cash payout!</div>
      </div>
      <div style="margin-top: 8px;"><span class="badge badge-gold">Weekly Bounty Winner</span></div>
    </div>

    <div class="award-card red">
      <div>
        <div class="award-tag" style="color: var(--red);">💀 The Buzzsaw Victim</div>
        <div class="award-title">{render_team_badge(buzzsaw['team'], reigning)}</div>
        <div class="award-desc">Dropped {buzzsaw['actual']:.2f} pts ({buzzsaw['all_play_w']}–{buzzsaw['all_play_l']} All-Play), but took an L to {buzzsaw['opp']} ({buzzsaw['opp_actual']:.2f} pts).</div>
      </div>
      <div style="margin-top: 8px;"><span class="badge badge-unlucky">Luck Δ: {buzzsaw['luck_delta']:+.3f}</span></div>
    </div>

    <div class="award-card green">
      <div>
        <div class="award-tag" style="color: var(--green);">🍀 Grand Theft Victory</div>
        <div class="award-title">{render_team_badge(horseshoe['team'], reigning)}</div>
        <div class="award-desc">Squeaked by with {horseshoe['actual']:.2f} pts ({horseshoe['all_play_w']}–{horseshoe['all_play_l']} All-Play) thanks to opponent meltdown.</div>
      </div>
      <div style="margin-top: 8px;"><span class="badge badge-lucky">Luck Δ: {horseshoe['luck_delta']:+.3f}</span></div>
    </div>

    <div class="award-card blue">
      <div>
        <div class="award-tag" style="color: var(--accent);">🧠 Master Tactician</div>
        <div class="award-title">{render_team_badge(tactician['team'], reigning)}</div>
        <div class="award-desc">Optimal starting execution of <b>{tactician['coach_eff']}%</b> ({tactician['actual']:.2f} of {tactician['optimal']:.2f} optimal pts).</div>
      </div>
      <div style="margin-top: 8px;"><span class="badge badge-neutral">Lineup Mastery</span></div>
    </div>

    <div class="award-card zinc">
      <div>
        <div class="award-tag" style="color: var(--dim);">⚓ The Anchor Award (Lead Weight)</div>
        <div class="award-title">{curr_anchor['player'] if curr_anchor else 'None'} ({curr_anchor['pos'] if curr_anchor else ''})</div>
        <div class="award-desc">Hung a league-low <b>{curr_anchor['pts']:.2f} pts</b> in the starting lineup for {curr_anchor['team'] if curr_anchor else 'None'}.</div>
      </div>
      <div style="margin-top: 8px;"><span class="badge badge-neutral">Lowest Starter of Wk</span></div>
    </div>
  </div>

  <div class="tab-bar">
    <button class="tab-btn active" onclick="switchTab('week')" id="tabBtnWeek">📅 Week {week_num} Summary</button>
    <button class="tab-btn" onclick="switchTab('season')" id="tabBtnSeason">📈 Season Trends</button>
    <button class="tab-btn" onclick="switchTab('h2h')">⚔️ Head-to-Head</button>
    <button class="tab-btn" onclick="switchTab('payouts')">💰 Payouts & Records</button>
    <button class="tab-btn" onclick="switchTab('halloffame')">🏆 Hall of Champions</button>
    <button class="tab-btn" onclick="switchTab('blunders')">🤡 Bench Blunders</button>
    <button class="tab-btn" onclick="switchTab('glossary')">📖 Stat Decoders</button>
  </div>

  <!-- TAB 1: WEEK AUDIT -->
  <div id="view-week" class="table-container">
    <table class="responsive-table">
      <thead>
        <tr>
          <th>Rank / Team</th>
          <th>Result</th>
          <th>Score<span class="sub-th">(vs Proj)</span></th>
          <th>Opponent<span class="sub-th">(Score)</span></th>
          <th>All-Play<span class="sub-th">Record</span></th>
          <th>Luck Δ<span class="sub-th">Schedule Break</span></th>
          <th>Coaching Eff<span class="sub-th">Optimal Pts %</span></th>
        </tr>
      </thead>
      <tbody id="weekTableBody">"""

  for idx, t in enumerate(sorted_week, 1):
    delta_class = "badge-lucky" if t["luck_delta"] > 0 else ("badge-unlucky" if t["luck_delta"] < 0 else "badge-neutral")
    res_badge = "badge-win" if t["result"] == "W" else "badge-loss"
    decorated_team = render_team_badge(t["team"], reigning)
    html += f"""
        <tr>
          <td class="team-cell"><span class="rank-num">#{idx}</span> {decorated_team}</td>
          <td data-label="Result"><span class="badge {res_badge}">{t['result']}</span></td>
          <td data-label="Score"><b>{t['actual']:.2f}</b> <span style="font-size: 11px; color: var(--dim);">({t['diff']:+.2f})</span></td>
          <td data-label="Opponent">{t['opp']} <span style="color: var(--muted); font-size: 11px;">({t['opp_actual']:.2f})</span></td>
          <td data-label="All-Play"><b>{t['all_play_w']}</b>–{t['all_play_l']}</td>
          <td data-label="Luck Δ"><span class="badge {delta_class}">{t['luck_delta']:+.3f}</span></td>
          <td data-label="Coaching Eff"><b>{t['coach_eff']}%</b></td>
        </tr>"""

  html += f"""
      </tbody>
    </table>
  </div>

  <!-- TAB 2: SEASON TRENDS -->
  <div id="view-season" class="table-container" style="display: none;">
    <table class="responsive-table">
      <thead>
        <tr>
          <th>Rank / Team</th>
          <th>Actual W-L</th>
          <th>Pyth Exp Wins<span class="sub-th">True Record (Δ)</span></th>
          <th>All-Play<span class="sub-th">Record (%)</span></th>
          <th>Season Luck Δ</th>
          <th>Volatility (σ)<span class="sub-th">Consistency Archetype</span></th>
          <th>Cardiac Rec<span class="sub-th">Games ≤ 5 pts</span></th>
          <th>Pine Tax<span class="sub-th">Pts Lost</span></th>
          <th>Opp Surges<span class="sub-th">Faced (Streak)</span></th>
          <th>Avg Opp PA</th>
        </tr>
      </thead>
      <tbody id="seasonTableBody">"""

  for idx, s in enumerate(sorted_trends, 1):
    c_delta_class = "badge-lucky" if s["luck_delta"] > 0 else ("badge-unlucky" if s["luck_delta"] < 0 else "badge-neutral")
    decorated_team = render_team_badge(s["team"], reigning)
    streak_badge = f"<b>{s['curr_opp_surge_streak']} st!</b>" if s["curr_opp_surge_streak"] >= 2 else f"{s['curr_opp_surge_streak']} st"
    pyth_diff_str = f"+{s['pyth_delta']:.1f}" if s["pyth_delta"] > 0 else f"{s['pyth_delta']:.1f}"
    pyth_color = "var(--green)" if s["pyth_delta"] > 0.5 else ("var(--red)" if s["pyth_delta"] < -0.5 else "var(--muted)")

    html += f"""
        <tr>
          <td class="team-cell"><span class="rank-num">#{idx}</span> {decorated_team}</td>
          <td data-label="Actual W-L"><b>{s['actual_w']}–{s['actual_l']}</b></td>
          <td data-label="Pyth Wins"><b>{s['pyth_wins']:.1f}</b> <span style="font-size: 11px; color: {pyth_color};">({pyth_diff_str})</span></td>
          <td data-label="All-Play">{s['all_play_w']}–{s['all_play_l']} <span style="font-size: 11px; color: var(--dim);">({s['all_play_pct']:.3f})</span></td>
          <td data-label="Season Luck Δ"><span class="badge {c_delta_class}">{s['luck_delta']:+.3f}</span></td>
          <td data-label="Volatility">±{s['volatility_sd']:.1f} <span class="badge badge-neutral" style="font-size: 10px; padding: 1px 6px;">{s['volatility_tag']}</span></td>
          <td data-label="Cardiac Rec"><b>{s['cardiac_w']}–{s['cardiac_l']}</b></td>
          <td data-label="Pine Tax" style="color: var(--amber); font-weight: 700;">{s['pine_tax']:.2f} pts</td>
          <td data-label="Opp Surges">{s['opp_over_proj_count']}/{total_weeks} wks ({streak_badge})</td>
          <td data-label="Avg Opp PA"><b>{s['avg_pa']:.2f}</b></td>
        </tr>"""

  html += f"""
      </tbody>
    </table>
  </div>

  <!-- TAB 3: HEAD-TO-HEAD -->
  <div id="view-h2h" style="display: none; display: flex; flex-direction: column; gap: 16px;">
    <div class="table-container">
      <div class="filter-header">
        <div style="display: flex; align-items: center; gap: 12px; flex-wrap: wrap;">
          <div style="font-size: 14px; font-weight: 800; color: var(--text);">⚔️ Head-to-Head Rivalry Records (2023–Present)</div>
          <div class="h2h-scope-bar">
            <button id="scopeCurrentBtn" class="scope-btn active" onclick="setH2HScope('current')">👥 Current Managers</button>
            <button id="scopeAllBtn" class="scope-btn" onclick="setH2HScope('all')">🌐 All-Time (Inc. Former)</button>
          </div>
        </div>
        <div class="filter-control">
          <select id="mgrFilter" class="select-dropdown" onchange="applyH2HFilters()">
            <option value="ALL">Show All Rivalries</option>"""

  for mgr in managers_list:
    is_cur = mgr in current_managers
    tag = " (Former)" if not is_cur else ""
    html += f"""<option value="{mgr}" data-is-current="{'true' if is_cur else 'false'}">{mgr}{tag}</option>"""

  html += """
          </select>
        </div>
      </div>
      <table class="responsive-table" id="rivalryTable">
        <thead>
          <tr>
            <th>Rivalry Matchup</th>
            <th>All-Time Series</th>
            <th>Season Series</th>
            <th>Total Points (PF vs PA)</th>
            <th>Last Meeting</th>
          </tr>
        </thead>
        <tbody>"""

  for pair_key, r in rivalries.items():
    m1, m2 = r["m1"], r["m2"]
    is_both_current = m1 in current_managers and m2 in current_managers
    last = r["last_meet"]
    last_str = f"{last['year']} Wk {last['week']}: {last['m1']} ({last['s1']:.2f}) vs {last['m2']} ({last['s2']:.2f})" if last else "N/A"
    html += f"""
          <tr class="rivalry-row" data-m1="{m1}" data-m2="{m2}" data-current="{'true' if is_both_current else 'false'}">
            <td class="team-cell">{m1} vs {m2}</td>
            <td data-label="All-Time Series"><b>{r['m1_wins']}–{r['m2_wins']}</b></td>
            <td data-label="Season Series">{r['season_m1_wins']}–{r['season_m2_wins']}</td>
            <td data-label="PF vs PA">{r['m1_pf']:.2f} – {r['m2_pf']:.2f}</td>
            <td data-label="Last Meeting" style="color: var(--muted); font-size: 11px;">{last_str}</td>
          </tr>"""

  html += f"""
        </tbody>
      </table>
    </div>
    
    <div class="table-container">
      <div style="padding: 14px 16px; font-weight: 800; border-bottom: 1px solid var(--border); color: var(--text); font-size: 14px;">
        📅 Season Completed Matchup Log
      </div>
      <table class="responsive-table">
        <thead>
          <tr><th>Week</th><th>Winner</th><th>Score</th><th>Loser</th><th>Margin</th></tr>
        </thead>
        <tbody>"""

  for g in season_log:
    html += f"""
          <tr>
            <td class="team-cell" style="color: var(--accent);">Week {g['week']} Matchup</td>
            <td data-label="Winner" style="font-weight: 700; color: var(--text);">{g['winner_team']}</td>
            <td data-label="Score" style="font-weight: 700; color: var(--green);">{g['winner_score']:.2f} – {g['loser_score']:.2f}</td>
            <td data-label="Loser" style="color: var(--muted);">{g['loser_team']}</td>
            <td data-label="Margin" style="font-weight: 700; color: var(--accent);">+{g['margin']:.2f} pts</td>
          </tr>"""

  html += f"""
        </tbody>
      </table>
    </div>
  </div>

  <!-- TAB 4: PAYOUTS -->
  <div id="view-payouts" style="display: none; display: flex; flex-direction: column; gap: 16px;">
    <div style="font-size: 15px; font-weight: 800; color: var(--text);">🏆 Season High Point Cash Bounties</div>
    <div class="awards-grid">
      <div class="award-card gold">
        <div>
          <div class="award-tag" style="color: var(--gold);">👑 Season Points Leader (Total PF)</div>
          <div class="award-title">{render_team_badge(season_payout_leaders['pf_leader_team'], reigning)}</div>
          <div class="award-desc">Pacing the entire season with <b>{season_payout_leaders['pf_leader_pts']:.2f} Total PF</b>!</div>
        </div>
      </div>
      <div class="award-card blue">
        <div>
          <div class="award-tag" style="color: var(--accent);">⚡ Single-Game Team Record</div>
          <div class="award-title">{render_team_badge(season_payout_leaders['high_game_team'], reigning)}</div>
          <div class="award-desc">Hung <b>{season_payout_leaders['high_game_pts']:.2f} pts</b> in Week {season_payout_leaders['high_game_week']}.</div>
        </div>
      </div>
      <div class="award-card green">
        <div>
          <div class="award-tag" style="color: var(--green);">🌟 Single-Game Starter Record</div>
          <div class="award-title">{season_payout_leaders['high_player']} ({season_payout_leaders['high_player_pos']})</div>
          <div class="award-desc">Erupted for <b>{season_payout_leaders['high_player_pts']:.2f} pts</b> in Week {season_payout_leaders['high_player_week']}.</div>
        </div>
      </div>
    </div>
  </div>

  <!-- TAB 5: HALL OF FAME -->
  <div id="view-halloffame" style="display: none; display: flex; flex-direction: column; gap: 20px;">
    <div class="table-container">
      <div style="padding: 14px 16px; font-weight: 800; border-bottom: 1px solid var(--border); color: var(--text); font-size: 15px;">
        🏛️ All-Time Franchise Trophy & Placement Ledger (2023–Present)
      </div>
      <table class="responsive-table">
        <thead>
          <tr><th>Manager / Franchise</th><th>🥇 1st</th><th>🥈 2nd</th><th>🥉 3rd</th><th>💩 Bitch</th><th>Podiums</th><th>Avg Finish</th></tr>
        </thead>
        <tbody>"""

  for row in leaderboard:
    status_badge = ' <span class="badge badge-neutral" style="font-size: 9px; padding: 1px 5px;">Active</span>' if row["is_current"] else ' <span class="badge badge-neutral" style="font-size: 9px; padding: 1px 5px; opacity: 0.6;">Alumni</span>'
    avg_str = f"<b>{row['avg_finish']:.1f}</b>" if row["avg_finish"] is not None else "—"
    html += f"""
          <tr>
            <td class="team-cell"><b>{row['manager']}</b>{status_badge}<div style="font-size: 11px; color: var(--muted); font-weight: normal;">Most Recent: {row['most_recent']}</div></td>
            <td><b>{row['gold']}</b></td><td><b>{row['silver']}</b></td><td><b>{row['bronze']}</b></td>
            <td style="color: #ef4444; font-weight: 700;">{row['last']}</td>
            <td><span class="badge badge-neutral"><b>{row['total_podiums']}</b></span></td>
            <td>{avg_str}</td>
          </tr>"""

  html += """
        </tbody>
      </table>
    </div>
  </div>

  <!-- TAB 6: BENCH BLUNDERS -->
  <div id="view-blunders" class="table-container" style="display: none;">
    <table class="responsive-table">
      <thead><tr><th>Team</th><th>Player Benched</th><th>Pos</th><th>Points Left</th><th>Projection</th></tr></thead>
      <tbody id="blundersTableBody">"""

  for idx, b in enumerate(all_blunders[:10], 1):
    html += f"""
        <tr>
          <td class="team-cell"><span class="rank-num">#{idx}</span> {render_team_badge(b['team'], reigning)}</td>
          <td style="color: var(--text); font-weight: 600;">{b['name']}</td>
          <td><span class="badge badge-neutral">{b['pos']}</span></td>
          <td style="font-weight: 800; color: var(--amber);">{b['pts']:.2f} pts</td>
          <td style="color: var(--muted);">{b['proj']:.2f} pts</td>
        </tr>"""

  html += """
      </tbody>
    </table>
  </div>

  <!-- TAB 7: GLOSSARY -->
  <div id="view-glossary" class="table-container" style="display: none;">
    <div style="padding: 16px; font-weight: 800; border-bottom: 1px solid var(--border); color: var(--text); font-size: 15px;">
      📖 The Deflaters Analytics Handbook
    </div>
    <div class="glossary-grid">
      <div class="glossary-card">
        <div class="glossary-title">🫀 The Cardiac Index</div>
        <div class="glossary-desc">Tracks team record in tight games decided by <b>5.00 points or fewer</b>.</div>
      </div>
      <div class="glossary-card">
        <div class="glossary-title">📊 Scoring Volatility</div>
        <div class="glossary-desc">Standard deviation of weekly totals. Highlights <b>Steady Floors</b> vs. <b>Boom/Bust</b> squads.</div>
      </div>
    </div>
  </div>

</div>

<script>
  var seasonsData = JSON.parse(document.getElementById('seasons-data-payload').textContent || '{}');
  var reigningBadges = JSON.parse(document.getElementById('reigning-badges-data').textContent || '{}');
  var activeMeta = JSON.parse(document.getElementById('active-meta-data').textContent || '{"year": "2026", "week": "1"}');

  var currentYear = activeMeta.year;
  var currentWeek = activeMeta.week;
  var h2hScope = 'current';

  function initApp() {
    var savedTheme = localStorage.getItem('ff_theme');
    if (savedTheme === 'light') {
      document.body.classList.add('light-mode');
      updateThemeBtn(true);
    }
    setH2HScope('current');
    setupSeasonPills();
  }

  function setupSeasonPills() {
    var container = document.getElementById('seasonPillsContainer');
    if (!container) return;
    
    // Clear existing pills except label
    while (container.childNodes.length > 1) {
      container.removeChild(container.lastChild);
    }

    var years = Object.keys(seasonsData).sort(function(a, b) { return b - a; });
    if (years.length === 0) {
      years = [currentYear];
      seasonsData[currentYear] = {};
    }

    if (!seasonsData[currentYear]) {
      currentYear = years[0];
    }

    years.forEach(function(yr) {
      var btn = document.createElement('button');
      btn.className = 'pill' + (yr === currentYear ? ' active' : '');
      btn.textContent = yr;
      btn.onclick = function() { selectSeason(yr); };
      container.appendChild(btn);
    });

    setupWeekPills(currentYear);
  }

  function setupWeekPills(yr) {
    var container = document.getElementById('weekPillsContainer');
    if (!container) return;

    while (container.childNodes.length > 1) {
      container.removeChild(container.lastChild);
    }

    var weeksObj = seasonsData[yr] || {};
    var weeks = Object.keys(weeksObj).map(Number).sort(function(a, b) { return a - b; });

    if (weeks.length === 0) {
      weeks = [1];
    }

    var targetWk = weeks.includes(parseInt(currentWeek)) ? parseInt(currentWeek) : weeks[weeks.length - 1];

    weeks.forEach(function(w) {
      var btn = document.createElement('button');
      btn.className = 'pill' + (w === targetWk ? ' active' : '');
      btn.textContent = 'Wk ' + w;
      btn.onclick = function() { selectWeek(w); };
      container.appendChild(btn);
    });

    currentWeek = targetWk.toString();
    renderSelectedWeekData();
  }

  function selectSeason(yr) {
    currentYear = yr;
    var sPills = document.querySelectorAll('#seasonPillsContainer .pill');
    sPills.forEach(function(p) {
      p.classList.toggle('active', p.textContent === yr);
    });
    setupWeekPills(yr);
  }

  function selectWeek(wk) {
    currentWeek = wk.toString();
    var wPills = document.querySelectorAll('#weekPillsContainer .pill');
    wPills.forEach(function(p) {
      p.classList.toggle('active', p.textContent === 'Wk ' + wk);
    });
    renderSelectedWeekData();
  }

  function renderSelectedWeekData() {
    var yrData = seasonsData[currentYear] || {};
    var wkData = yrData[currentWeek] || [];

    var summaryTitleEl = document.getElementById('headerSummaryTitle');
    if (summaryTitleEl) summaryTitleEl.innerText = currentYear + ' WEEK ' + currentWeek + ' SUMMARY';
    
    var btnWeekEl = document.getElementById('tabBtnWeek');
    if (btnWeekEl) btnWeekEl.innerText = '📅 Week ' + currentWeek + ' Summary';
    
    var btnSeasonEl = document.getElementById('tabBtnSeason');
    if (btnSeasonEl) btnSeasonEl.innerText = '📈 ' + currentYear + ' Season Trends';

    var sorted = wkData.slice().sort(function(a, b) {
      if (b.all_play_w !== a.all_play_w) return b.all_play_w - a.all_play_w;
      return b.actual - a.actual;
    });

    var tbody = document.getElementById('weekTableBody');
    if (tbody) {
      tbody.innerHTML = '';
      sorted.forEach(function(t, idx) {
        var deltaClass = t.luck_delta > 0 ? 'badge-lucky' : (t.luck_delta < 0 ? 'badge-unlucky' : 'badge-neutral');
        var resBadge = t.result === 'W' ? 'badge-win' : 'badge-loss';
        var decoratedTeam = renderBadge(t.team);
        var tr = document.createElement('tr');
        tr.innerHTML = 
          '<td class="team-cell"><span class="rank-num">#' + (idx + 1) + '</span> ' + decoratedTeam + '</td>' +
          '<td data-label="Result"><span class="badge ' + resBadge + '">' + t.result + '</span></td>' +
          '<td data-label="Score"><b>' + t.actual.toFixed(2) + '</b> <span style="font-size: 11px; color: var(--dim);">(' + (t.diff > 0 ? '+' : '') + t.diff.toFixed(2) + ')</span></td>' +
          '<td data-label="Opponent">' + t.opp + ' <span style="color: var(--muted); font-size: 11px;">(' + t.opp_actual.toFixed(2) + ')</span></td>' +
          '<td data-label="All-Play"><b>' + t.all_play_w + '</b>–' + t.all_play_l + '</td>' +
          '<td data-label="Luck Δ"><span class="badge ' + deltaClass + '">' + (t.luck_delta > 0 ? '+' : '') + t.luck_delta.toFixed(3) + '</span></td>' +
          '<td data-label="Coaching Eff"><b>' + t.coach_eff.toFixed(1) + '%</b></td>';
        tbody.appendChild(tr);
      });
    }

    renderDynamicAwards(sorted, wkData);
    renderBenchBlunders(wkData);
    renderSeasonTrends(yrData);
  }

  function renderBadge(label) {
    if (!reigningBadges) return label;
    var yrShort = (reigningBadges.year || '25').slice(-2);
    function matches(target) {
      if (!target || target === 'TBD') return false;
      var tClean = target.toLowerCase().trim();
      var lClean = label.toLowerCase().trim();
      if (tClean.indexOf(lClean) !== -1 || lClean.indexOf(tClean) !== -1) return true;
      if (target.indexOf('(') !== -1 && target.indexOf(')') !== -1) {
        var mgr = target.split('(').pop().split(')')[0].trim().toLowerCase();
        if (mgr && mgr !== 'manager' && lClean.indexOf(mgr) !== -1) return true;
      }
      return false;
    }
    if (matches(reigningBadges.gold)) return label + ' <span class="badge badge-champ">🥇 \'' + yrShort + ' Champ</span>';
    if (matches(reigningBadges.silver)) return label + ' <span class="badge badge-silver">🥈 \'' + yrShort + ' Runner-Up</span>';
    if (matches(reigningBadges.bronze)) return label + ' <span class="badge badge-bronze">🥉 \'' + yrShort + ' 3rd Pl</span>';
    if (matches(reigningBadges.last)) return label + ' <span class="badge badge-bitch">💩 \'' + yrShort + ' League Bitch</span>';
    return label;
  }

  function renderDynamicAwards(sortedWkData, wkData) {
    var awardsContainer = document.getElementById('dynamicAwardsGrid');
    if (!awardsContainer) return;
    if (!sortedWkData || sortedWkData.length === 0) {
      awardsContainer.innerHTML = '<div style="color: var(--muted); padding: 12px;">No box scores available for this week.</div>';
      return;
    }

    var bounty = sortedWkData[0];
    var buzzsaw = sortedWkData.slice().sort(function(a, b) { return a.luck_delta - b.luck_delta; })[0];
    var horseshoe = sortedWkData.slice().sort(function(a, b) { return b.luck_delta - a.luck_delta; })[0];
    var tactician = sortedWkData.slice().sort(function(a, b) { return b.coach_eff - a.coach_eff; })[0];

    var allStarters = [];
    wkData.forEach(function(t) {
      if (t.players) {
        t.players.forEach(function(p) {
          if (p.started) allStarters.push({ player: p.name, pos: p.pos, pts: p.pts, team: t.team });
        });
      }
    });
    var anchor = allStarters.length > 0 ? allStarters.sort(function(a, b) { return a.pts - b.pts; })[0] : null;

    awardsContainer.innerHTML = 
      '<div class="award-card gold">' +
        '<div><div class="award-tag" style="color: var(--gold);">💰 Week ' + currentWeek + ' Team Bounty</div>' +
        '<div class="award-title">' + renderBadge(bounty.team) + '</div>' +
        '<div class="award-desc">Paced the entire league with <b>' + bounty.actual.toFixed(2) + ' pts</b> to take down the weekly cash payout!</div></div>' +
        '<div style="margin-top: 8px;"><span class="badge badge-gold">Weekly Bounty Winner</span></div>' +
      '</div>' +
      '<div class="award-card red">' +
        '<div><div class="award-tag" style="color: var(--red);">💀 The Buzzsaw Victim</div>' +
        '<div class="award-title">' + renderBadge(buzzsaw.team) + '</div>' +
        '<div class="award-desc">Dropped ' + buzzsaw.actual.toFixed(2) + ' pts (' + buzzsaw.all_play_w + '–' + buzzsaw.all_play_l + ' All-Play), but took an L to ' + buzzsaw.opp + ' (' + buzzsaw.opp_actual.toFixed(2) + ' pts).</div></div>' +
        '<div style="margin-top: 8px;"><span class="badge badge-unlucky">Luck Δ: ' + (buzzsaw.luck_delta > 0 ? '+' : '') + buzzsaw.luck_delta.toFixed(3) + '</span></div>' +
      '</div>' +
      '<div class="award-card green">' +
        '<div><div class="award-tag" style="color: var(--green);">🍀 Grand Theft Victory</div>' +
        '<div class="award-title">' + renderBadge(horseshoe.team) + '</div>' +
        '<div class="award-desc">Squeaked by with ' + horseshoe.actual.toFixed(2) + ' pts (' + horseshoe.all_play_w + '–' + horseshoe.all_play_l + ' All-Play) thanks to opponent meltdown.</div></div>' +
        '<div style="margin-top: 8px;"><span class="badge badge-lucky">Luck Δ: ' + (horseshoe.luck_delta > 0 ? '+' : '') + horseshoe.luck_delta.toFixed(3) + '</span></div>' +
      '</div>' +
      '<div class="award-card blue">' +
        '<div><div class="award-tag" style="color: var(--accent);">🧠 Master Tactician</div>' +
        '<div class="award-title">' + renderBadge(tactician.team) + '</div>' +
        '<div class="award-desc">Optimal starting execution of <b>' + tactician.coach_eff.toFixed(1) + '%</b> (' + tactician.actual.toFixed(2) + ' of ' + tactician.optimal.toFixed(2) + ' optimal pts).</div></div>' +
        '<div style="margin-top: 8px;"><span class="badge badge-neutral">Lineup Mastery</span></div>' +
      '</div>' +
      '<div class="award-card zinc">' +
        '<div><div class="award-tag" style="color: var(--dim);">⚓ The Anchor Award (Lead Weight)</div>' +
        '<div class="award-title">' + (anchor ? anchor.player + ' (' + anchor.pos + ')' : 'None') + '</div>' +
        '<div class="award-desc">Hung a league-low <b>' + (anchor ? anchor.pts.toFixed(2) : '0.00') + ' pts</b> in the starting lineup for ' + (anchor ? anchor.team : 'None') + '.</div></div>' +
        '<div style="margin-top: 8px;"><span class="badge badge-neutral">Lowest Starter of Wk</span></div>' +
      '</div>';
  }

  function renderBenchBlunders(wkData) {
    var blunders = [];
    wkData.forEach(function(t) {
      if (t.players) {
        t.players.forEach(function(p) {
          if (p.audit === 'Costly Bench') {
            blunders.push({ team: t.team, name: p.name, pos: p.pos, pts: p.pts, proj: p.proj });
          }
        });
      }
    });
    blunders.sort(function(a, b) { return b.pts - a.pts; });

    var bbody = document.getElementById('blundersTableBody');
    if (!bbody) return;
    bbody.innerHTML = '';
    blunders.slice(0, 10).forEach(function(b, idx) {
      var decoratedTeam = renderBadge(b.team);
      var btr = document.createElement('tr');
      btr.innerHTML = 
        '<td class="team-cell"><span class="rank-num">#' + (idx + 1) + '</span> ' + decoratedTeam + '</td>' +
        '<td data-label="Player" style="color: var(--text); font-weight: 600;">' + b.name + '</td>' +
        '<td data-label="Pos"><span class="badge badge-neutral">' + b.pos + '</span></td>' +
        '<td data-label="Points Left" style="font-weight: 800; color: var(--amber);">' + b.pts.toFixed(2) + ' pts</td>' +
        '<td data-label="Projection" style="color: var(--muted);">' + b.proj.toFixed(2) + ' pts</td>';
      bbody.appendChild(btr);
    });
  }

  function renderSeasonTrends(yrWeeksObj) {
    var stats = {};
    var weeks = Object.keys(yrWeeksObj).map(Number).sort(function(a, b) { return a - b; });

    weeks.forEach(function(w) {
      var matchups = yrWeeksObj[w] || [];
      matchups.forEach(function(m) {
        var tm = m.team;
        if (!stats[tm]) {
          stats[tm] = { team: tm, actual_w: 0, actual_l: 0, all_play_w: 0, all_play_l: 0, pf: 0.0, pa: 0.0, scores: [], pine_tax: 0.0, opp_surges: 0, opp_streak: 0, cardiac_w: 0, cardiac_l: 0 };
        }
        var s = stats[tm];
        s.pf += m.actual; s.pa += m.opp_actual; s.scores.push(m.actual);
        if (m.result === 'W') s.actual_w++;
        else if (m.result === 'L') s.actual_l++;
        s.all_play_w += m.all_play_w; s.all_play_l += m.all_play_l;
        s.pine_tax += (m.optimal - m.actual);
        if (Math.abs(m.actual - m.opp_actual) <= 5.0) {
          if (m.result === 'W') s.cardiac_w++;
          else if (m.result === 'L') s.cardiac_l++;
        }
        var oppProj = m.opp_proj || m.opp_actual;
        if (Math.round((m.opp_actual - oppProj) * 100) / 100 > 0) { s.opp_surges++; s.opp_streak++; }
        else { s.opp_streak = 0; }
      });
    });

    var rows = Object.values(stats);
    var totalWeeks = weeks.length;

    rows.forEach(function(r) {
      var totalMatches = r.actual_w + r.actual_l;
      var pfSq = Math.pow(r.pf, 2), paSq = Math.pow(r.pa, 2), denom = pfSq + paSq;
      r.pyth_wins = denom > 0 ? Math.round((pfSq / denom) * totalMatches * 10) / 10 : 0.0;
      r.pyth_delta = Math.round((r.actual_w - r.pyth_wins) * 10) / 10;
      var totAp = r.all_play_w + r.all_play_l;
      r.all_play_pct = totAp > 0 ? (r.all_play_w / totAp) : 0.0;
      var actPct = totalMatches > 0 ? (r.actual_w / totalMatches) : 0.0;
      r.luck_delta = Math.round((actPct - r.all_play_pct) * 1000) / 1000;
      r.avg_pa = totalWeeks > 0 ? Math.round((r.pa / totalWeeks) * 100) / 100 : 0.0;
      r.pine_tax = Math.round(r.pine_tax * 100) / 100;

      var mean = r.scores.length ? r.scores.reduce(function(a,b){return a+b;},0)/r.scores.length : 0;
      var variance = r.scores.length ? r.scores.reduce(function(a,b){return a + Math.pow(b - mean, 2);},0)/r.scores.length : 0;
      r.volatility_sd = Math.round(Math.sqrt(variance) * 10) / 10;
      r.volatility_tag = r.volatility_sd >= 18.0 ? 'Boom/Bust' : (r.volatility_sd <= 12.0 ? 'Steady Floor' : 'Balanced');
    });

    rows.sort(function(a, b) {
      if (b.all_play_w !== a.all_play_w) return b.all_play_w - a.all_play_w;
      return b.pf - a.pf;
    });

    var stBody = document.getElementById('seasonTableBody');
    if (!stBody) return;
    stBody.innerHTML = '';
    rows.forEach(function(r, idx) {
      var cDeltaClass = r.luck_delta > 0 ? 'badge-lucky' : (r.luck_delta < 0 ? 'badge-unlucky' : 'badge-neutral');
      var decoratedTeam = renderBadge(r.team);
      var streakBadge = r.curr_opp_surge_streak >= 2 ? '<b>' + r.curr_opp_surge_streak + ' st!</b>' : r.curr_opp_surge_streak + ' st';
      var pythDiffStr = (r.pyth_delta > 0 ? '+' : '') + r.pyth_delta.toFixed(1);
      var pythColor = r.pyth_delta > 0.5 ? 'var(--green)' : (r.pyth_delta < -0.5 ? 'var(--red)' : 'var(--muted)');

      var tr = document.createElement('tr');
      tr.innerHTML = 
        '<td class="team-cell"><span class="rank-num">#' + (idx + 1) + '</span> ' + decoratedTeam + '</td>' +
        '<td data-label="Actual W-L"><b>' + r.actual_w + '–' + r.actual_l + '</b></td>' +
        '<td data-label="Pyth Wins"><b>' + r.pyth_wins.toFixed(1) + '</b> <span style="font-size: 11px; color: ' + pythColor + ';">(' + pythDiffStr + ')</span></td>' +
        '<td data-label="All-Play">' + r.all_play_w + '–' + r.all_play_l + ' <span style="font-size: 11px; color: var(--dim);">(' + r.all_play_pct.toFixed(3) + ')</span></td>' +
        '<td data-label="Season Luck Δ"><span class="badge ' + cDeltaClass + '">' + (r.luck_delta >= 0 ? '+' : '') + r.luck_delta.toFixed(3) + '</span></td>' +
        '<td data-label="Volatility">±' + r.volatility_sd.toFixed(1) + ' <span class="badge badge-neutral" style="font-size: 10px; padding: 1px 6px;">' + r.volatility_tag + '</span></td>' +
        '<td data-label="Cardiac Rec"><b>' + r.cardiac_w + '–' + r.cardiac_l + '</b></td>' +
        '<td data-label="Pine Tax" style="color: var(--amber); font-weight: 700;">' + r.pine_tax.toFixed(2) + ' pts</td>' +
        '<td data-label="Opp Surges">' + r.opp_over_proj_count + '/' + totalWeeks + ' wks (' + streakBadge + ')</td>' +
        '<td data-label="Avg Opp PA"><b>' + r.avg_pa.toFixed(2) + '</b></td>';
      stBody.appendChild(tr);
    });
  }

  function switchTab(viewName) {
    var tabs = ['week', 'season', 'h2h', 'payouts', 'halloffame', 'blunders', 'glossary'];
    for (var i = 0; i < tabs.length; i++) {
      var el = document.getElementById('view-' + tabs[i]);
      if (el) el.style.display = 'none';
    }
    var btns = document.querySelectorAll('.tab-btn');
    for (var j = 0; j < btns.length; j++) {
      btns[j].classList.remove('active');
    }
    var activeEl = document.getElementById('view-' + viewName);
    if (activeEl) {
      if (viewName === 'h2h' || viewName === 'payouts' || viewName === 'halloffame') {
        activeEl.style.display = 'flex';
      } else {
        activeEl.style.display = 'block';
      }
    }
    if (event && event.target) {
      event.target.classList.add('active');
    }
  }

  function setH2HScope(scope) {
    h2hScope = scope;
    var curBtn = document.getElementById('scopeCurrentBtn');
    var allBtn = document.getElementById('scopeAllBtn');
    if (curBtn) curBtn.classList.toggle('active', scope === 'current');
    if (allBtn) allBtn.classList.toggle('active', scope === 'all');
    
    var select = document.getElementById('mgrFilter');
    if (select) {
      select.querySelectorAll('option').forEach(function(opt) {
        if (opt.value === 'ALL') return;
        var isCurrent = opt.getAttribute('data-is-current') === 'true';
        if (scope === 'current' && !isCurrent) {
          opt.style.display = 'none';
          if (select.value === opt.value) select.value = 'ALL';
        } else {
          opt.style.display = '';
        }
      });
    }
    applyH2HFilters();
  }

  function applyH2HFilters() {
    var select = document.getElementById('mgrFilter');
    var mgr = select ? select.value : 'ALL';
    document.querySelectorAll('.rivalry-row').forEach(function(r) {
      var m1 = r.getAttribute('data-m1'), m2 = r.getAttribute('data-m2');
      var isCurrent = r.getAttribute('data-current') === 'true';
      if ((h2hScope === 'all' || isCurrent) && (mgr === 'ALL' || m1 === mgr || m2 === mgr)) {
        r.style.display = '';
      } else {
        r.style.display = 'none';
      }
    });
  }

  function toggleTheme() {
    var isLight = document.body.classList.toggle('light-mode');
    localStorage.setItem('ff_theme', isLight ? 'light' : 'dark');
    updateThemeBtn(isLight);
  }

  function updateThemeBtn(isLight) {
    var btn = document.getElementById('theme-toggle');
    if (btn) {
      btn.innerHTML = isLight ? '🌙 Dark Mode' : '☀️ Light Mode';
    }
  }

  window.onload = initApp;
</script>
</body>
</html>"""

  with open("index.html", "w") as f:
    f.write(html)


def main():
  global WEEK
  print(f"Connecting to ESPN Fantasy API for League {LEAGUE_ID} (Season {YEAR})...")
  league = League(league_id=LEAGUE_ID, year=YEAR, espn_s2=ESPN_S2, swid=SWID)

  if not WEEK:
    WEEK = max(1, getattr(league, "current_week", 1) - 1)
    print(f"Auto-detected completed week: Week {WEEK}")

  current_managers = sorted(list(set(get_manager_name(t) for t in league.teams if get_manager_name(t) != "Manager")))

  print(f"Processing season up to Week {WEEK}...")
  history_file = f"league_history_{YEAR}.json"
  history = load_history(history_file, {"year": YEAR, "weeks": {}})

  for w in range(1, WEEK + 1):
    w_str = str(w)
    if w_str not in history["weeks"] or not history["weeks"][w_str] or "opp_proj" not in history["weeks"][w_str][0]:
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

        w_teams.append({"team": home_label, "manager": h_mgr, "opp": away_label, "opp_manager": a_mgr, "actual": h_act, "proj": h_proj, "diff": round(h_act - h_proj, 2), "opp_actual": a_act, "opp_proj": a_proj, "optimal": h_opt, "result": "W" if h_act > a_act else ("L" if h_act < a_act else "T"), "coach_eff": round((h_act / h_opt) * 100, 1) if h_opt > 0 else 100.0, "players": h_players})
        w_teams.append({"team": away_label, "manager": a_mgr, "opp": home_label, "opp_manager": h_mgr, "actual": a_act, "proj": a_proj, "diff": round(a_act - a_proj, 2), "opp_actual": h_act, "opp_proj": h_proj, "optimal": a_opt, "result": "W" if a_act > h_act else ("L" if a_act < h_act else "T"), "coach_eff": round((a_act / a_opt) * 100, 1) if a_opt > 0 else 100.0, "players": a_players})

      all_scores = [t["actual"] for t in w_teams]
      total_opps = len(w_teams) - 1
      for t in w_teams:
        t["all_play_w"] = sum(1 for s in all_scores if t["actual"] > s)
        t["all_play_l"] = sum(1 for s in all_scores if t["actual"] < s)
        t["luck_delta"] = round((1.0 if t["result"] == "W" else 0.0) - (t["all_play_w"] / total_opps), 3)

      history["weeks"][w_str] = w_teams

  save_history(history_file, history)

  current_week_data = history["weeks"].get(str(WEEK), [])
  trends_data, total_weeks = compute_trends(history)
  weekly_team_bounties, weekly_player_bounties, weekly_anchors, position_records, season_payout_leaders = compute_records_and_payouts(history)

  sync_historical_h2h(YEAR)
  champions, finishes_data = sync_champions_and_finishes(YEAR)
  leaderboard = compute_all_time_leaderboard(champions, current_managers, finishes_data)
  reigning = get_reigning_badges(champions, YEAR)
  rivalries, managers_list, season_log = update_and_compute_h2h(history, YEAR)

  generate_html_report(WEEK, current_week_data, trends_data, total_weeks, weekly_team_bounties, weekly_player_bounties, weekly_anchors, position_records, season_payout_leaders, champions, leaderboard, reigning, rivalries, managers_list, current_managers, season_log)
  print("Summary build complete with Pill Navigation!")


if __name__ == "__main__":
  main()
