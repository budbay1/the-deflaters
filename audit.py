import json
import os
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

HISTORICAL_CHAMPIONS_OVERRIDE = {
    # "2022": {"gold": "Team (Manager)", "silver": "Team (Manager)", "bronze": "Team (Manager)", "last": "Team (Manager)"}
}


def get_manager_name(team):
  """Extracts human name or display name from ESPN metadata."""
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
  """Extracts human manager name from a formatted label 'Team Name (Manager)'."""
  if not team_label or team_label == "TBD":
    return "Unknown"
  if "(" in team_label and ")" in team_label:
    return team_label.split("(")[-1].split(")")[0].strip()
  return team_label.strip()


def audit_roster(lineup, slots, actual_score):
  qbs = sorted(
      [p for p in lineup if p.position == "QB"],
      key=lambda x: x.points,
      reverse=True,
  )
  rbs = sorted(
      [p for p in lineup if p.position == "RB"],
      key=lambda x: x.points,
      reverse=True,
  )
  wrs = sorted(
      [p for p in lineup if p.position == "WR"],
      key=lambda x: x.points,
      reverse=True,
  )
  tes = sorted(
      [p for p in lineup if p.position == "TE"],
      key=lambda x: x.points,
      reverse=True,
  )
  ks = sorted(
      [p for p in lineup if p.position == "K"],
      key=lambda x: x.points,
      reverse=True,
  )
  dsts = sorted(
      [p for p in lineup if p.position in ["D/ST", "DEF"]],
      key=lambda x: x.points,
      reverse=True,
  )

  optimal_ids = set()
  for p in qbs[: slots.get("QB", 1)]:
    optimal_ids.add(p.playerId)
  for p in rbs[: slots.get("RB", 2)]:
    optimal_ids.add(p.playerId)
  for p in wrs[: slots.get("WR", 3)]:
    optimal_ids.add(p.playerId)
  for p in tes[: slots.get("TE", 1)]:
    optimal_ids.add(p.playerId)

  flex_pool = sorted(
      rbs[slots.get("RB", 2) :]
      + wrs[slots.get("WR", 3) :]
      + tes[slots.get("TE", 1) :],
      key=lambda x: x.points,
      reverse=True,
  )
  for p in flex_pool[: slots.get("FLEX", 1)]:
    optimal_ids.add(p.playerId)

  for p in ks[: slots.get("K", 1)]:
    optimal_ids.add(p.playerId)
  for p in dsts[: slots.get("D/ST", 1)]:
    optimal_ids.add(p.playerId)

  players_data = []
  for p in lineup:
    started = p.slot_position not in ["BE", "IR"]
    is_optimal = p.playerId in optimal_ids
    pts = round(p.points, 2)
    proj = round(getattr(p, "projected_points", 0.0), 2)
    pos_clean = "D/ST" if p.position in ["D/ST", "DEF"] else p.position

    if started and is_optimal:
      audit = "Smart Start"
    elif not started and not is_optimal:
      audit = "Correct Bench"
    elif not started and is_optimal:
      audit = "Costly Bench"
    else:
      audit = "Starter Bust"

    players_data.append({
        "name": p.name,
        "pos": pos_clean,
        "started": started,
        "audit": audit,
        "pts": pts,
        "proj": proj,
    })

  calc_optimal = round(
      sum(p.points for p in lineup if p.playerId in optimal_ids), 2
  )
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
  weekly_team_bounties = []
  weekly_player_bounties = []
  position_records = {
      pos: {"pts": -99.0, "player": "None", "team": "None", "week": 0}
      for pos in ["QB", "RB", "WR", "TE", "K", "D/ST"]
  }

  sorted_weeks = sorted([int(w) for w in history["weeks"].keys()])

  for w in sorted_weeks:
    matchups = history["weeks"][str(w)]
    if not matchups:
      continue

    # 1. Weekly High Team Points
    high_match = max(matchups, key=lambda x: x["actual"])
    weekly_team_bounties.append({
        "week": w,
        "team": high_match["team"],
        "pts": high_match["actual"],
        "opp": high_match["opp"],
        "opp_pts": high_match["opp_actual"],
    })

    # 2. Weekly High Individual Starter
    starters_this_week = []
    for team_entry in matchups:
      team_name = team_entry["team"]
      for p in team_entry["players"]:
        if p["started"]:
          starters_this_week.append({
              "week": w,
              "player": p["name"],
              "pos": p["pos"],
              "pts": p["pts"],
              "team": team_name,
          })
          if p["pos"] in position_records:
            if p["pts"] > position_records[p["pos"]]["pts"]:
              position_records[p["pos"]] = {
                  "pts": p["pts"],
                  "player": p["name"],
                  "team": team_name,
                  "week": w,
              }

    if starters_this_week:
      high_starter = max(starters_this_week, key=lambda x: x["pts"])
      weekly_player_bounties.append(high_starter)

  # 3. Season High Points Leaders
  season_high_team_game = (
      max(weekly_team_bounties, key=lambda x: x["pts"])
      if weekly_team_bounties
      else None
  )

  team_totals = {}
  for w in sorted_weeks:
    for m in history["weeks"][str(w)]:
      tm = m["team"]
      team_totals[tm] = team_totals.get(tm, 0.0) + m["actual"]

  season_pf_leader = (
      max(team_totals.items(), key=lambda x: x[1])
      if team_totals
      else ("None", 0.0)
  )
  season_high_player_game = (
      max(weekly_player_bounties, key=lambda x: x["pts"])
      if weekly_player_bounties
      else None
  )

  season_payout_leaders = {
      "pf_leader_team": season_pf_leader[0],
      "pf_leader_pts": round(season_pf_leader[1], 2),
      "high_game_team": (
          season_high_team_game["team"] if season_high_team_game else "None"
      ),
      "high_game_pts": (
          season_high_team_game["pts"] if season_high_team_game else 0.0
      ),
      "high_game_week": (
          season_high_team_game["week"] if season_high_team_game else 0
      ),
      "high_player": (
          season_high_player_game["player"]
          if season_high_player_game
          else "None"
      ),
      "high_player_pts": (
          season_high_player_game["pts"] if season_high_player_game else 0.0
      ),
      "high_player_pos": (
          season_high_player_game["pos"] if season_high_player_game else ""
      ),
      "high_player_team": (
          season_high_player_game["team"] if season_high_player_game else "None"
      ),
      "high_player_week": (
          season_high_player_game["week"] if season_high_player_game else 0
      ),
  }

  return (
      weekly_team_bounties,
      weekly_player_bounties,
      position_records,
      season_payout_leaders,
  )


