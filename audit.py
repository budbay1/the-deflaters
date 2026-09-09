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
ALIASES_FILE = "manager_aliases.json"

HISTORICAL_CHAMPIONS_OVERRIDE = {}

WEEKLY_BOUNTY_TEAM_CASH = 25.0
WEEKLY_BOUNTY_PLAYER_CASH = 25.0

PODIUM_PAYOUTS = {
    "gold": 550.0,
    "silver": 300.0,
    "bronze": 150.0,
    "pf_leader": 100.0
}


def load_aliases():
  if os.path.exists(ALIASES_FILE):
    try:
      with open(ALIASES_FILE, "r") as f:
        return json.load(f)
    except Exception as e:
      print(f"Warning: Could not parse {ALIASES_FILE}: {e}")
  return {}


def get_manager_name(team):
  aliases = load_aliases()
  raw_name = "Manager"
  
  if hasattr(team, "owners") and team.owners:
    owner = team.owners[0]
    if isinstance(owner, dict):
      first = owner.get("firstName", "")
      last = owner.get("lastName", "")
      full = f"{first} {last}".strip()
      raw_name = full if full else owner.get("displayName", "Manager")
    else:
      raw_name = str(owner)
  elif hasattr(team, "owner") and team.owner:
    raw_name = str(team.owner)

  team_name = getattr(team, "team_name", "")

  for alias, canonical in aliases.items():
    if alias.lower() == raw_name.lower() or alias.lower() == team_name.lower():
      return canonical

  return raw_name


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

    players_data.append({"name": p.name, "pos": pos_clean, "started": started, "audit": audit, "pts": pts, "proj": proj, "playerId": p.playerId})

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


