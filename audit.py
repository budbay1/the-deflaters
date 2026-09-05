import json
import os
from espn_api.football import League

# 1. Credentials loaded securely from GitHub Secrets
LEAGUE_ID = int(os.environ["LEAGUE_ID"])
SWID = os.environ["SWID"]
ESPN_S2 = os.environ["ESPN_S2"]
YEAR = int(os.environ.get("YEAR", 2026))
WEEK = int(os.environ.get("WEEK", 1))

# 2. Your League Roster Setup (3 WR + 1 FLEX)
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

  remaining_flex = [
      p
      for p in (
          rbs[slots.get("RB", 2) :]
          + wrs[slots.get("WR", 3) :]
          + tes[slots.get("TE", 1) :]
      )
  ]
  remaining_flex.sort(key=lambda x: x.points, reverse=True)
  for p in remaining_flex[: slots.get("FLEX", 1)]:
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
        "pos": p.position,
        "audit": audit,
        "pts": pts,
        "proj": proj,
    })

  calc_optimal = round(
      sum(p.points for p in lineup if p.playerId in optimal_ids), 2
  )
  return players_data, max(actual_score, calc_optimal)


def load_history():
  if os.path.exists(HISTORY_FILE):
    with open(HISTORY_FILE, "r") as f:
      return json.load(f)
  return {"year": YEAR, "weeks": {}}


def save_history(history):
  with open(HISTORY_FILE, "w") as f:
    json.dump(history, f, indent=2)


def generate_html_report(week_num, current_week_data, cumulative_data):
  sorted_week = sorted(
      current_week_data, key=lambda x: (x["all_play_w"], x["actual"]), reverse=True
  )
  buzzsaw = min(current_week_data, key=lambda x: x["luck_delta"])
  horseshoe = max(current_week_data, key=lambda x: x["luck_delta"])
  tactician = max(current_week_data, key=lambda x: x["coach_eff"])

  all_blunders = []
  for t in current_week_data:
    for p in t["players"]:
      if p["audit"] == "Costly Bench":
        all_blunders.append({
            "team": t["team"],
            "name": p["name"],
            "pos": p["pos"],
            "pts": p["pts"],
            "proj": p["proj"],
        })
  all_blunders.sort(key=lambda x: x["pts"], reverse=True)
  top_blunder = (
      all_blunders[0]
      if all_blunders
      else {"team": "None", "name": "None", "pts": 0, "pos": ""}
  )

  html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no" />
  <title>The Deflaters // Week {week_num} Audit</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;600;700;800&display=swap" rel="stylesheet">
  <style>
    :root {{
      --bg: #070a13; --surface: #111827; --card: #151f32; --border: #24324d;
      --text: #f1f5f9; --muted: #94a3b8; --dim: #475569; --accent: #38bdf8;
      --green: #10b981; --green-bg: rgba(16, 185, 129, 0.12);
      --red: #f43f5e; --red-bg: rgba(244, 63, 94, 0.12);
      --amber: #f59e0b; --amber-bg: rgba(245, 158, 11, 0.12);
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: 'Plus Jakarta Sans', -apple-system, sans-serif;
      background-color: var(--bg); color: var(--text); line-height: 1.5; padding: 24px 12px;
    }}
    .wrapper {{ max-width: 1040px; margin: 0 auto; display: flex; flex-direction: column; gap: 24px; }}
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
    .award-card.amber {{ border-left: 4px solid var(--amber); }}
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
    .eff-box {{ display: flex; align-items: center; gap: 8px; }}
    .eff-bar-bg {{ width: 50px; height: 6px; background: rgba(255,255,255,0.08); border-radius: 3px; overflow: hidden; }}
    .eff-bar-fill {{ height: 100%; background: var(--accent); border-radius: 3px; }}
  </style>
