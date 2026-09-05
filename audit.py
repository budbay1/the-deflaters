import json
import os
from espn_api.football import League

# Credentials pulled from GitHub Secrets
LEAGUE_ID = int(os.environ["LEAGUE_ID"])
SWID = os.environ["SWID"]
ESPN_S2 = os.environ["ESPN_S2"]
YEAR = int(os.environ.get("YEAR", 2026))
WEEK = int(os.environ.get("WEEK", 1))

# League Roster Requirements (1 QB, 2 RB, 3 WR, 1 TE, 1 FLEX, 1 K, 1 D/ST)
ROSTER_SLOTS = {
    "QB": 1,
    "RB": 2,
    "WR": 3,
    "TE": 1,
    "FLEX": 1,
    "K": 1,
    "D/ST": 1,
}

HISTORY_FILE = f"league_history_{YEAR}.json"
ALL_TIME_FILE = "league_history_alltime.json"

HISTORICAL_CHAMPIONS_OVERRIDE = {
    # "2024": {"gold": "Team (Manager)", "silver": "Team (Manager)", "bronze": "Team (Manager)"}
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
  weekly_bounties = []
  position_records = {
      pos: {"pts": -99.0, "player": "None", "team": "None", "week": 0}
      for pos in ["QB", "RB", "WR", "TE", "K", "D/ST"]
  }

  sorted_weeks = sorted([int(w) for w in history["weeks"].keys()])

  for w in sorted_weeks:
    matchups = history["weeks"][str(w)]
    if not matchups:
      continue

    high_match = max(matchups, key=lambda x: x["actual"])
    weekly_bounties.append({
        "week": w,
        "team": high_match["team"],
        "pts": high_match["actual"],
        "opp": high_match["opp"],
        "opp_pts": high_match["opp_actual"],
    })

    for team_entry in matchups:
      team_name = team_entry["team"]
      for p in team_entry["players"]:
        if p["started"] and p["pos"] in position_records:
          if p["pts"] > position_records[p["pos"]]["pts"]:
            position_records[p["pos"]] = {
                "pts": p["pts"],
                "player": p["name"],
                "team": team_name,
                "week": w,
            }

  bounty_counts = {}
  for b in weekly_bounties:
    bounty_counts[b["team"]] = bounty_counts.get(b["team"], 0) + 1

  return weekly_bounties, bounty_counts, position_records


def sync_champions(league, current_year):
  all_time = load_history(ALL_TIME_FILE, {"champions": {}, "matchups": {}})
  all_time["champions"].update(HISTORICAL_CHAMPIONS_OVERRIDE)

  try:
    teams_with_rank = [
        t for t in league.teams if getattr(t, "final_standing", 0) > 0
    ]
    if teams_with_rank:
      ranked = sorted(teams_with_rank, key=lambda x: x.final_standing)
      year_str = str(current_year)

      def format_champ_entry(t):
        mgr = get_manager_name(t)
        return f"{t.team_name} ({mgr})" if mgr != "Manager" else t.team_name

      all_time["champions"][year_str] = {
          "gold": format_champ_entry(ranked[0]) if len(ranked) > 0 else "TBD",
          "silver": (
              format_champ_entry(ranked[1]) if len(ranked) > 1 else "TBD"
          ),
          "bronze": (
              format_champ_entry(ranked[2]) if len(ranked) > 2 else "TBD"
          ),
      }
  except Exception as e:
    print(f"Standings scan skipped: {e}")

  save_history(ALL_TIME_FILE, all_time)
  return all_time["champions"]


def get_reigning_badges(champions, current_year):
  prior_year_str = str(current_year - 1)
  prior_podium = champions.get(prior_year_str, {})
  return {
      "gold": prior_podium.get("gold", ""),
      "silver": prior_podium.get("silver", ""),
      "bronze": prior_podium.get("bronze", ""),
  }


def render_team_badge(team_label, reigning):
  """Appends persistent reigning medal pills next to manager names."""
  medals = ""
  if reigning.get("gold") and reigning["gold"] in team_label:
    medals += (
        ' <span class="badge badge-champ" title="2025 League Champion">🥇'
        " 25 Champ</span>"
    )
  elif reigning.get("silver") and reigning["silver"] in team_label:
    medals += (
        ' <span class="badge badge-silver" title="2025 Runner-Up">🥈 25'
        " Runner-Up</span>"
    )
  elif reigning.get("bronze") and reigning["bronze"] in team_label:
    medals += (
        ' <span class="badge badge-bronze" title="2025 3rd Place">🥉 25 3rd'
        " Pl</span>"
    )
  return f"{team_label}{medals}"


def update_and_compute_h2h(history, current_year):
  """Syncs all matchups to all-time memory and computes seasonal & lifetime H2H records."""
  all_time = load_history(ALL_TIME_FILE, {"champions": {}, "matchups": {}})
  if "matchups" not in all_time:
    all_time["matchups"] = {}

  # 1. Ingest matchups into permanent all-time archive
  for w_str, matchups in history["weeks"].items():
    w = int(w_str)
    for m in matchups:
      # Use sorted manager pairs to create a single canonical matchup key per game
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

  # 2. Compute aggregate pairwise stats
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
    s["avg_pa"] = round(s["pa"] / total_weeks, 1) if total_weeks else 0.0
    s["pine_tax"] = round(s["pine_tax"], 1)

  return team_trends, total_weeks


def generate_html_report(
    week_num,
    current_week_data,
    trends_data,
    total_weeks,
    weekly_bounties,
    bounty_counts,
    position_records,
    champions,
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
          "actual": 0,
          "opp": "None",
          "opp_actual": 0,
          "all_play_w": 0,
          "all_play_l": 0,
          "luck_delta": 0,
      },
  )
  horseshoe = max(
      current_week_data,
      key=lambda x: x["luck_delta"],
      default={
          "team": "None",
          "actual": 0,
          "opp": "None",
          "opp_actual": 0,
          "all_play_w": 0,
          "all_play_l": 0,
          "luck_delta": 0,
      },
  )
  tactician = max(
      current_week_data,
      key=lambda x: x["coach_eff"],
      default={"team": "None", "coach_eff": 100, "actual": 0, "optimal": 0},
  )

  all_blunders = []
  for t in current_week_data:
    for p in t["players"]:
      if p["audit"] == "Costly Bench":
        all_blunders.append({"team": t["team"], **p})
  all_blunders.sort(key=lambda x: x["pts"], reverse=True)
  top_blunder = (
      all_blunders[0]
      if all_blunders
      else {"team": "None", "name": "None", "pts": 0, "pos": ""}
  )

  curr_bounty = (
      next((b for b in weekly_bounties if b["week"] == week_num), None)
      or (weekly_bounties[-1] if weekly_bounties else None)
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
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: 'Plus Jakarta Sans', -apple-system, sans-serif; background: var(--bg); color: var(--text); padding: 24px 12px; }}
    .wrapper {{ max-width: 1080px; margin: 0 auto; display: flex; flex-direction: column; gap: 24px; }}
    
    .header {{
      background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
      border: 1px solid var(--border); border-radius: 20px; padding: 24px 28px;
      display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 16px;
    }}
    .header h1 {{ font-size: 26px; font-weight: 800; color: #fff; }}
    .header .subtitle {{ color: var(--accent); font-weight: 700; text-transform: uppercase; font-size: 11px; letter-spacing: 1.5px; margin-bottom: 4px; }}
    .header-badge {{ background: rgba(56, 189, 248, 0.1); border: 1px solid rgba(56, 189, 248, 0.25); color: var(--accent); padding: 6px 14px; border-radius: 20px; font-size: 13px; font-weight: 700; }}

    .awards-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 14px; }}
    .award-card {{ background: var(--card); border: 1px solid var(--border); border-radius: 16px; padding: 18px 20px; display: flex; flex-direction: column; justify-content: space-between; }}
    .award-card.red {{ border-left: 4px solid var(--red); }}
    .award-card.green {{ border-left: 4px solid var(--green); }}
    .award-card.blue {{ border-left: 4px solid var(--accent); }}
    .award-card.gold {{ border-left: 4px solid var(--gold); }}
    .award-tag {{ font-size: 11px; font-weight: 800; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 6px; }}
    .award-title {{ font-size: 17px; font-weight: 800; color: #fff; margin-bottom: 4px; }}
    .award-desc {{ font-size: 13px; color: var(--muted); line-height: 1.4; }}

    .tab-bar {{ display: flex; gap: 8px; background: var(--surface); padding: 6px; border-radius: 12px; border: 1px solid var(--border); overflow-x: auto; }}
    .tab-btn {{ flex: 1; padding: 10px 16px; background: none; border: none; border-radius: 8px; color: var(--muted); font-family: inherit; font-size: 13px; font-weight: 700; cursor: pointer; text-align: center; white-space: nowrap; transition: all 0.2s; }}
    .tab-btn.active {{ background: var(--card); color: #fff; border: 1px solid var(--border); }}

    .table-container {{ background: var(--card); border: 1px solid var(--border); border-radius: 16px; overflow: hidden; }}
    .table-scroll {{ overflow-x: auto; }}
    table {{ width: 100%; border-collapse: collapse; text-align: left; font-size: 13px; }}
    th {{ background: #0d1424; color: var(--muted); font-weight: 700; font-size: 11px; text-transform: uppercase; padding: 14px 16px; border-bottom: 1px solid var(--border); white-space: nowrap; }}
    th .sub-th {{ display: block; font-size: 9px; color: var(--dim); font-weight: normal; text-transform: none; margin-top: 2px; }}
    td {{ padding: 14px 16px; border-bottom: 1px solid rgba(255,255,255,0.04); vertical-align: middle; white-space: nowrap; }}
    tr:last-child td {{ border-bottom: none; }}
    tr:hover td {{ background: rgba(255,255,255,0.015); }}
    
    .team-name {{ font-weight: 700; color: #fff; }}
    .rank-num {{ font-size: 12px; color: var(--dim); font-weight: 800; width: 20px; }}
    
    .badge {{ display: inline-flex; align-items: center; padding: 3px 8px; border-radius: 6px; font-size: 11px; font-weight: 800; gap: 4px; }}
    .badge-win {{ background: var(--green-bg); color: var(--green); }}
    .badge-loss {{ background: var(--red-bg); color: var(--red); }}
    .badge-lucky {{ background: var(--green-bg); color: var(--green); }}
    .badge-unlucky {{ background: var(--red-bg); color: var(--red); }}
    .badge-neutral {{ background: rgba(255,255,255,0.06); color: var(--muted); }}
    .badge-gold {{ background: var(--gold-bg); color: var(--gold); border: 1px solid rgba(251, 191, 36, 0.3); }}
    .badge-champ {{ background: var(--gold-bg); color: var(--gold); border: 1px solid rgba(251, 191, 36, 0.4); font-size: 10px; padding: 2px 6px; }}
    .badge-silver {{ background: var(--silver-bg); color: var(--silver); border: 1px solid rgba(203, 213, 225, 0.4); font-size: 10px; padding: 2px 6px; }}
    .badge-bronze {{ background: var(--bronze-bg); color: var(--bronze); border: 1px solid rgba(217, 119, 6, 0.4); font-size: 10px; padding: 2px 6px; }}

    .podium-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; padding: 20px; }}
    .podium-card {{ background: #0d1424; border: 1px solid var(--border); border-radius: 14px; padding: 18px; }}
    .podium-year {{ font-size: 18px; font-weight: 800; color: #fff; margin-bottom: 12px; border-bottom: 1px solid var(--border); padding-bottom: 6px; }}
    .podium-row {{ display: flex; align-items: center; justify-content: space-between; padding: 8px 0; font-size: 13px; }}
    
    .records-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 14px; margin-bottom: 24px; }}
    .record-card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 14px; text-align: center; }}
    .record-pos {{ font-size: 11px; font-weight: 800; color: var(--accent); text-transform: uppercase; margin-bottom: 4px; }}
    .record-pts {{ font-size: 22px; font-weight: 800; color: #fff; }}
    .record-holder {{ font-size: 12px; color: var(--muted); margin-top: 4px; }}

    .glossary-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 16px; padding: 24px; }}
    .glossary-card {{ background: #0d1424; border: 1px solid var(--border); border-radius: 14px; padding: 20px; }}
    .glossary-title {{ font-size: 16px; font-weight: 800; color: #fff; margin-bottom: 8px; display: flex; align-items: center; gap: 8px; }}
    .glossary-desc {{ font-size: 13px; color: var(--muted); line-height: 1.5; }}
    .glossary-example {{ margin-top: 10px; padding: 8px 12px; background: var(--surface); border-radius: 8px; font-size: 12px; color: var(--text); border-left: 3px solid var(--accent); }}

    /* H2H Filter Header */
    .filter-header {{ padding: 16px 20px; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; }}
    .select-dropdown {{ background: var(--surface); color: var(--text); border: 1px solid var(--border); padding: 8px 14px; border-radius: 8px; font-size: 13px; font-weight: 700; cursor: pointer; outline: none; }}
  </style>
</head>
<body>
<div class="wrapper">
  <div class="header">
    <div>
      <div class="subtitle">The Deflaters Analytics Lab</div>
      <h1>WEEK {week_num} EXECUTIVE AUDIT</h1>
    </div>
    <div class="header-badge">Season {YEAR} (Weeks 1–{total_weeks})</div>
  </div>

  <div class="awards-grid">
    <div class="award-card gold">
      <div>
        <div class="award-tag" style="color: var(--gold);">💰 Week {curr_bounty['week'] if curr_bounty else week_num} High Point Bounty</div>
        <div class="award-title">{render_team_badge(curr_bounty['team'] if curr_bounty else 'None', reigning)}</div>
        <div class="award-desc">Paced the entire league with <b>{curr_bounty['pts'] if curr_bounty else 0} pts</b> to take down the weekly cash payout!</div>
      </div>
      <div style="margin-top: 10px;"><span class="badge badge-gold">Weekly Bounty Winner</span></div>
    </div>

    <div class="award-card red">
      <div>
        <div class="award-tag" style="color: var(--red);">💀 The Buzzsaw Victim</div>
        <div class="award-title">{render_team_badge(buzzsaw['team'], reigning)}</div>
        <div class="award-desc">Dropped {buzzsaw['actual']} pts ({buzzsaw['all_play_w']}–{buzzsaw['all_play_l']} All-Play), but took an L to {buzzsaw['opp']} ({buzzsaw['opp_actual']} pts).</div>
      </div>
      <div style="margin-top: 10px;"><span class="badge badge-unlucky">Luck Δ: {buzzsaw['luck_delta']:+.3f}</span></div>
    </div>

    <div class="award-card green">
      <div>
        <div class="award-tag" style="color: var(--green);">🍀 Grand Theft Victory</div>
        <div class="award-title">{render_team_badge(horseshoe['team'], reigning)}</div>
        <div class="award-desc">Squeaked by with {horseshoe['actual']} pts ({horseshoe['all_play_w']}–{horseshoe['all_play_l']} All-Play) thanks to opponent meltdown.</div>
      </div>
      <div style="margin-top: 10px;"><span class="badge badge-lucky">Luck Δ: {horseshoe['luck_delta']:+.3f}</span></div>
    </div>

    <div class="award-card blue">
      <div>
        <div class="award-tag" style="color: var(--accent);">🧠 Master Tactician</div>
        <div class="award-title">{render_team_badge(tactician['team'], reigning)}</div>
        <div class="award-desc">Optimal starting execution of <b>{tactician['coach_eff']}%</b> ({tactician['actual']} of {tactician['optimal']} optimal pts).</div>
      </div>
      <div style="margin-top: 10px;"><span class="badge badge-neutral">Lineup Mastery</span></div>
    </div>
  </div>

  <div class="tab-bar">
    <button class="tab-btn active" onclick="switchTab('week')">📅 Week {week_num} Audit</button>
    <button class="tab-btn" onclick="switchTab('season')">📈 Season Trends</button>
    <button class="tab-btn" onclick="switchTab('h2h')">⚔️ Head-to-Head</button>
    <button class="tab-btn" onclick="switchTab('payouts')">💰 Weekly Payouts & Records</button>
    <button class="tab-btn" onclick="switchTab('halloffame')">🏆 Hall of Champions</button>
    <button class="tab-btn" onclick="switchTab('blunders')">🤡 Bench Blunders</button>
    <button class="tab-btn" onclick="switchTab('glossary')">📖 Stat Decoders</button>
  </div>

  <!-- TAB 1: WEEK AUDIT -->
  <div id="view-week" class="table-container">
    <div class="table-scroll">
      <table>
        <thead>
          <tr>
            <th>Rank</th>
            <th>Team</th>
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
            <td class="rank-num">{idx}</td>
            <td class="team-name">{decorated_team}</td>
            <td><span class="badge {res_badge}">{t['result']}</span></td>
            <td style="font-weight: 700;">{t['actual']} <span style="font-size: 11px; color: var(--dim); font-weight: normal;">({t['diff']:+0.1f})</span></td>
            <td>{t['opp']} <span style="color: var(--muted); font-size: 11px;">({t['opp_actual']})</span></td>
            <td><b>{t['all_play_w']}</b>–{t['all_play_l']}</td>
            <td><span class="badge {delta_class}">{t['luck_delta']:+.3f}</span></td>
            <td>{t['coach_eff']}%</td>
          </tr>"""

  html += f"""
        </tbody>
      </table>
    </div>
  </div>

  <!-- TAB 2: SEASON TRENDS -->
  <div id="view-season" class="table-container" style="display: none;">
    <div class="table-scroll">
      <table>
        <thead>
          <tr>
            <th>Rank</th>
            <th>Team</th>
            <th>Actual W-L</th>
            <th>All-Play<span class="sub-th">True Strength</span></th>
            <th>All-Play %</th>
            <th>Season Luck Δ<span class="sub-th">Net Fortune</span></th>
            <th>Pine Tax<span class="sub-th">Total Pts Lost</span></th>
            <th>Opp Surges Faced<span class="sub-th">Over Proj (Active Streak)</span></th>
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
        f"<b>{s['curr_opp_surge_streak']} straight!</b>"
        if s["curr_opp_surge_streak"] >= 2
        else f"{s['curr_opp_surge_streak']} st"
    )
    html += f"""
          <tr>
            <td class="rank-num">{idx}</td>
            <td class="team-name">{decorated_team}</td>
            <td><b>{s['actual_w']}–{s['actual_l']}</b></td>
            <td>{s['all_play_w']}–{s['all_play_l']}</td>
            <td><b>{s['all_play_pct']:.3f}</b></td>
            <td><span class="badge {c_delta_class}">{s['luck_delta']:+.3f}</span></td>
            <td style="color: var(--amber); font-weight: 700;">{s['pine_tax']} pts</td>
            <td>{s['opp_over_proj_count']}/{total_weeks} wks ({streak_badge})</td>
            <td style="font-weight: 700;">{s['avg_pa']}</td>
          </tr>"""

  html += f"""
        </tbody>
      </table>
    </div>
  </div>

  <!-- TAB 3: HEAD-TO-HEAD LOG & MATRIX -->
  <div id="view-h2h" style="display: none;">
    
    <div class="table-container" style="margin-bottom: 24px;">
      <div class="filter-header">
        <div style="font-size: 15px; font-weight: 800; color: #fff;">⚔️ All-Time Manager Rivalry Records</div>
        <div>
          <label style="font-size: 12px; color: var(--muted); font-weight: 700; margin-right: 8px;">Filter by Manager:</label>
          <select id="mgrFilter" class="select-dropdown" onchange="filterRivalries(this.value)">
            <option value="ALL">Show All Rivalries</option>"""

  for mgr in managers_list:
    html += f"""<option value="{mgr}">{mgr}</option>"""

  html += """
          </select>
        </div>
      </div>
      <div class="table-scroll">
        <table id="rivalryTable">
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
        f"{last['year']} Wk {last['week']}: {last['m1']} ({last['s1']}) vs"
        f" {last['m2']} ({last['s2']})"
        if last
        else "N/A"
    )

    html += f"""
            <tr class="rivalry-row" data-m1="{m1}" data-m2="{m2}">
              <td class="team-name"><b>{m1}</b> vs <b>{m2}</b></td>
              <td><b>{m1_w}–{m2_w}</b></td>
              <td>{sm1_w}–{sm2_w}</td>
              <td>{r['m1_pf']:.1f} vs {r['m2_pf']:.1f}</td>
              <td style="color: var(--muted); font-size: 12px;">{last_str}</td>
            </tr>"""

  html += f"""
          </tbody>
        </table>
      </div>
    </div>

    <!-- SEASON MATCHUP SCHEDULE LOG -->
    <div class="table-container">
      <div style="padding: 16px 20px; font-weight: 800; border-bottom: 1px solid var(--border); color: #fff;">
        📅 Season {YEAR} Completed Matchup Log
      </div>
      <div class="table-scroll">
        <table>
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
              <td style="font-weight: 800; color: var(--accent);">Week {g['week']}</td>
              <td class="team-name">{winner_team}</td>
              <td style="font-weight: 700; color: var(--green);">{winner_score} – {loser_score}</td>
              <td style="color: var(--muted);">{loser_team}</td>
              <td style="font-weight: 700; color: var(--accent);">+{g['margin']} pts</td>
            </tr>"""

  html += """
          </tbody>
        </table>
      </div>
    </div>

  </div>

  <!-- TAB 4: PAYOUTS & POSITIONAL RECORDS -->
  <div id="view-payouts" style="display: none;">
    <div style="font-size: 16px; font-weight: 800; margin-bottom: 12px; color: #fff;">🔥 Single-Game Positional Records (Season Highs)</div>
    <div class="records-grid">"""

  for pos, rec in position_records.items():
    html += f"""
      <div class="record-card">
        <div class="record-pos">{pos} Record</div>
        <div class="record-pts">{rec['pts'] if rec['pts'] > -50 else '0.0'}</div>
        <div class="record-holder">{rec['player']}<br><span style="color: var(--dim);">{rec['team']} (Wk {rec['week']})</span></div>
      </div>"""

  html += """
    </div>

    <div class="table-container">
      <div style="padding: 16px 20px; font-weight: 800; border-bottom: 1px solid var(--border); color: #fff;">💵 Weekly High Scorer Cash Ledger</div>
      <div class="table-scroll">
        <table>
          <thead><tr><th>Week</th><th>High Point Winner</th><th>Score</th><th>Matchup Opponent</th><th>Opp Score</th></tr></thead>
          <tbody>"""

  for b in weekly_bounties:
    dec_team = render_team_badge(b["team"], reigning)
    html += f"""
            <tr>
              <td style="font-weight: 800; color: var(--accent);">Week {b['week']}</td>
              <td class="team-name">{dec_team}</td>
              <td style="font-weight: 800; color: var(--gold);">{b['pts']} pts</td>
              <td>vs {b['opp']}</td>
              <td style="color: var(--muted);">{b['opp_pts']} pts</td>
            </tr>"""

  html += """
          </tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- TAB 5: HALL OF CHAMPIONS -->
  <div id="view-halloffame" class="table-container" style="display: none;">
    <div style="padding: 16px 20px; font-weight: 800; border-bottom: 1px solid var(--border); color: #fff;">🏆 Historical Podium (Gold, Silver, Bronze)</div>
    <div class="podium-grid">"""

  sorted_champs = sorted(champions.keys(), reverse=True)
  if not sorted_champs:
    html += """<div style="padding: 24px; color: var(--muted);">No historical podium records locked in yet.</div>"""
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
        </div>"""

  html += f"""
    </div>
  </div>

  <!-- TAB 6: BENCH BLUNDERS -->
  <div id="view-blunders" class="table-container" style="display: none;">
    <div class="table-scroll">
      <table>
        <thead><tr><th>Rank</th><th>Team</th><th>Player Benched</th><th>Pos</th><th>Points Left on Pine</th><th>Projection</th></tr></thead>
        <tbody>"""

  for idx, b in enumerate(all_blunders[:10], 1):
    dec_team = render_team_badge(b["team"], reigning)
    html += f"""
          <tr>
            <td class="rank-num">{idx}</td>
            <td class="team-name">{dec_team}</td>
            <td style="color: #fff; font-weight: 600;">{b['name']}</td>
            <td><span class="badge badge-neutral">{b['pos']}</span></td>
            <td style="font-weight: 800; color: var(--amber);">{b['pts']} pts</td>
            <td style="color: var(--muted);">{b['proj']} pts</td>
          </tr>"""

  html += """
        </tbody>
      </table>
    </div>
  </div>

  <!-- TAB 7: STAT DECODERS (THE GLOSSARY) -->
  <div id="view-glossary" class="table-container" style="display: none;">
    <div style="padding: 18px 24px; font-weight: 800; border-bottom: 1px solid var(--border); color: #fff; font-size: 16px;">
      📖 The Deflaters Analytics Handbook
    </div>
    <div class="glossary-grid">
      
      <div class="glossary-card">
        <div class="glossary-title">🪵 Pine Tax (Cumulative Bench Cost)</div>
        <div class="glossary-desc">
          The total number of real points surrendered to your bench across the season. It calculates the difference between your team's <b>Optimal Score</b> and your <b>Actual Score</b> each week.
        </div>
        <div class="glossary-example">
          <b>Example:</b> You started an RB who scored 4.2 pts while leaving an RB with 18.2 on your bench. That is <b>14.0 pts</b> added to your Pine Tax.
        </div>
      </div>

      <div class="glossary-card">
        <div class="glossary-title">🧲 Opp Surges Faced & Streak (X st)</div>
        <div class="glossary-desc">
          Tracks how many times an opponent significantly outperformed their projected ESPN score when facing you. The <b>(X st)</b> callout denotes their <b>current consecutive streak</b> of facing surging opponents.
        </div>
        <div class="glossary-example">
          <b>Example:</b> <code>6/14 wks (3 straight!)</code> means your opponent beat their projection 6 times this year, and you are currently in a 3-week stretch where opponents are spiking against you.
        </div>
      </div>

      <div class="glossary-card">
        <div class="glossary-title">🍀 Luck Delta (Δ)</div>
        <div class="glossary-desc">
          Quantifies schedule luck by measuring the gap between your <b>Actual Win %</b> and your <b>All-Play Win %</b>.
        </div>
        <div class="glossary-example">
          <b>+0.450 (Lucky):</b> Escaping with wins despite bottom-half scoring.<br>
          <b>-0.500 (Unlucky):</b> Putting up top scores but getting buzzsawed by the #1 scorer.
        </div>
      </div>

      <div class="glossary-card">
        <div class="glossary-title">🌐 All-Play Record</div>
        <div class="glossary-desc">
          What your record would be if you played <b>every other team in the league</b> every single week. It strips away schedule bias to reveal your roster's true scoring caliber.
        </div>
        <div class="glossary-example">
          In a 12-team league, going 11–0 in All-Play means you put up the absolute highest score of the week.
        </div>
      </div>

      <div class="glossary-card">
        <div class="glossary-title">🧠 Coaching Efficiency %</div>
        <div class="glossary-desc">
          The percentage of maximum possible points you successfully started. Calculated as: <code>(Actual Score ÷ Optimal Lineup Score) × 100</code>.
        </div>
        <div class="glossary-example">
          A score of <b>100%</b> means you started the mathematically best possible lineup out of everyone on your roster.
        </div>
      </div>

      <div class="glossary-card">
        <div class="glossary-title">🛡️ Avg Opp PA (Matchup Gauntlet)</div>
        <div class="glossary-desc">
          Average Points Against per game. Teams at the top of this list have faced the most brutal schedules in the league, regardless of their win-loss record.
        </div>
      </div>

    </div>
  </div>

</div>

<script>
  function switchTab(viewName) {
    ['week', 'season', 'h2h', 'payouts', 'halloffame', 'blunders', 'glossary'].forEach(tab => {
      var el = document.getElementById('view-' + tab);
      if (el) el.style.display = 'none';
    });
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    
    var activeEl = document.getElementById('view-' + viewName);
    if (activeEl) activeEl.style.display = 'block';
    if (event && event.target) event.target.classList.add('active');
  }

  function filterRivalries(mgr) {
    var rows = document.querySelectorAll('.rivalry-row');
    rows.forEach(r => {
      if (mgr === 'ALL') {
        r.style.display = '';
      } else {
        var m1 = r.getAttribute('data-m1');
        var m2 = r.getAttribute('data-m2');
        if (m1 === mgr || m2 === mgr) {
          r.style.display = '';
        } else {
          r.style.display = 'none';
        }
      }
    });
  }
</script>
</body>
</html>"""

  with open("index.html", "w") as f:
    f.write(html)


def main():
  print(
      f"Connecting to ESPN Fantasy API for League {LEAGUE_ID} (Season {YEAR},"
      f" Up to Week {WEEK})..."
  )
  league = League(league_id=LEAGUE_ID, year=YEAR, espn_s2=ESPN_S2, swid=SWID)
  history = load_history(HISTORY_FILE, {"year": YEAR, "weeks": {}})

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

  save_history(HISTORY_FILE, history)

  current_week_data = history["weeks"].get(str(WEEK), [])
  trends_data, total_weeks = compute_trends(history)
  weekly_bounties, bounty_counts, position_records = (
      compute_records_and_payouts(history)
  )

  champions = sync_champions(league, YEAR)
  reigning = get_reigning_badges(champions, YEAR)
  rivalries, managers_list, season_log = update_and_compute_h2h(history, YEAR)

  generate_html_report(
      WEEK,
      current_week_data,
      trends_data,
      total_weeks,
      weekly_bounties,
      bounty_counts,
      position_records,
      champions,
      reigning,
      rivalries,
      managers_list,
      season_log,
  )
  print(
      "Audit complete! Generated index.html with Head-to-Head rivalries &"
      " logs."
  )


if __name__ == "__main__":
  main()