def compute_records_and_payouts(weeks_obj, finishes_map=None):
  weekly_team_bounties, weekly_player_bounties, weekly_anchors = [], [], []
  sorted_weeks = sorted([int(w) for w in weeks_obj.keys() if int(w) <= 17])

  for w in sorted_weeks:
    matchups = weeks_obj[str(w)]
    if not matchups: continue
    
    if w <= 14:
      high_match = max(matchups, key=lambda x: x["actual"])
      if high_match["actual"] > 0:
        weekly_team_bounties.append({
            "week": w, "team": high_match["team"], "pts": high_match["actual"],
            "opp": high_match["opp"], "opp_pts": high_match["opp_actual"],
            "cash": WEEKLY_BOUNTY_TEAM_CASH
        })

    starters_this_week = []
    for team_entry in matchups:
      team_name = team_entry["team"]
      for p in team_entry["players"]:
        if p["started"]:
          starters_this_week.append({"week": w, "player": p["name"], "pos": p["pos"], "pts": p["pts"], "team": team_name})

    if starters_this_week and w <= 14:
      top_player = max(starters_this_week, key=lambda x: x["pts"])
      if top_player["pts"] > 0:
        weekly_player_bounties.append({
            "week": w, "player": top_player["player"], "pos": top_player["pos"],
            "pts": top_player["pts"], "team": top_player["team"],
            "cash": WEEKLY_BOUNTY_PLAYER_CASH
        })
        weekly_anchors.append(min(starters_this_week, key=lambda x: x["pts"]))

  team_totals = {}
  for w in sorted_weeks:
    for m in weeks_obj[str(w)]:
      team_totals[m["team"]] = team_totals.get(m["team"], 0.0) + m["actual"]

  sorted_pf = sorted(team_totals.items(), key=lambda x: x[1], reverse=True)
  top_three_pf = [{"team": t, "pts": round(p, 2)} for t, p in sorted_pf[:3]]

  season_pf_leader = sorted_pf[0] if sorted_pf else ("None", 0.0)
  season_high_team_game = max(weekly_team_bounties, key=lambda x: x["pts"]) if weekly_team_bounties else None
  season_high_player_game = max(weekly_player_bounties, key=lambda x: x["pts"]) if weekly_player_bounties else None

  season_payout_leaders = {
      "pf_leader_team": season_pf_leader[0],
      "pf_leader_pts": round(season_pf_leader[1], 2),
      "pf_leader_prize": PODIUM_PAYOUTS["pf_leader"],
      "top_three_pf": top_three_pf,
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


def extract_draft_info(league_obj, seasons_data_obj):
  """Extracts draft picks and calculates total season points for each drafted player."""
  draft_picks = []
  try:
    raw_picks = getattr(league_obj, "draft", [])
    
    player_total_pts = {}
    for w_str, matchups in seasons_data_obj.items():
      for m in matchups:
        for p in m.get("players", []):
          pid = p.get("playerId")
          pts = p.get("pts", 0.0)
          if pid:
            player_total_pts[pid] = player_total_pts.get(pid, 0.0) + pts

    for idx, pick in enumerate(raw_picks):
      # Accurately resolve pick numbers across varied ESPN object formats and fall back to sequential index if needed
      overall = getattr(pick, "overall_pick", None) or getattr(pick, "pick_num", None) or getattr(pick, "overallPickNumber", None) or pick.get("overallPickNumber") or pick.get("pickNum") or (idx + 1)
      round_num = getattr(pick, "round_num", None) or getattr(pick, "roundId", None) or pick.get("roundNum") or pick.get("roundId") or 1
      round_pick = getattr(pick, "round_pick", None) or getattr(pick, "roundPickNumber", None) or pick.get("roundPickNumber") or pick.get("roundPick") or (overall)
      
      player_name = getattr(pick, "playerName", None) or pick.get("playerName", "Unknown Player")
      player_id = getattr(pick, "playerId", None) or pick.get("playerId", 0)
      pos = getattr(pick, "position", None) or pick.get("position", "")
      
      team_obj = getattr(pick, "team", None) or pick.get("team", None)
      mgr = get_manager_name(team_obj) if team_obj else "Unknown Manager"
      team_name = getattr(team_obj, "team_name", "Team") if team_obj else "Team"

      tot_pts = player_total_pts.get(player_id, 0.0)

      draft_picks.append({
          "overall": int(overall),
          "round": int(round_num),
          "round_pick": int(round_pick),
          "player": player_name,
          "playerId": player_id,
          "position": pos,
          "manager": mgr,
          "team_name": team_name,
          "total_points": round(tot_pts, 2)
      })
  except Exception as e:
    print(f"Draft extraction note: {e}")
  
  return sorted(draft_picks, key=lambda x: x["overall"])


def process_season_weeks(league_obj, season_yr):
  aliases = load_aliases()
  season_weeks = {}
  all_time_matchups = {}

  for w in range(1, 18):
    w_str = str(w)
    try:
      box_scores = league_obj.box_scores(week=w)
    except Exception:
      continue
    if not box_scores: continue

    w_teams = []
    for match in box_scores:
      h_act, a_act = round(match.home_score, 2), round(match.away_score, 2)
      if h_act == 0.0 and a_act == 0.0: continue
      h_proj = round(sum(p.projected_points for p in match.home_lineup if p.slot_position not in ["BE", "IR"]), 2)
      a_proj = round(sum(p.projected_points for p in match.away_lineup if p.slot_position not in ["BE", "IR"]), 2)

      h_players, h_opt = audit_roster(match.home_lineup, ROSTER_SLOTS, h_act)
      a_players, a_opt = audit_roster(match.away_lineup, ROSTER_SLOTS, a_act)

      h_mgr = get_manager_name(match.home_team)
      a_mgr = get_manager_name(match.away_team)
      
      h_team_name = getattr(match.home_team, "team_name", "Team")
      a_team_name = getattr(match.away_team, "team_name", "Team")

      home_label = f"{h_team_name} ({h_mgr})" if h_mgr != "Manager" else h_team_name
      away_label = f"{a_team_name} ({a_mgr})" if a_mgr != "Manager" else a_team_name

      if h_mgr != "Manager" and a_mgr != "Manager":
        pair = sorted([h_mgr, a_mgr])
        m_id = f"{season_yr}_W{w}_{pair[0]}_vs_{pair[1]}"
        is_playoff = w >= 15
        
        all_time_matchups[m_id] = {
            "year": season_yr, "week": w, "is_playoff": is_playoff,
            "m1": pair[0], "t1": h_team_name if h_mgr == pair[0] else a_team_name, "s1": h_act if h_mgr == pair[0] else a_act,
            "m2": pair[1], "t2": a_team_name if h_mgr == pair[1] else h_team_name, "s2": a_act if h_mgr == pair[1] else h_act
        }

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
          "opp_actual": h_act, "opp_proj": a_proj, "optimal": a_opt,
          "result": "W" if a_act > h_act else ("L" if a_act < h_act else "T"),
          "coach_eff": round((a_act / a_opt) * 100, 1) if a_opt > 0 else 100.0,
          "players": a_players,
      })

    all_scores = [t["actual"] for t in w_teams]
    total_opps = len(w_teams) - 1
    if total_opps > 0:
      for t in w_teams:
        t["all_play_w"] = sum(1 for s in all_scores if t["actual"] > s)
        t["all_play_l"] = sum(1 for s in all_scores if t["actual"] < s)
        t["luck_delta"] = round((1.0 if t["result"] == "W" else 0.0) - (t["all_play_w"] / total_opps), 3)

    season_weeks[w_str] = w_teams

  return season_weeks, all_time_matchups