</head>
<body>
<div class="wrapper">
  <div class="header">
    <div><div class="subtitle">The Deflaters Fantasy Football</div><h1>WEEK {week_num} AUDIT DOSSIER</h1></div>
    <div class="header-badge">Season {YEAR}</div>
  </div>

  <div class="awards-grid">
    <div class="award-card red">
      <div>
        <div class="award-tag" style="color: var(--red);">💀 The Buzzsaw Victim</div>
        <div class="award-title">{buzzsaw['team']}</div>
        <div class="award-desc">Poured on <b>{buzzsaw['actual']} pts</b> (All-Play {buzzsaw['all_play_w']}–{buzzsaw['all_play_l']}), beatable by almost no one—except opponent {buzzsaw['opp']} ({buzzsaw['opp_actual']} pts).</div>
      </div>
      <div style="margin-top: 10px;"><span class="badge badge-unlucky">Luck Delta: {buzzsaw['luck_delta']:+.3f}</span></div>
    </div>

    <div class="award-card green">
      <div>
        <div class="award-tag" style="color: var(--green);">🍀 Grand Theft Victory</div>
        <div class="award-title">{horseshoe['team']}</div>
        <div class="award-desc">Stumbled to <b>{horseshoe['actual']} pts</b> (All-Play {horseshoe['all_play_w']}–{horseshoe['all_play_l']}), yet walked away with a win due to opponent collapse.</div>
      </div>
      <div style="margin-top: 10px;"><span class="badge badge-lucky">Luck Delta: {horseshoe['luck_delta']:+.3f}</span></div>
    </div>

    <div class="award-card blue">
      <div>
        <div class="award-tag" style="color: var(--accent);">🧠 Master Tactician</div>
        <div class="award-title">{tactician['team']}</div>
        <div class="award-desc">Achieved a league-high <b>{tactician['coach_eff']}%</b> coaching efficiency, extracting {tactician['actual']} of {tactician['optimal']} possible optimal points.</div>
      </div>
      <div style="margin-top: 10px;"><span class="badge badge-neutral">Lineup Mastery</span></div>
    </div>

    <div class="award-card amber">
      <div>
        <div class="award-tag" style="color: var(--amber);">🤡 Bench Warmers Award</div>
        <div class="award-title">{top_blunder['team']}</div>
        <div class="award-desc">Left <b>{top_blunder['name']} ({top_blunder['pts']} pts, {top_blunder['pos']})</b> sitting on the bench as an unused optimal starter.</div>
      </div>
      <div style="margin-top: 10px;"><span class="badge badge-neutral">Unused Potential</span></div>
    </div>
  </div>

  <div class="tab-bar">
    <button class="tab-btn active" onclick="switchTab('week')">📅 Week {week_num} Audit</button>
    <button class="tab-btn" onclick="switchTab('season')">🏆 Cumulative Season Standings</button>
    <button class="tab-btn" onclick="switchTab('blunders')">🤡 Top Bench Blunders</button>
  </div>

  <div id="view-week" class="table-container">
    <div class="table-scroll">
      <table>
        <thead><tr><th>Rank</th><th>Team</th><th>Result</th><th>Score</th><th>Opponent</th><th>All-Play</th><th>Luck Delta</th><th>Coaching Eff</th></tr></thead>
        <tbody>"""

  for idx, t in enumerate(sorted_week, 1):
    delta_class = (
        "badge-lucky"
        if t["luck_delta"] > 0
        else ("badge-unlucky" if t["luck_delta"] < 0 else "badge-neutral")
    )
    res_badge = "badge-win" if t["result"] == "W" else "badge-loss"
    eff_pct = min(100, max(0, t["coach_eff"]))
    html += f"""
          <tr>
            <td class="rank-num">{idx}</td>
            <td class="team-name">{t['team']}</td>
            <td><span class="badge {res_badge}">{t['result']}</span></td>
            <td style="font-weight: 700;">{t['actual']} <span style="font-size: 11px; color: var(--dim); font-weight: normal;">({t['diff']:+0.1f})</span></td>
            <td>{t['opp']} <span style="color: var(--muted); font-size: 11px;">({t['opp_actual']})</span></td>
            <td><b>{t['all_play_w']}</b>–{t['all_play_l']}</td>
            <td><span class="badge {delta_class}">{t['luck_delta']:+.3f}</span></td>
            <td>
              <div class="eff-box">
                <span>{t['coach_eff']}%</span>
                <div class="eff-bar-bg"><div class="eff-bar-fill" style="width: {eff_pct}%;"></div></div>
              </div>
            </td>
          </tr>"""

  html += f"""
        </tbody>
      </table>
    </div>
  </div>

  <div id="view-season" class="table-container" style="display: none;">
    <div class="table-scroll">
      <table>
        <thead><tr><th>Rank</th><th>Team</th><th>Actual W-L</th><th>All-Play W-L</th><th>All-Play %</th><th>Season Luck Δ</th><th>Total PF</th><th>Avg Eff</th></tr></thead>
        <tbody>"""

  sorted_cum = sorted(
      cumulative_data.values(),
      key=lambda x: (x["all_play_w"], x["pf"]),
      reverse=True,
  )
  for idx, c in enumerate(sorted_cum, 1):
    c_delta_class = (
        "badge-lucky"
        if c["luck_delta"] > 0
        else ("badge-unlucky" if c["luck_delta"] < 0 else "badge-neutral")
    )
    html += f"""
          <tr>
            <td class="rank-num">{idx}</td>
            <td class="team-name">{c['team']}</td>
            <td><b>{c['actual_w']}–{c['actual_l']}</b></td>
            <td>{c['all_play_w']}–{c['all_play_l']}</td>
            <td><b>{c['all_play_pct']:.3f}</b></td>
            <td><span class="badge {c_delta_class}">{c['luck_delta']:+.3f}</span></td>
            <td style="font-weight: 700;">{c['pf']:.1f}</td>
            <td>{c['avg_eff']:.1f}%</td>
          </tr>"""

  html += """
        </tbody>
      </table>
    </div>
  </div>

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
    document.getElementById('view-week').style.display = 'none';
    document.getElementById('view-season').style.display = 'none';
    document.getElementById('view-blunders').style.display = 'none';
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    if (viewName === 'week') {
      document.getElementById('view-week').style.display = 'block';
      event.target.classList.add('active');
    } else if (viewName === 'season') {
      document.getElementById('view-season').style.display = 'block';
      event.target.classList.add('active');
    } else if (viewName === 'blunders') {
      document.getElementById('view-blunders').style.display = 'block';
      event.target.classList.add('active');
    }
  }