def sync_historical_h2h(current_year):
  """Reaches back to 2023 to backfill multi-year head-to-head records."""
  all_time = load_history(
      ALL_TIME_FILE,
      {"champions": {}, "matchups": {}, "h2h_ingested_years": []},
  )
  if "matchups" not in all_time:
    all_time["matchups"] = {}
  if "h2h_ingested_years" not in all_time:
    all_time["h2h_ingested_years"] = []

  for y in range(2023, current_year):
    if y in all_time["h2h_ingested_years"]:
      continue

    print(f"Backfilling H2H matchup log for Season {y}...")
    try:
      past_league = League(
          league_id=LEAGUE_ID, year=y, espn_s2=ESPN_S2, swid=SWID
      )
      for w in range(1, 19):
        try:
          b_scores = past_league.box_scores(week=w)
          if not b_scores:
            continue
          for match in b_scores:
            h_act, a_act = round(match.home_score, 2), round(
                match.away_score, 2
            )
            if h_act == 0 and a_act == 0:
              continue

            h_mgr = get_manager_name(match.home_team)
            a_mgr = get_manager_name(match.away_team)
            if h_mgr == "Manager" and a_mgr == "Manager":
              continue

            pair = sorted([h_mgr, a_mgr])
            m_id = f"{y}_W{w}_{pair[0]}_vs_{pair[1]}"
            if m_id not in all_time["matchups"]:
              all_time["matchups"][m_id] = {
                  "year": y,
                  "week": w,
                  "m1": h_mgr,
                  "t1": match.home_team.team_name,
                  "s1": h_act,
                  "m2": a_mgr,
                  "t2": match.away_team.team_name,
                  "s2": a_act,
              }
        except Exception:
          break
      all_time["h2h_ingested_years"].append(y)
      print(f"Season {y} H2H matchups successfully indexed!")
    except Exception as e:
      print(f"Could not backfill Season {y} H2H: {e}")

  save_history(ALL_TIME_FILE, all_time)


def sync_champions(current_year):
  """Reaches back to 2023 to audit standings for 1st, 2nd, 3rd, and League Bitch (Last Place)."""
  all_time = load_history(
      ALL_TIME_FILE,
      {"champions": {}, "matchups": {}, "h2h_ingested_years": []},
  )
  if "champions" not in all_time:
    all_time["champions"] = {}
  all_time["champions"].update(HISTORICAL_CHAMPIONS_OVERRIDE)

  for y in range(2023, current_year + 1):
    y_str = str(y)

    try:
      past_league = League(
          league_id=LEAGUE_ID, year=y, espn_s2=ESPN_S2, swid=SWID
      )
      curr_wk = getattr(past_league, "current_week", 1)

      # Suppress in-progress season until the entire championship has finalized
      if y == current_year:
        standings = [
            getattr(t, "final_standing", 0) for t in past_league.teams
        ]
        has_champion = any(s == 1 for s in standings)
        if curr_wk <= 17 or not has_champion:
          if y_str in all_time["champions"]:
            del all_time["champions"][y_str]
          continue

      existing = all_time["champions"].get(y_str, {})
      if (
          existing.get("gold")
          and existing.get("gold") != "TBD"
          and existing.get("bronze")
          and existing.get("bronze") != "TBD"
          and existing.get("last")
          and existing.get("last") != "TBD"
      ):
        continue

      print(
          f"Auditing Season {y} for Gold, Silver, Bronze, and League Bitch..."
      )

      gold_team = next(
          (t for t in past_league.teams if getattr(t, "final_standing", 0) == 1),
          None,
      )
      silver_team = next(
          (t for t in past_league.teams if getattr(t, "final_standing", 0) == 2),
          None,
      )
      bronze_team = next(
          (t for t in past_league.teams if getattr(t, "final_standing", 0) == 3),
          None,
      )

      remaining = [
          t for t in past_league.teams if t != gold_team and t != silver_team
      ]
      remaining.sort(
          key=lambda t: (
              getattr(t, "final_standing", 99)
              if getattr(t, "final_standing", 0) > 0
              else 99,
              getattr(t, "standing", 99),
              -getattr(t, "points_for", 0),
          )
      )

      if not gold_team and past_league.teams:
        gold_team = remaining.pop(0)
      if not silver_team and remaining:
        silver_team = remaining.pop(0)
      if not bronze_team and remaining:
        bronze_team = remaining.pop(0)

      valid_standings = [
          t for t in past_league.teams if getattr(t, "final_standing", 0) > 0
      ]
      if valid_standings:
        last_team = max(valid_standings, key=lambda t: t.final_standing)
      else:
        last_team = max(
            past_league.teams,
            key=lambda t: (
                getattr(t, "standing", 0),
                -getattr(t, "points_for", 0),
            ),
        )

      def format_champ_entry(t):
        if not t:
          return "TBD"
        mgr = get_manager_name(t)
        return f"{t.team_name} ({mgr})" if mgr != "Manager" else t.team_name

      all_time["champions"][y_str] = {
          "gold": format_champ_entry(gold_team),
          "silver": format_champ_entry(silver_team),
          "bronze": format_champ_entry(bronze_team),
          "last": format_champ_entry(last_team),
      }
      print(f"Season {y} Podium Locked -> {all_time['champions'][y_str]}")
    except Exception as e:
      print(f"Historical query for Season {y} bypassed: {e}")

  save_history(ALL_TIME_FILE, all_time)
  return all_time["champions"]