def sync_champions_and_finishes(current_year):
  all_time = load_history(ALL_TIME_FILE, {"champions": {}, "matchups": {}, "finishes": {}, "h2h_ingested_years": []})
  if "champions" not in all_time: all_time["champions"] = {}
  if "finishes" not in all_time: all_time["finishes"] = {}
  all_time["champions"].update(HISTORICAL_CHAMPIONS_OVERRIDE)

  for y in range(2023, current_year + 1):
    y_str = str(y)
    try:
      past_league = League(league_id=LEAGUE_ID, year=y, espn_s2=ESPN_S2, swid=SWID)
      ranked_teams = sorted(past_league.teams, key=lambda t: (getattr(t, "final_standing", 0) if getattr(t, "final_standing", 0) > 0 else 99, getattr(t, "standing", 99), getattr(t, "points_for", 0)))
      season_finishes = {get_manager_name(t): (getattr(t, "final_standing", 0) if 0 < getattr(t, "final_standing", 0) <= len(past_league.teams) else idx) for idx, t in enumerate(ranked_teams, 1) if get_manager_name(t) != "Manager"}
      all_time["finishes"][y_str] = season_finishes

      gold_team = next((t for t in past_league.teams if getattr(t, "final_standing", 0) == 1), ranked_teams[0] if ranked_teams else None)
      silver_team = next((t for t in past_league.teams if getattr(t, "final_standing", 0) == 2), ranked_teams[1] if len(ranked_teams) > 1 else None)
      bronze_team = next((t for t in past_league.teams if getattr(t, "final_standing", 0) == 3), ranked_teams[2] if len(ranked_teams) > 2 else None)
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
  aliases = load_aliases()

  for y in sorted([int(y) for y in champions.keys()]):
    p = champions[str(y)]
    for m, cat in [(extract_manager_from_label(p.get("gold")), "gold"), (extract_manager_from_label(p.get("silver")), "silver"), (extract_manager_from_label(p.get("bronze")), "bronze"), (extract_manager_from_label(p.get("last")), "last")]:
      if m != "Unknown":
        for alias, canonical in aliases.items():
          if alias.lower() == m.lower(): m = canonical
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
      for alias, canonical in aliases.items():
        if alias.lower() == m.lower(): m = canonical
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


def compute_accumulated_money(seasons_data, champions, weekly_bounty_totals, weekly_player_bounties_all, current_year):
  accumulated = {}
  aliases = load_aliases()

  def add_cash(mgr_label, amount):
    if not mgr_label or mgr_label == "TBD" or mgr_label == "Unknown": return
    mgr = extract_manager_from_label(mgr_label)
    if mgr == "Unknown": mgr = mgr_label
    for alias, canonical in aliases.items():
      if alias.lower() == mgr.lower(): mgr = canonical
    accumulated[mgr] = accumulated.get(mgr, 0.0) + float(amount)

  for yr_str, weeks_dict in seasons_data.items():
    yr_int = int(yr_str)
    if yr_int < 2023: continue
    if yr_int > current_year: continue

    bounties_list = weekly_bounty_totals.get(yr_str, [])
    for b in bounties_list:
      team_lbl = b.get("team")
      wins = b.get("team_bounties", b.get("wins", 0))
      add_cash(team_lbl, wins * WEEKLY_BOUNTY_TEAM_CASH)

    player_bounties_list = weekly_player_bounties_all.get(yr_str, [])
    for pb in player_bounties_list:
      team_lbl = pb.get("team")
      add_cash(team_lbl, WEEKLY_BOUNTY_PLAYER_CASH)

    yr_champ = champions.get(yr_str, {})
    if yr_champ.get("gold"): add_cash(yr_champ["gold"], PODIUM_PAYOUTS["gold"])
    if yr_champ.get("silver"): add_cash(yr_champ["silver"], PODIUM_PAYOUTS["silver"])
    if yr_champ.get("bronze"): add_cash(yr_champ["bronze"], PODIUM_PAYOUTS["bronze"])

    team_season_pf = {}
    for w_str, matchups in weeks_dict.items():
      for m in matchups:
        team_season_pf[m["team"]] = team_season_pf.get(m["team"], 0.0) + m["actual"]
    if team_season_pf:
      top_pf_team = max(team_season_pf.items(), key=lambda x: x[1])[0]
      add_cash(top_pf_team, PODIUM_PAYOUTS["pf_leader"])

  return sorted([{"manager": mgr, "total_cash": round(amt, 2)} for mgr, amt in accumulated.items() if amt > 0], key=lambda x: x["total_cash"], reverse=True)