</script>
</body>
</html>"""

  with open("index.html", "w") as f:
    f.write(html)


def main():
  print(f"Connecting to ESPN Fantasy API for League {LEAGUE_ID} (Week {WEEK})...")
  league = League(league_id=LEAGUE_ID, year=YEAR, espn_s2=ESPN_S2, swid=SWID)

  box_scores = league.box_scores(week=WEEK)
  week_teams = []

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

    week_teams.append({
        "team": match.home_team.team_name,
        "opp": match.away_team.team_name,
        "actual": h_act,
        "proj": h_proj,
        "diff": round(h_act - h_proj, 2),
        "opp_actual": a_act,
        "optimal": h_opt,
        "result": (
            "W"
            if h_act > a_act
            else ("L" if h_act < a_act else "T")
        ),
        "coach_eff": round((h_act / h_opt) * 100, 1) if h_opt > 0 else 100.0,
        "players": h_players,
    })

    week_teams.append({
        "team": match.away_team.team_name,
        "opp": match.home_team.team_name,
        "actual": a_act,
        "proj": a_proj,
        "diff": round(a_act - a_proj, 2),
        "opp_actual": h_act,
        "optimal": a_opt,
        "result": (
            "W"
            if a_act > h_act
            else ("L" if a_act < h_act else "T")
        ),
        "coach_eff": round((a_act / a_opt) * 100, 1) if a_opt > 0 else 100.0,
        "players": a_players,
    })

  all_scores = [t["actual"] for t in week_teams]
  total_opps = len(week_teams) - 1
  for t in week_teams:
    t["all_play_w"] = sum(1 for s in all_scores if t["actual"] > s)
    t["all_play_l"] = sum(1 for s in all_scores if t["actual"] < s)
    t["luck_delta"] = round(
        (1.0 if t["result"] == "W" else 0.0) - (t["all_play_w"] / total_opps), 3
    )

  # Update persistent database
  history = load_history()
  history["weeks"][str(WEEK)] = week_teams
  save_history(history)

  # Calculate cumulative season totals
  cum_stats = {}
  for w_num, w_data in history["weeks"].items():
    for entry in w_data:
      name = entry["team"]
      if name not in cum_stats:
        cum_stats[name] = {
            "team": name,
            "actual_w": 0,
            "actual_l": 0,
            "all_play_w": 0,
            "all_play_l": 0,
            "pf": 0.0,
            "eff_list": [],
        }
      if entry["result"] == "W":
        cum_stats[name]["actual_w"] += 1
      elif entry["result"] == "L":
        cum_stats[name]["actual_l"] += 1
      cum_stats[name]["all_play_w"] += entry["all_play_w"]
      cum_stats[name]["all_play_l"] += entry["all_play_l"]
      cum_stats[name]["pf"] += entry["actual"]
      cum_stats[name]["eff_list"].append(entry["coach_eff"])

  for name, c in cum_stats.items():
    tot_ap = c["all_play_w"] + c["all_play_l"]
    tot_act = c["actual_w"] + c["actual_l"]
    ap_pct = (c["all_play_w"] / tot_ap) if tot_ap > 0 else 0
    act_pct = (c["actual_w"] / tot_act) if tot_act > 0 else 0
    c["all_play_pct"] = ap_pct
    c["luck_delta"] = round(act_pct - ap_pct, 3)
    c["avg_eff"] = (
        round(sum(c["eff_list"]) / len(c["eff_list"]), 1)
        if c["eff_list"]
        else 0.0
    )

  generate_html_report(WEEK, week_teams, cum_stats)
  print(f"Successfully audited Week {WEEK} and generated index.html!")


if __name__ == "__main__":
  main()