def compute_all_time_leaderboard(champions):
  """Computes total podium and placement counts per manager with most recent placement note."""
  mgr_stats = {}
  sorted_years = sorted([int(y) for y in champions.keys()])

  for y in sorted_years:
    p = champions[str(y)]

    m_gold = extract_manager_from_label(p.get("gold"))
    m_silver = extract_manager_from_label(p.get("silver"))
    m_bronze = extract_manager_from_label(p.get("bronze"))
    m_last = extract_manager_from_label(p.get("last"))

    for m in [m_gold, m_silver, m_bronze, m_last]:
      if m != "Unknown" and m not in mgr_stats:
        mgr_stats[m] = {
            "manager": m,
            "gold": 0,
            "silver": 0,
            "bronze": 0,
            "last": 0,
            "total_podiums": 0,
            "most_recent": "None",
        }

    if m_gold != "Unknown":
      mgr_stats[m_gold]["gold"] += 1
      mgr_stats[m_gold]["total_podiums"] += 1
      mgr_stats[m_gold]["most_recent"] = f"🥇 Gold ({y})"

    if m_silver != "Unknown":
      mgr_stats[m_silver]["silver"] += 1
      mgr_stats[m_silver]["total_podiums"] += 1
      mgr_stats[m_silver]["most_recent"] = f"🥈 Silver ({y})"

    if m_bronze != "Unknown":
      mgr_stats[m_bronze]["bronze"] += 1
      mgr_stats[m_bronze]["total_podiums"] += 1
      mgr_stats[m_bronze]["most_recent"] = f"🥉 Bronze ({y})"

    if m_last != "Unknown":
      mgr_stats[m_last]["last"] += 1
      mgr_stats[m_last]["most_recent"] = f"💩 League Bitch ({y})"

  leaderboard = sorted(
      mgr_stats.values(),
      key=lambda x: (
          -x["gold"],
          -x["silver"],
          -x["bronze"],
          x["last"],
          x["manager"],
      ),
  )
  return leaderboard


def get_reigning_badges(champions, current_year):
  prior_year_str = str(current_year - 1)
  prior_podium = champions.get(prior_year_str, {})
  return {
      "year": prior_year_str,
      "gold": prior_podium.get("gold", ""),
      "silver": prior_podium.get("silver", ""),
      "bronze": prior_podium.get("bronze", ""),
      "last": prior_podium.get("last", ""),
  }


def render_team_badge(team_label, reigning):
  """Appends persistent reigning medal or shame pills next to manager names."""
  if not reigning:
    return team_label

  yr_short = reigning.get("year", "25")[-2:]

  def matches(target, label):
    if not target or target == "TBD":
      return False
    t_clean = target.lower().strip()
    l_clean = label.lower().strip()
    if t_clean in l_clean or l_clean in t_clean:
      return True
    if "(" in target and ")" in target:
      mgr = target.split("(")[-1].split(")")[0].strip().lower()
      if mgr and mgr != "manager" and mgr in l_clean:
        return True
      tm = target.split("(")[0].strip().lower()
      if tm and tm in l_clean:
        return True
    return False

  medals = ""
  if matches(reigning.get("gold"), team_label):
    medals += (
        f' <span class="badge badge-champ" title="{reigning.get("year")}'
        f' Champion">🥇 \'{yr_short} Champ</span>'
    )
  elif matches(reigning.get("silver"), team_label):
    medals += (
        f' <span class="badge badge-silver" title="{reigning.get("year")}'
        f' Runner-Up">🥈 \'{yr_short} Runner-Up</span>'
    )
  elif matches(reigning.get("bronze"), team_label):
    medals += (
        f' <span class="badge badge-bronze" title="{reigning.get("year")} 3rd'
        f' Place">🥉 \'{yr_short} 3rd Pl</span>'
    )
  elif matches(reigning.get("last"), team_label):
    medals += (
        f' <span class="badge badge-bitch" title="{reigning.get("year")} League'
        f' Bitch (Last Place)">💩 \'{yr_short} League Bitch</span>'
    )
  return f"{team_label}{medals}"


def update_and_compute_h2h(history, current_year):
  """Syncs current season matchups to all-time memory and computes lifetime H2H stats."""
  all_time = load_history(
      ALL_TIME_FILE,
      {"champions": {}, "matchups": {}, "h2h_ingested_years": []},
  )
  if "matchups" not in all_time:
    all_time["matchups"] = {}

  for w_str, matchups in history["weeks"].items():
    w = int(w_str)
    for m in matchups:
      mgr = m.get("manager", "Unknown")
      opp_mgr = m.get("opp_manager", "Unknown")
      if mgr == "Unknown" or opp_mgr == "Unknown":
        continue

      pair = sorted([mgr, opp_mgr])
      match_id = f"{current_year}_W{w}_{pair[0]}_vs_{pair[1]}"

      if match_id not in all_time["matchups"]:
        all_time["matchups"][match_id] = {
            "year": current_year,
            "week": w,
            "m1": mgr,
            "t1": m["team"],
            "s1": m["actual"],
            "m2": opp_mgr,
            "t2": m["opp"],
            "s2": m["opp_actual"],
        }

  save_history(ALL_TIME_FILE, all_time)

  rivalries = {}
  managers_set = set()
  season_log = []

  for m_id, g in all_time["matchups"].items():
    m1, m2 = g["m1"], g["m2"]
    s1, s2 = g["s1"], g["s2"]
    y, w = g["year"], g["week"]
    managers_set.add(m1)
    managers_set.add(m2)

    pair_key = tuple(sorted([m1, m2]))
    if pair_key not in rivalries:
      rivalries[pair_key] = {
          "m1": pair_key[0],
          "m2": pair_key[1],
          "m1_wins": 0,
          "m2_wins": 0,
          "ties": 0,
          "m1_pf": 0.0,
          "m2_pf": 0.0,
          "season_m1_wins": 0,
          "season_m2_wins": 0,
          "season_ties": 0,
          "last_meet": None,
      }

    r = rivalries[pair_key]
    r["last_meet"] = {
        "year": y,
        "week": w,
        "m1": m1,
        "s1": s1,
        "m2": m2,
        "s2": s2,
    }

    if s1 > s2:
      if m1 == r["m1"]:
        r["m1_wins"] += 1
      else:
        r["m2_wins"] += 1
      if y == current_year:
        if m1 == r["m1"]:
          r["season_m1_wins"] += 1
        else:
          r["season_m2_wins"] += 1
    elif s2 > s1:
      if m2 == r["m2"]:
        r["m2_wins"] += 1
      else:
        r["m1_wins"] += 1
      if y == current_year:
        if m2 == r["m2"]:
          r["season_m2_wins"] += 1
        else:
          r["season_m1_wins"] += 1
    else:
      r["ties"] += 1
      if y == current_year:
        r["season_ties"] += 1

    if m1 == r["m1"]:
      r["m1_pf"] += s1
      r["m2_pf"] += s2
    else:
      r["m1_pf"] += s2
      r["m2_pf"] += s1

    if y == current_year:
      season_log.append({
          "week": w,
          "m1": m1,
          "t1": g["t1"],
          "s1": s1,
          "m2": m2,
          "t2": g["t2"],
          "s2": s2,
          "margin": round(abs(s1 - s2), 2),
          "winner": m1 if s1 > s2 else (m2 if s2 > s1 else "Tie"),
      })

  season_log.sort(key=lambda x: (x["week"], -x["margin"]))
  return rivalries, sorted(list(managers_set)), season_log