def main():
  global WEEK
  print(f"Connecting to ESPN Fantasy API for League {LEAGUE_ID} (Season {YEAR})...")
  league = League(league_id=LEAGUE_ID, year=YEAR, espn_s2=ESPN_S2, swid=SWID)

  if not WEEK:
    WEEK = max(1, getattr(league, "current_week", 1))
    print(f"Auto-detected current week: Week {WEEK}")

  current_managers = sorted(list(set(get_manager_name(t) for t in league.teams if get_manager_name(t) != "Manager")))

  all_time = load_history(ALL_TIME_FILE, {"champions": {}, "matchups": {}, "finishes": {}, "h2h_ingested_years": []})
  if "matchups" not in all_time: all_time["matchups"] = {}

  seasons_data = load_history(SEASONS_DATA_FILE, {})
  draft_history_all = {}

  for y in range(2023, YEAR + 1):
    print(f"Processing season data for {y}...")
    if y == YEAR:
      season_weeks, yr_matchups = process_season_weeks(league, y)
      draft_history_all[str(y)] = extract_draft_info(league, season_weeks)
    else:
      try:
        past_league = League(league_id=LEAGUE_ID, year=y, espn_s2=ESPN_S2, swid=SWID, fetch_options=['mDraftDetail'])
        season_weeks, yr_matchups = process_season_weeks(past_league, y)
        draft_history_all[str(y)] = extract_draft_info(past_league, season_weeks)
      except Exception as e:
        print(f"Could not load season {y} draft with options: {e}")
        try:
          past_league = League(league_id=LEAGUE_ID, year=y, espn_s2=ESPN_S2, swid=SWID)
          season_weeks, yr_matchups = process_season_weeks(past_league, y)
          draft_history_all[str(y)] = extract_draft_info(past_league, season_weeks)
        except Exception as e2:
          print(f"Fallback season {y} draft failed: {e2}")
          continue

    seasons_data[str(y)] = season_weeks
    all_time["matchups"].update(yr_matchups)

  save_history(SEASONS_DATA_FILE, seasons_data)
  save_history(ALL_TIME_FILE, all_time)

  champions, finishes_data = sync_champions_and_finishes(YEAR)
  leaderboard = compute_all_time_leaderboard(champions, current_managers, finishes_data)
  
  season_payouts_all = {}
  weekly_bounties_all = {}
  weekly_player_bounties_all = {}
  weekly_anchors_all = {}
  weekly_bounty_totals_all = {}
  for yr_key, weeks_dict in seasons_data.items():
    fin_map = finishes_data.get(yr_key, {})
    tb, pb, an, sp = compute_records_and_payouts(weeks_dict, fin_map)
    season_payouts_all[yr_key] = sp
    weekly_bounties_all[yr_key] = tb
    weekly_player_bounties_all[yr_key] = pb
    weekly_anchors_all[yr_key] = an

    bounty_tracker = {}
    for b in tb:
      tm = b["team"]
      if tm not in bounty_tracker:
        bounty_tracker[tm] = {"team_bounties": 0, "player_bounties": 0, "total_cash": 0.0}
      bounty_tracker[tm]["team_bounties"] += 1
      bounty_tracker[tm]["total_cash"] += WEEKLY_BOUNTY_TEAM_CASH

    for pb_item in pb:
      tm = pb_item["team"]
      if tm not in bounty_tracker:
        bounty_tracker[tm] = {"team_bounties": 0, "player_bounties": 0, "total_cash": 0.0}
      bounty_tracker[tm]["player_bounties"] += 1
      bounty_tracker[tm]["total_cash"] += WEEKLY_BOUNTY_PLAYER_CASH

    weekly_bounty_totals_all[yr_key] = sorted(
        [{
            "team": tm,
            "team_bounties": data["team_bounties"],
            "player_bounties": data["player_bounties"],
            "total_bounties": data["team_bounties"] + data["player_bounties"],
            "total_cash": round(data["total_cash"], 2)
        } for tm, data in bounty_tracker.items()],
        key=lambda x: x["total_cash"], reverse=True
    )

  accumulated_money = compute_accumulated_money(seasons_data, champions, weekly_bounty_totals_all, weekly_player_bounties_all, YEAR)

  all_time_high_team = {"team": "None", "pts": 0.0, "opp": "None", "opp_pts": 0.0, "week": 0, "year": 0}
  all_time_high_player = {"player": "None", "team": "None", "pts": 0.0, "week": 0, "year": 0, "pos": ""}
  all_time_high_season_pf = {"team": "None", "pts": 0.0, "year": 0}
  all_time_high_pa = {"team": "None", "pa": 0.0, "year": 0}
  all_time_max_margin = {"winner": "None", "loser": "None", "margin": -1.0, "week": 0, "year": 0}

  career_season_pf_list = []
  career_game_teams_list = []
  career_game_players_list = []

  for yr_str, weeks_dict in seasons_data.items():
    yr_int = int(yr_str)
    team_season_pf = {}
    team_season_pa = {}

    for w_str, matchups in weeks_dict.items():
      w_int = int(w_str)
      for m in matchups:
        team_season_pf[m["team"]] = team_season_pf.get(m["team"], 0.0) + m["actual"]
        team_season_pa[m["team"]] = team_season_pa.get(m["team"], 0.0) + m["opp_actual"]

        career_game_teams_list.append({
            "team": m["team"], "pts": m["actual"], "opp": m["opp"], "opp_pts": m["opp_actual"], "week": w_int, "year": yr_int
        })

        if m["actual"] > all_time_high_team["pts"]:
          all_time_high_team = {
              "team": m["team"], "pts": m["actual"],
              "opp": m["opp"], "opp_pts": m["opp_actual"],
              "week": w_int, "year": yr_int
          }

        margin = round(abs(m["actual"] - m["opp_actual"]), 2)
        if margin > all_time_max_margin["margin"] and m["actual"] > m["opp_actual"]:
          all_time_max_margin = {
              "winner": m["team"], "loser": m["opp"],
              "margin": margin, "week": w_int, "year": yr_int
          }

        for p in m.get("players", []):
          if p["started"]:
            career_game_players_list.append({
                "player": p["name"], "team": m["team"], "pts": p["pts"], "pos": p["pos"], "week": w_int, "year": yr_int
            })
            if p["pts"] > all_time_high_player["pts"]:
              all_time_high_player = {"player": p["name"], "team": m["team"], "pts": p["pts"], "week": w_int, "year": yr_int, "pos": p["pos"]}

    for tm, pf_val in team_season_pf.items():
      career_season_pf_list.append({"team": tm, "pts": round(pf_val, 2), "year": yr_int})
      if pf_val > all_time_high_season_pf["pts"]:
        all_time_high_season_pf = {"team": tm, "pts": round(pf_val, 2), "year": yr_int}

    for tm, pa_val in team_season_pa.items():
      if pa_val > all_time_high_pa["pa"]:
        all_time_high_pa = {"team": tm, "pa": round(pa_val, 2), "year": yr_int}

  career_season_pf_list.sort(key=lambda x: x["pts"], reverse=True)
  career_game_teams_list.sort(key=lambda x: x["pts"], reverse=True)
  career_game_players_list.sort(key=lambda x: x["pts"], reverse=True)

  global_bundle = {
      "seasons_data": seasons_data,
      "champions": champions,
      "leaderboard": leaderboard,
      "reigning_by_season": champions,
      "current_managers": current_managers,
      "matchups": all_time["matchups"],
      "season_payouts": season_payouts_all,
      "weekly_bounties": weekly_bounties_all,
      "weekly_player_bounties": weekly_player_bounties_all,
      "weekly_anchors": weekly_anchors_all,
      "weekly_bounty_totals": weekly_bounty_totals_all,
      "accumulated_money": accumulated_money,
      "draft_history": draft_history_all,
      "career_rankings": {
          "season_pf": career_season_pf_list[:10],
          "game_teams": career_game_teams_list[:10],
          "game_players": career_game_players_list[:10]
      },
      "all_time_records": {
          "high_team_game": all_time_high_team,
          "high_player_game": all_time_high_player,
          "high_season_pf": all_time_high_season_pf,
          "high_points_against": all_time_high_pa,
          "max_margin": all_time_max_margin
      }
  }
  save_history(GLOBAL_DATA_FILE, global_bundle)
  print("Data engine execution complete.")


if __name__ == "__main__":
  main()
