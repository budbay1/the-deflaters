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

# Manual legacy archive for seasons prior to automation
HISTORICAL_CHAMPIONS_OVERRIDE = {
    # "2024": {"gold": "Team Name (Owner A)", "silver": "Team Name (Owner B)", "bronze": "Team Name (Owner C)"},
    # "2023": {"gold": "Team Name (Owner D)", "silver": "Team Name (Owner E)", "bronze": "Team Name (Owner F)"},
}


def get_manager_name(team):
  """Extracts human or display name from ESPN metadata."""
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
  all_time = load_history(ALL_TIME_FILE, {"champions": {}})
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

      if round(entry["opp_actual"] - entry["opp_proj"], 2) > 0:
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
      --silver: #cbd5e1; --bronze: #d97706;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: 'Plus Jakarta Sans', -apple-system, sans-serif; background: var(--bg); color: var(--text); padding: 24px 12px; }}
    .wrapper {{ max-width: 1060px; margin: 0 auto; display: flex; flex-direction: column; gap: 24px; }}
    
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
    td {{ padding: 14px 16px; border-bottom: 1px solid rgba(255,255,255,0.04); vertical-align: middle; white-space: nowrap; }}
    tr:last-child td {{ border-bottom: none; }}
    tr:hover td {{ background: rgba(255,255,255,0.015); }}
    
    .team-name {{ font-weight: 700; color: #fff; }}
    .rank-num {{ font-size: 12px; color: var(--dim); font-weight: 800; width: 20px; }}
    .badge {{ display: inline-flex; align-items: center; padding: 3px 8px; border-radius: 6px; font-size: 11px; font-weight: 800; }}
    .badge-win {{ background: var(--green-bg); color: var(--green); }}
    .badge-loss {{ background: var(--red-bg); color: var(--red); }}
    .badge-lucky {{ background: var(--green-bg); color: var(--green); }}
    .badge-unlucky {{ background: var(--red-bg); color: var(--red); }}
    .badge-neutral {{ background: rgba(255,255,255,0.06); color: var(--muted); }}
    .badge-gold {{ background: var(--gold-bg); color: var(--gold); border: 1px solid rgba(251, 191, 36, 0.3); }}

    .podium-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; padding: 20px; }}
    .podium-card {{ background: #0d1424; border: 1px solid var(--border); border-radius: 14px; padding: 18px; }}
    .podium-year {{ font-size: 18px; font-weight: 800; color: #fff; margin-bottom: 12px; border-bottom: 1px solid var(--border); padding-bottom: 6px; }}
    .podium-row {{ display: flex; align-items: center; justify-content: space-between; padding: 8px 0; font-size: 13px; }}
    
    .records-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 14px; margin-bottom: 24px; }}
    .record-card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 14px; text-align: center; }}
    .record-pos {{ font-size: 11px; font-weight: 800; color: var(--accent); text-transform: uppercase; margin-bottom: 4px; }}
    .record-pts {{ font-size: 22px; font-weight: 800; color: #fff; }}
    .record-holder {{ font-size: 12px; color: var(--muted); margin-top: 4px; }}
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
        <div class="award-tag" style="color: var(--gold);">💰 Week {curr_bounty['week'] if curr_bounty else week_num} High Point Payout</div>
        <div class="award-title">{curr_bounty['team'] if curr_bounty else 'None'}</div>
        <div class="award-desc">Paced the entire league with <b>{curr_bounty['pts'] if curr_bounty else 0} pts</b> this week to take home the weekly cash payout!</div>
      </div>
      <div style="margin-top: 10px;"><span class="badge badge-gold">Weekly Bounty Winner</span></div>
    </div>

    <div class="award-card red">
      <div>
        <div class="award-tag" style="color: var(--red);">💀 The Buzzsaw Victim</div>
        <div class="award-title">{buzzsaw['team']}</div>
        <div class="award-desc">Dropped {buzzsaw['actual']} pts ({buzzsaw['all_play_w']}–{buzzsaw['all_play_l']} All-Play), but lost to {buzzsaw['opp']} ({buzzsaw['opp_actual']} pts).</div>
      </div>
      <div style="margin-top: 10px;"><span class="badge badge-unlucky">Luck Δ: {buzzsaw['luck_delta']:+.3f}</span></div>
    </div>

    <div class="award-card green">
      <div>
        <div class="award-tag" style="color: var(--green);">🍀 Grand Theft Victory</div>
        <div class="award-title">{horseshoe['team']}</div>
        <div class="award-desc">Squeaked by with only {horseshoe['actual']} pts ({horseshoe['all_play_w']}–{horseshoe['all_play_l']} All-Play) thanks to opponent collapse.</div>
      </div>
      <div style="margin-top: 10px;"><span class="badge badge-lucky">Luck Δ: {horseshoe['luck_delta']:+.3f}</span></div>
    </div>

    <div class="award-card blue">
      <div>
        <div class="award-tag" style="color: var(--accent);">🧠 Master Tactician</div>
        <div class="award-title">{tactician['team']}</div>
        <div class="award-desc">Optimal lineup execution of <b>{tactician['coach_eff']}%</b> ({tactician['actual']} of {tactician['optimal']} pts).</div>
      </div>
      <div style="margin-top: 10px;"><span class="badge badge-neutral">Lineup Mastery</span></div>
    </div>
  </div>

  <div class="tab-bar">
    <button class="tab-btn active" onclick="switchTab('week')">📅 Week {week_num} Audit</button>
    <button class="tab-btn" onclick="switchTab('season')">📈 Season Trends</button>
    <button class="tab-btn" onclick="switchTab('payouts')">💰 Weekly Payouts & Records</button>
    <button class="tab-btn" onclick="switchTab('halloffame')">🏆 Hall of Champions</button>
    <button class="tab-btn" onclick="switchTab('blunders')">🤡 Bench Blunders</button>
  </div>

  <!-- TAB 1: WEEKLY AUDIT -->
  <div id="view-week" class="table-container">
    <div class="table-scroll">
      <table>
        <thead><tr><th>Rank</th><th>Team</th><th>Result</th><th>Score</th><th>Opponent</th><th>All-Play</th><th>Luck Δ</th><th>Coaching Eff</th></tr></thead>
        <tbody>"""

  for idx, t in enumerate(sorted_week, 1):
    delta_class = (
        "badge-lucky"
        if t["luck_delta"] > 0
        else ("badge-unlucky" if t["luck_delta"] < 0 else "badge-neutral")
    )
    res_badge = "badge-win" if t["result"] == "W" else "badge-loss"
    html += f"""
          <tr>
            <td class="rank-num">{idx}</td>
            <td class="team-name">{t['team']}</td>
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
            <th>All-Play W-L</th>
            <th>All-Play %</th>
            <th>Season Luck Δ</th>
            <th>Pine Tax (Pts Lost)</th>
            <th>Opp Surges Faced</th>
            <th>Avg Opp PA</th>
          </tr>
        </thead>
        <tbody>"""

  for idx, s in enumerate(sorted_trends, 1):
    c_delta_class = (
        "badge-lucky"
        if s["luck_delta"] > 0
        else ("badge-unlucky" if s["luck_delta"] < 0 else "badge-neutral")
    )
    html += f"""
          <tr>
            <td class="rank-num">{idx}</td>
            <td class="team-name">{s['team']}</td>
            <td><b>{s['actual_w']}–{s['actual_l']}</b></td>
            <td>{s['all_play_w']}–{s['all_play_l']}</td>
            <td><b>{s['all_play_pct']:.3f}</b></td>
            <td><span class="badge {c_delta_class}">{s['luck_delta']:+.3f}</span></td>
            <td style="color: var(--amber); font-weight: 700;">{s['pine_tax']}</td>
            <td>{s['opp_over_proj_count']}/{total_weeks} wks ({s['curr_opp_surge_streak']} st)</td>
            <td style="font-weight: 700;">{s['avg_pa']}</td>
          </tr>"""

  html += """
        </tbody>
      </table>
    </div>
  </div>

  <!-- TAB 3: WEEKLY PAYOUTS & POSITIONAL RECORDS -->
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
    html += f"""
            <tr>
              <td style="font-weight: 800; color: var(--accent);">Week {b['week']}</td>
              <td class="team-name">{b['team']}</td>
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

  <!-- TAB 4: HALL OF CHAMPIONS -->
  <div id="view-halloffame" class="table-container" style="display: none;">
    <div style="padding: 16px 20px; font-weight: 800; border-bottom: 1px solid var(--border); color: #fff;">🏆 Historical Podium (Gold, Silver, Bronze)</div>
    <div class="podium-grid">"""

  sorted_champs = sorted(champions.keys(), reverse=True)
  if not sorted_champs:
    html += """<div style="padding: 24px; color: var(--muted);">No historical seasons locked in yet. They will appear here automatically when seasons finish or are entered into history.</div>"""
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

  <!-- TAB 5: BENCH BLUNDERS -->
  <div id="view-blunders" class="table-container" style="display: none;">
    <div class="table-scroll">
      <table>
        <thead><tr><th>Rank</th><th>Team</th><th>Player Benched</th><th>Pos</th><th>Points Left on Pine</th><th>Projection</th></tr></thead>
        <tbody>"""

  for idx, b in enumerate(all_blunders[:10], 1):
    html += f"""
          <tr>
            <td class="rank-num">{idx}</td>
            <td class="team-name">{b['team']}</td>
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
</div>

<script>
  function switchTab(viewName) {
    ['week', 'season', 'payouts', 'halloffame', 'blunders'].forEach(tab => {
      var el = document.getElementById('view-' + tab);
      if (el) el.style.display = 'none';
    });
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    
    var activeEl = document.getElementById('view-' + viewName);
    if (activeEl) activeEl.style.display = 'block';
    if (event && event.target) event.target.classList.add('active');
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
    if w_str not in history["weeks"]:
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
            "opp": away_label,
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
            "opp": home_label,
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

  generate_html_report(
      WEEK,
      current_week_data,
      trends_data,
      total_weeks,
      weekly_bounties,
      bounty_counts,
      position_records,
      champions,
  )
  print("Audit complete! Saved history and generated index.html")


if __name__ == "__main__":
  main()