def compute_trends(history):
  team_trends = {}
  weeks_sorted = sorted([int(w) for w in history["weeks"].keys()])

  for w in weeks_sorted:
    matchups = history["weeks"][str(w)]
    for entry in matchups:
      team = entry["team"]
      if team not in team_trends:
        team_trends[team] = {
            "team": team,
            "actual_w": 0,
            "actual_l": 0,
            "all_play_w": 0,
            "all_play_l": 0,
            "pf": 0.0,
            "pa": 0.0,
            "eff_history": [],
            "pine_tax": 0.0,
            "opp_over_proj_count": 0,
            "curr_opp_surge_streak": 0,
        }

      stat = team_trends[team]
      stat["pf"] += entry["actual"]
      stat["pa"] += entry["opp_actual"]
      if entry["result"] == "W":
        stat["actual_w"] += 1
      elif entry["result"] == "L":
        stat["actual_l"] += 1

      stat["all_play_w"] += entry["all_play_w"]
      stat["all_play_l"] += entry["all_play_l"]
      stat["eff_history"].append(entry["coach_eff"])
      stat["pine_tax"] += round(entry["optimal"] - entry["actual"], 2)

      opp_actual = entry.get("opp_actual", 0.0)
      opp_proj = entry.get("opp_proj", opp_actual)
      if round(opp_actual - opp_proj, 2) > 0:
        stat["opp_over_proj_count"] += 1
        stat["curr_opp_surge_streak"] += 1
      else:
        stat["curr_opp_surge_streak"] = 0

  total_weeks = len(weeks_sorted)
  for team, s in team_trends.items():
    tot_ap = s["all_play_w"] + s["all_play_l"]
    tot_act = s["actual_w"] + s["actual_l"]
    s["all_play_pct"] = (s["all_play_w"] / tot_ap) if tot_ap > 0 else 0.0
    act_pct = (s["actual_w"] / tot_act) if tot_act > 0 else 0.0
    s["luck_delta"] = round(act_pct - s["all_play_pct"], 3)
    s["avg_eff"] = (
        round(sum(s["eff_history"]) / len(s["eff_history"]), 1)
        if s["eff_history"]
        else 100.0
    )
    s["avg_pa"] = round(s["pa"] / total_weeks, 2) if total_weeks else 0.0
    s["pine_tax"] = round(s["pine_tax"], 2)

  return team_trends, total_weeks


def generate_html_report(
    week_num,
    current_week_data,
    trends_data,
    total_weeks,
    weekly_team_bounties,
    weekly_player_bounties,
    position_records,
    season_payout_leaders,
    champions,
    leaderboard,
    reigning,
    rivalries,
    managers_list,
    season_log,
):
  sorted_week = sorted(
      current_week_data, key=lambda x: (x["all_play_w"], x["actual"]), reverse=True
  )
  sorted_trends = sorted(
      trends_data.values(),
      key=lambda x: (x["all_play_w"], x["pf"]),
      reverse=True,
  )

  buzzsaw = min(
      current_week_data,
      key=lambda x: x["luck_delta"],
      default={
          "team": "None",
          "actual": 0.0,
          "opp": "None",
          "opp_actual": 0.0,
          "all_play_w": 0,
          "all_play_l": 0,
          "luck_delta": 0.0,
      },
  )
  horseshoe = max(
      current_week_data,
      key=lambda x: x["luck_delta"],
      default={
          "team": "None",
          "actual": 0.0,
          "opp": "None",
          "opp_actual": 0.0,
          "all_play_w": 0,
          "all_play_l": 0,
          "luck_delta": 0.0,
      },
  )
  tactician = max(
      current_week_data,
      key=lambda x: x["coach_eff"],
      default={
          "team": "None",
          "coach_eff": 100.0,
          "actual": 0.0,
          "optimal": 0.0,
      },
  )

  all_blunders = []
  for t in current_week_data:
    for p in t["players"]:
      if p["audit"] == "Costly Bench":
        all_blunders.append({"team": t["team"], **p})
  all_blunders.sort(key=lambda x: x["pts"], reverse=True)

  curr_bounty = (
      next((b for b in weekly_team_bounties if b["week"] == week_num), None)
      or (weekly_team_bounties[-1] if weekly_team_bounties else None)
  )

  html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0" />
  <title>The Deflaters // Week {week_num} Ledger</title>
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
      display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px;
    }}
    .header h1 {{ font-size: 22px; font-weight: 800; color: #fff; }}
    .header .subtitle {{ color: var(--accent); font-weight: 700; text-transform: uppercase; font-size: 11px; letter-spacing: 1.5px; margin-bottom: 2px; }}
    .header-controls {{ display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }}
    .header-badge {{ background: rgba(56, 189, 248, 0.1); border: 1px solid rgba(56, 189, 248, 0.25); color: var(--accent); padding: 5px 12px; border-radius: 20px; font-size: 12px; font-weight: 700; }}
    
    .theme-toggle-btn {{
      background: rgba(255, 255, 255, 0.1); border: 1px solid rgba(255, 255, 255, 0.2);
      color: #fff; padding: 6px 14px; border-radius: 20px; font-size: 12px; font-weight: 700;
      cursor: pointer; display: inline-flex; align-items: center; gap: 6px; transition: all 0.2s;
    }}
    .theme-toggle-btn:hover {{ background: rgba(255, 255, 255, 0.2); }}

    .awards-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; }}
    .award-card {{ background: var(--card); border: 1px solid var(--border); border-radius: 14px; padding: 16px; display: flex; flex-direction: column; justify-content: space-between; box-shadow: 0 2px 4px rgba(0,0,0,0.04); }}
    .award-card.red {{ border-left: 4px solid var(--red); }}
    .award-card.green {{ border-left: 4px solid var(--green); }}
    .award-card.blue {{ border-left: 4px solid var(--accent); }}
    .award-card.gold {{ border-left: 4px solid var(--gold); }}
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

    .team-name {{ font-weight: 700; color: var(--text); word-break: break-word; }}
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
    body.light-mode .badge-bitch {{ background: rgba(220, 38, 38, 0.15); color: #b91c1c; border: 1px solid rgba(220, 38, 38, 0.4); }}

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
    .glossary-example {{ margin-top: 8px; padding: 8px 10px; background: var(--card); border-radius: 8px; font-size: 12px; color: var(--text); border-left: 3px solid var(--accent); border: 1px solid var(--border); }}

    .filter-header {{ padding: 14px 16px; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; }}
    .filter-control {{ display: flex; align-items: center; gap: 8px; width: 100%; max-width: 380px; }}
    .select-dropdown {{
      flex: 1; width: 100%; background: var(--surface); color: var(--text); border: 1px solid var(--border);
      padding: 8px 12px; border-radius: 8px; font-size: 13px; font-weight: 700; cursor: pointer; outline: none;
    }}
  </style>
</head>
<body>
<div class="wrapper">
  <div class="header">
    <div>
      <div class="subtitle">The Deflaters Analytics Lab</div>
      <h1>WEEK {week_num} EXECUTIVE AUDIT</h1>
    </div>
    <div class="header-controls">
      <button id="theme-toggle" class="theme-toggle-btn" onclick="toggleTheme()">☀️ Light Mode</button>
      <div class="header-badge">Season {YEAR} (Weeks 1–{total_weeks})</div>
    </div>
  </div>

  <div class="awards-grid">
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
  </div>

  <div class="tab-bar">
    <button class="tab-btn active" onclick="switchTab('week')">📅 Week {week_num} Audit</button>
    <button class="tab-btn" onclick="switchTab('season')">📈 Season Trends</button>
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
      <tbody>"""

  for idx, t in enumerate(sorted_week, 1):
    delta_class = (
        "badge-lucky"
        if t["luck_delta"] > 0
        else ("badge-unlucky" if t["luck_delta"] < 0 else "badge-neutral")
    )
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
          <th>All-Play<span class="sub-th">True Strength</span></th>
          <th>All-Play %</th>
          <th>Season Luck Δ<span class="sub-th">Net Fortune</span></th>
          <th>Pine Tax<span class="sub-th">Total Pts Lost</span></th>
          <th>Opp Surges Faced<span class="sub-th">Over Proj (Streak)</span></th>
          <th>Avg Opp PA<span class="sub-th">Matchup Gauntlet</span></th>
        </tr>
      </thead>
      <tbody>"""

  for idx, s in enumerate(sorted_trends, 1):
    c_delta_class = (
        "badge-lucky"
        if s["luck_delta"] > 0
        else ("badge-unlucky" if s["luck_delta"] < 0 else "badge-neutral")
    )
    decorated_team = render_team_badge(s["team"], reigning)
    streak_badge = (
        f"<b>{s['curr_opp_surge_streak']} st!</b>"
        if s["curr_opp_surge_streak"] >= 2
        else f"{s['curr_opp_surge_streak']} st"
    )
    html += f"""
        <tr>
          <td class="team-cell"><span class="rank-num">#{idx}</span> {decorated_team}</td>
          <td data-label="Actual W-L"><b>{s['actual_w']}–{s['actual_l']}</b></td>
          <td data-label="All-Play">{s['all_play_w']}–{s['all_play_l']}</td>
          <td data-label="All-Play %"><b>{s['all_play_pct']:.3f}</b></td>
          <td data-label="Season Luck Δ"><span class="badge {c_delta_class}">{s['luck_delta']:+.3f}</span></td>
          <td data-label="Pine Tax" style="color: var(--amber); font-weight: 700;">{s['pine_tax']:.2f} pts</td>
          <td data-label="Opp Surges">{s['opp_over_proj_count']}/{total_weeks} wks ({streak_badge})</td>
          <td data-label="Avg Opp PA"><b>{s['avg_pa']:.2f}</b></td>
        </tr>"""

  html += f"""
      </tbody>
    </table>
  </div>

  <!-- TAB 3: HEAD-TO-HEAD LOG & MATRIX -->
  <div id="view-h2h" style="display: none; display: flex; flex-direction: column; gap: 16px;">
    
    <div class="table-container">
      <div class="filter-header">
        <div style="font-size: 14px; font-weight: 800; color: var(--text);">⚔️ All-Time Manager Rivalry Records (2023–Present)</div>
        <div class="filter-control">
          <select id="mgrFilter" class="select-dropdown" onchange="filterRivalries(this.value)">
            <option value="ALL">Show All Rivalries</option>"""

  for mgr in managers_list:
    html += f"""<option value="{mgr}">{mgr}</option>"""

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
    m1_w, m2_w = r["m1_wins"], r["m2_wins"]
    sm1_w, sm2_w = r["season_m1_wins"], r["season_m2_wins"]
    last = r["last_meet"]
    last_str = (
        f"{last['year']} Wk {last['week']}: {last['m1']} ({last['s1']:.2f}) vs"
        f" {last['m2']} ({last['s2']:.2f})"
        if last
        else "N/A"
    )

    html += f"""
          <tr class="rivalry-row" data-m1="{m1}" data-m2="{m2}">
            <td class="team-cell">{m1} vs {m2}</td>
            <td data-label="All-Time Series"><b>{m1_w}–{m2_w}</b></td>
            <td data-label="Season Series">{sm1_w}–{sm2_w}</td>
            <td data-label="PF vs PA">{r['m1_pf']:.2f} – {r['m2_pf']:.2f}</td>
            <td data-label="Last Meeting" style="color: var(--muted); font-size: 11px;">{last_str}</td>
          </tr>"""

  html += f"""
        </tbody>
      </table>
    </div>

    <!-- SEASON MATCHUP SCHEDULE LOG -->
    <div class="table-container">
      <div style="padding: 14px 16px; font-weight: 800; border-bottom: 1px solid var(--border); color: var(--text); font-size: 14px;">
        📅 Season {YEAR} Completed Matchup Log
      </div>
      <table class="responsive-table">
        <thead>
          <tr>
            <th>Week</th>
            <th>Winner</th>
            <th>Score</th>
            <th>Loser</th>
            <th>Margin</th>
          </tr>
        </thead>
        <tbody>"""

  for g in season_log:
    winner_team = g["t1"] if g["s1"] >= g["s2"] else g["t2"]
    winner_score = max(g["s1"], g["s2"])
    loser_team = g["t2"] if g["s1"] >= g["s2"] else g["t1"]
    loser_score = min(g["s1"], g["s2"])

    html += f"""
          <tr>
            <td class="team-cell" style="color: var(--accent);">Week {g['week']} Matchup</td>
            <td data-label="Winner" style="font-weight: 700; color: var(--text);">{winner_team}</td>
            <td data-label="Score" style="font-weight: 700; color: var(--green);">{winner_score:.2f} – {loser_score:.2f}</td>
            <td data-label="Loser" style="color: var(--muted);">{loser_team}</td>
            <td data-label="Margin" style="font-weight: 700; color: var(--accent);">+{g['margin']:.2f} pts</td>
          </tr>"""

  html += f"""
        </tbody>
      </table>
    </div>

  </div>

  <!-- TAB 4: PAYOUTS & POSITIONAL RECORDS -->
  <div id="view-payouts" style="display: none; display: flex; flex-direction: column; gap: 16px;">
    
    <!-- SEASON CASH BOUNTIES -->
    <div style="font-size: 15px; font-weight: 800; color: var(--text);">🏆 Season High Point Cash Bounties</div>
    <div class="awards-grid">
      <div class="award-card gold">
        <div>
          <div class="award-tag" style="color: var(--gold);">👑 Season Points Leader (Total PF)</div>
          <div class="award-title">{render_team_badge(season_payout_leaders['pf_leader_team'], reigning)}</div>
          <div class="award-desc">Pacing the entire season with <b>{season_payout_leaders['pf_leader_pts']:.2f} Total PF</b> to lead the overall scoring payout!</div>
        </div>
        <div style="margin-top: 8px;"><span class="badge badge-gold">Season PF Crown</span></div>
      </div>

      <div class="award-card blue">
        <div>
          <div class="award-tag" style="color: var(--accent);">⚡ Single-Game Team Record</div>
          <div class="award-title">{render_team_badge(season_payout_leaders['high_game_team'], reigning)}</div>
          <div class="award-desc">Hung <b>{season_payout_leaders['high_game_pts']:.2f} pts</b> in Week {season_payout_leaders['high_game_week']} for the single highest team score of the year.</div>
        </div>
        <div style="margin-top: 8px;"><span class="badge badge-neutral">Single-Week High</span></div>
      </div>

      <div class="award-card green">
        <div>
          <div class="award-tag" style="color: var(--green);">🌟 Single-Game Starter Record</div>
          <div class="award-title">{season_payout_leaders['high_player']} ({season_payout_leaders['high_player_pos']})</div>
          <div class="award-desc">Erupted for <b>{season_payout_leaders['high_player_pts']:.2f} pts</b> in Week {season_payout_leaders['high_player_week']} for {season_payout_leaders['high_player_team']}.</div>
        </div>
        <div style="margin-top: 8px;"><span class="badge badge-lucky">Season Player High</span></div>
      </div>
    </div>

    <!-- WEEKLY CASH PAYOUTS TABLE -->
    <div class="table-container">
      <div style="padding: 14px 16px; font-weight: 800; border-bottom: 1px solid var(--border); color: var(--text); font-size: 14px;">
        💵 Weekly High Scorer Cash Ledger (Team & Starter Payouts)
      </div>
      <table class="responsive-table">
        <thead>
          <tr>
            <th>Week</th>
            <th>Team High Winner ($)</th>
            <th>Score</th>
            <th>Starter High Winner ($)</th>
            <th>Player Score</th>
          </tr>
        </thead>
        <tbody>"""

  for tb in weekly_team_bounties:
    pb = next(
        (p for p in weekly_player_bounties if p["week"] == tb["week"]), None
    )
    dec_team = render_team_badge(tb["team"], reigning)
    pb_str = (
        f"{pb['player']} ({pb['pos']}) - {pb['team']}" if pb else "None"
    )
    pb_pts = f"{pb['pts']:.2f} pts" if pb else "-"

    html += f"""
          <tr>
            <td class="team-cell" style="color: var(--accent);">Week {tb['week']} Payouts</td>
            <td data-label="Team High Winner"><b>{dec_team}</b></td>
            <td data-label="Team Score" style="font-weight: 800; color: var(--gold);">{tb['pts']:.2f} pts</td>
            <td data-label="Starter High Winner"><b>{pb_str}</b></td>
            <td data-label="Player Score" style="font-weight: 800; color: var(--green);">{pb_pts}</td>
          </tr>"""

  html += """
        </tbody>
      </table>
    </div>

    <!-- POSITIONAL HIGH WATER MARKS -->
    <div style="font-size: 15px; font-weight: 800; color: var(--text); margin-top: 8px;">🔥 Single-Game Positional Records (Season Highs)</div>
    <div class="records-grid">"""

  for pos, rec in position_records.items():
    rec_display = f"{rec['pts']:.2f}" if rec["pts"] > -50 else "0.00"
    html += f"""
      <div class="record-card">
        <div class="record-pos">{pos} Record</div>
        <div class="record-pts">{rec_display}</div>
        <div class="record-holder">{rec['player']}<br><span style="color: var(--dim);">{rec['team']} (Wk {rec['week']})</span></div>
      </div>"""

  html += """
    </div>

  </div>

  <!-- TAB 5: HALL OF CHAMPIONS -->
  <div id="view-halloffame" style="display: none; display: flex; flex-direction: column; gap: 20px;">
    
    <!-- ALL-TIME FRANCHISE PLACEMENT & SHAME TABLE -->
    <div class="table-container">
      <div style="padding: 14px 16px; font-weight: 800; border-bottom: 1px solid var(--border); color: var(--text); font-size: 15px;">
        🏛️ All-Time Franchise Trophy & Shame Ledger (2023–Present)
      </div>
      <table class="responsive-table">
        <thead>
          <tr>
            <th>Manager / Franchise</th>
            <th>🥇 1st (Gold)</th>
            <th>🥈 2nd (Silver)</th>
            <th>🥉 3rd (Bronze)</th>
            <th>💩 League Bitch</th>
            <th>Total Podiums</th>
          </tr>
        </thead>
        <tbody>"""

  for row in leaderboard:
    html += f"""
          <tr>
            <td class="team-cell">
              <div>
                <b>{row['manager']}</b>
                <div style="font-size: 11px; color: var(--muted); font-weight: normal; margin-top: 2px;">Most Recent: {row['most_recent']}</div>
              </div>
            </td>
            <td data-label="🥇 1st (Gold)"><b>{row['gold']}</b></td>
            <td data-label="🥈 2nd (Silver)"><b>{row['silver']}</b></td>
            <td data-label="🥉 3rd (Bronze)"><b>{row['bronze']}</b></td>
            <td data-label="💩 League Bitch" style="color: #ef4444; font-weight: 700;">{row['last']}</td>
            <td data-label="Total Podiums"><span class="badge badge-neutral"><b>{row['total_podiums']}</b></span></td>
          </tr>"""

  html += """
        </tbody>
      </table>
    </div>

    <!-- HISTORICAL SEASON PODIUM CARDS -->
    <div class="table-container">
      <div style="padding: 14px 16px; font-weight: 800; border-bottom: 1px solid var(--border); color: var(--text); font-size: 14px;">
        🏆 Historical Season Podiums (Finalized Seasons)
      </div>
      <div class="podium-grid">"""

  sorted_champs = sorted(champions.keys(), reverse=True)
  if not sorted_champs:
    html += """<div style="padding: 20px; color: var(--muted);">No historical podium records locked in yet.</div>"""
  else:
    for c_year in sorted_champs:
      p = champions[c_year]
      html += f"""
        <div class="podium-card">
          <div class="podium-year">{c_year} Season</div>
          <div class="podium-row">
            <span>🥇 <b>Gold (Champion)</b></span>
            <span style="color: var(--gold); font-weight: 700;">{p.get('gold', 'TBD')}</span>
          </div>
          <div class="podium-row">
            <span>🥈 <b>Silver (Runner-Up)</b></span>
            <span style="color: var(--silver); font-weight: 700;">{p.get('silver', 'TBD')}</span>
          </div>
          <div class="podium-row">
            <span>🥉 <b>Bronze (3rd Place)</b></span>
            <span style="color: var(--bronze); font-weight: 700;">{p.get('bronze', 'TBD')}</span>
          </div>
          <div class="podium-row" style="border-top: 1px dashed var(--border); margin-top: 6px; padding-top: 8px;">
            <span style="color: #ef4444;">💩 <b>League Bitch (Last)</b></span>
            <span style="color: #ef4444; font-weight: 700;">{p.get('last', 'TBD')}</span>
          </div>
        </div>"""

  html += f"""
      </div>
    </div>

  </div>

  <!-- TAB 6: BENCH BLUNDERS -->
  <div id="view-blunders" class="table-container" style="display: none;">
    <table class="responsive-table">
      <thead>
        <tr>
          <th>Rank / Team</th>
          <th>Player Benched</th>
          <th>Pos</th>
          <th>Points Left on Pine</th>
          <th>Projection</th>
        </tr>
      </thead>
      <tbody>"""

  for idx, b in enumerate(all_blunders[:10], 1):
    dec_team = render_team_badge(b["team"], reigning)
    html += f"""
        <tr>
          <td class="team-cell"><span class="rank-num">#{idx}</span> {dec_team}</td>
          <td data-label="Player" style="color: var(--text); font-weight: 600;">{b['name']}</td>
          <td data-label="Pos"><span class="badge badge-neutral">{b['pos']}</span></td>
          <td data-label="Points Left" style="font-weight: 800; color: var(--amber);">{b['pts']:.2f} pts</td>
          <td data-label="Projection" style="color: var(--muted);">{b['proj']:.2f} pts</td>
        </tr>"""

  html += """
      </tbody>
    </table>
  </div>

  <!-- TAB 7: STAT DECODERS (THE GLOSSARY) -->
  <div id="view-glossary" class="table-container" style="display: none;">
    <div style="padding: 16px; font-weight: 800; border-bottom: 1px solid var(--border); color: var(--text); font-size: 15px;">
      📖 The Deflaters Analytics Handbook
    </div>
    <div class="glossary-grid">
      
      <div class="glossary-card">
        <div class="glossary-title">🪵 Pine Tax (Cumulative Bench Cost)</div>
        <div class="glossary-desc">
          Total real points surrendered to your bench across the season. It calculates the difference between your team's <b>Optimal Score</b> and your <b>Actual Score</b> each week.
        </div>
        <div class="glossary-example">
          <b>Example:</b> Started an RB who scored 4.20 pts while leaving an RB with 18.20 on the bench. That is <b>14.00 pts</b> added to your Pine Tax.
        </div>
      </div>

      <div class="glossary-card">
        <div class="glossary-title">🧲 Opp Surges Faced & Streak (X st)</div>
        <div class="glossary-desc">
          Tracks how many times an opponent significantly outperformed their projected ESPN score against you. The <b>(X st)</b> callout denotes their <b>current consecutive streak</b> of facing surging opponents.
        </div>
        <div class="glossary-example">
          <b>Example:</b> <code>6/14 wks (3 st!)</code> means opponents beat projections 6 times, currently in a 3-week streak of opponent scoring explosions.
        </div>
      </div>

      <div class="glossary-card">
        <div class="glossary-title">🍀 Luck Delta (Δ)</div>
        <div class="glossary-desc">
          Quantifies schedule luck by measuring the gap between your <b>Actual Win %</b> and your <b>All-Play Win %</b>.
        </div>
        <div class="glossary-example">
          <b>+0.450 (Lucky):</b> Winning despite bottom-half scoring.<br>
          <b>-0.500 (Unlucky):</b> Top scoring neutralized by opponent gauntlet.
        </div>
      </div>

      <div class="glossary-card">
        <div class="glossary-title">🌐 All-Play Record</div>
        <div class="glossary-desc">
          What your record would be if you played <b>every other team in the league</b> every week. It strips away schedule luck to show pure roster strength.
        </div>
        <div class="glossary-example">
          Going 11–0 in All-Play means you posted the highest score in the league that week.
        </div>
      </div>

      <div class="glossary-card">
        <div class="glossary-title">🧠 Coaching Efficiency %</div>
        <div class="glossary-desc">
          Percentage of maximum possible points started: <code>(Actual Score ÷ Optimal Lineup Score) × 100</code>.
        </div>
        <div class="glossary-example">
          <b>100%</b> means you started the mathematically best possible lineup from your roster.
        </div>
      </div>

      <div class="glossary-card">
        <div class="glossary-title">🛡️ Avg Opp PA (Matchup Gauntlet)</div>
        <div class="glossary-desc">
          Average Points Against per game. Teams at the top face the toughest weekly scoring schedules in the league.
        </div>
      </div>

    </div>
  </div>

</div>

<script>
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

  function filterRivalries(mgr) {
    var rows = document.querySelectorAll('.rivalry-row');
    for (var i = 0; i < rows.length; i++) {
      if (mgr === 'ALL') {
        rows[i].style.display = '';
      } else {
        var m1 = rows[i].getAttribute('data-m1');
        var m2 = rows[i].getAttribute('data-m2');
        if (m1 === mgr || m2 === mgr) {
          rows[i].style.display = '';
        } else {
          rows[i].style.display = 'none';
        }
      }
    }
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

  (function() {
    var savedTheme = localStorage.getItem('ff_theme');
    if (savedTheme === 'light') {
      document.body.classList.add('light-mode');
      updateThemeBtn(true);
    }
  })();
</script>
</body>
</html>"""

  with open("index.html", "w") as f:
    f.write(html)


def main():
  global WEEK
  print(
      f"Connecting to ESPN Fantasy API for League {LEAGUE_ID} (Season"
      f" {YEAR})..."
  )
  league = League(league_id=LEAGUE_ID, year=YEAR, espn_s2=ESPN_S2, swid=SWID)

  if not WEEK:
    WEEK = max(1, getattr(league, "current_week", 1) - 1)
    print(f"No week input provided. Auto-detected completed week: Week {WEEK}")

  print(f"Processing season up to Week {WEEK}...")
  history_file = f"league_history_{YEAR}.json"
  history = load_history(history_file, {"year": YEAR, "weeks": {}})

  for w in range(1, WEEK + 1):
    w_str = str(w)
    needs_ingest = (
        w_str not in history["weeks"]
        or not history["weeks"][w_str]
        or "opp_proj" not in history["weeks"][w_str][0]
        or "manager" not in history["weeks"][w_str][0]
    )
    if needs_ingest:
      print(f"Ingesting & processing Week {w}...")
      box_scores = league.box_scores(week=w)
      if not box_scores:
        continue

      w_teams = []
      for match in box_scores:
        h_act, a_act = round(match.home_score, 2), round(match.away_score, 2)
        h_proj = round(
            sum(
                p.projected_points
                for p in match.home_lineup
                if p.slot_position not in ["BE", "IR"]
            ),
            2,
        )
        a_proj = round(
            sum(
                p.projected_points
                for p in match.away_lineup
                if p.slot_position not in ["BE", "IR"]
            ),
            2,
        )

        h_players, h_opt = audit_roster(match.home_lineup, ROSTER_SLOTS, h_act)
        a_players, a_opt = audit_roster(match.away_lineup, ROSTER_SLOTS, a_act)

        h_mgr = get_manager_name(match.home_team)
        a_mgr = get_manager_name(match.away_team)

        home_label = (
            f"{match.home_team.team_name} ({h_mgr})"
            if h_mgr != "Manager"
            else match.home_team.team_name
        )
        away_label = (
            f"{match.away_team.team_name} ({a_mgr})"
            if a_mgr != "Manager"
            else match.away_team.team_name
        )

        w_teams.append({
            "team": home_label,
            "team_raw": match.home_team.team_name,
            "manager": h_mgr,
            "opp": away_label,
            "opp_raw": match.away_team.team_name,
            "opp_manager": a_mgr,
            "actual": h_act,
            "proj": h_proj,
            "diff": round(h_act - h_proj, 2),
            "opp_actual": a_act,
            "opp_proj": a_proj,
            "optimal": h_opt,
            "result": (
                "W" if h_act > a_act else ("L" if h_act < a_act else "T")
            ),
            "coach_eff": (
                round((h_act / h_opt) * 100, 1) if h_opt > 0 else 100.0
            ),
            "players": h_players,
        })

        w_teams.append({
            "team": away_label,
            "team_raw": match.away_team.team_name,
            "manager": a_mgr,
            "opp": home_label,
            "opp_raw": match.home_team.team_name,
            "opp_manager": h_mgr,
            "actual": a_act,
            "proj": a_proj,
            "diff": round(a_act - a_proj, 2),
            "opp_actual": h_act,
            "opp_proj": h_proj,
            "optimal": a_opt,
            "result": (
                "W" if a_act > h_act else ("L" if a_act < h_act else "T")
            ),
            "coach_eff": (
                round((a_act / a_opt) * 100, 1) if a_opt > 0 else 100.0
            ),
            "players": a_players,
        })

      all_scores = [t["actual"] for t in w_teams]
      total_opps = len(w_teams) - 1
      for t in w_teams:
        t["all_play_w"] = sum(1 for s in all_scores if t["actual"] > s)
        t["all_play_l"] = sum(1 for s in all_scores if t["actual"] < s)
        t["luck_delta"] = round(
            (1.0 if t["result"] == "W" else 0.0)
            - (t["all_play_w"] / total_opps),
            3,
        )

      history["weeks"][w_str] = w_teams

  save_history(history_file, history)

  current_week_data = history["weeks"].get(str(WEEK), [])
  trends_data, total_weeks = compute_trends(history)
  (
      weekly_team_bounties,
      weekly_player_bounties,
      position_records,
      season_payout_leaders,
  ) = compute_records_and_payouts(history)

  # Backfill multi-year H2H matchups from 2023 onwards
  sync_historical_h2h(YEAR)

  champions = sync_champions(YEAR)
  leaderboard = compute_all_time_leaderboard(champions)
  reigning = get_reigning_badges(champions, YEAR)
  rivalries, managers_list, season_log = update_and_compute_h2h(history, YEAR)

  generate_html_report(
      WEEK,
      current_week_data,
      trends_data,
      total_weeks,
      weekly_team_bounties,
      weekly_player_bounties,
      position_records,
      season_payout_leaders,
      champions,
      leaderboard,
      reigning,
      rivalries,
      managers_list,
      season_log,
  )
  print(
      "Audit complete! Hall of champions leaderboard, historical H2H, and"
      " awards compiled."
  )


if __name__ == "__main__":
  main()
