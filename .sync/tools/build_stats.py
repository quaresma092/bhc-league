#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_stats.py — англоязычный раздел статистики BHC (site-v2/en/) из одного JSON.

Пересборка всего раздела:
    python3 tools/build_stats.py

Проверка генератора на файле-образце:
    python3 tools/build_stats.py --data site-v2/en/data/_example.json --out /tmp/bhc-stats-test

Страницы статические: вся статистика уже в HTML, без JS — так её видит и человек, и парсер
(Elite Prospects требует «official league source»: публичные страницы + протоколы матчей).
"""
import argparse, datetime, html, json, os, shutil, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DATA = os.path.join(ROOT, "site-v2", "en", "data", "season-2026-27.json")
DEFAULT_OUT = os.path.join(ROOT, "site-v2", "en")

NAV = [
    ("index.html", "Overview"),
    ("schedule.html", "Schedule &amp; Results"),
    ("standings.html", "Standings"),
    ("players.html", "Players"),
    ("goalies.html", "Goalies"),
    ("teams.html", "Teams &amp; Rosters"),
    ("game-sheets.html", "Game sheets"),
]

FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com">'
         '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
         '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
         'family=Big+Shoulders:wght@700;800;900&family=Sofia+Sans+Extra+Condensed:wght@800;900'
         '&family=Inter:wght@400;500;600;700&display=swap">')


# ---------------------------------------------------------------- вспомогательное
def esc(v):
    return html.escape(str(v), quote=False)


def team_map(data):
    return {t["id"]: t for t in data.get("teams", [])}


def player_map(data):
    return {p["id"]: p for p in data.get("players", [])}


def final_games(data):
    return [g for g in data.get("games", []) if g.get("status") == "final"]


def fmt_date(iso):
    try:
        return datetime.date.fromisoformat(iso).strftime("%d %b %Y")
    except (ValueError, TypeError):
        return esc(iso or "")


# ---------------------------------------------------------------- расчёты
def compute_standings(data):
    """Очки 3-2-1-0 (IIHF), тай-брейкеры по §10 регламента."""
    rows = {t["id"]: dict(team=t["id"], gp=0, w=0, otw=0, otl=0, l=0, gf=0, ga=0, pts=0, pim=0)
            for t in data.get("teams", [])}
    h2h = {}  # (a,b) -> очки a в личных встречах
    for g in final_games(data):
        home, away = g["home"], g["away"]
        if home not in rows or away not in rows:
            continue
        hs, as_ = g["score"]["home"]["total"], g["score"]["away"]["total"]
        res = g.get("result", "REG").upper()
        for tid, gf, ga in ((home, hs, as_), (away, as_, hs)):
            rows[tid]["gp"] += 1
            rows[tid]["gf"] += gf
            rows[tid]["ga"] += ga
        winner, loser = (home, away) if hs > as_ else (away, home)
        if res == "REG":
            rows[winner]["w"] += 1
            rows[winner]["pts"] += 3
            rows[loser]["l"] += 1
            wp, lp = 3, 0
        else:  # OT / SO
            rows[winner]["otw"] += 1
            rows[winner]["pts"] += 2
            rows[loser]["otl"] += 1
            rows[loser]["pts"] += 1
            wp, lp = 2, 1
        h2h[(winner, loser)] = h2h.get((winner, loser), 0) + wp
        h2h[(loser, winner)] = h2h.get((loser, winner), 0) + lp
        for ev in g.get("events", []):
            if ev.get("type") == "penalty" and ev.get("team") in rows:
                rows[ev["team"]]["pim"] += int(ev.get("minutes", 0))

    tm = team_map(data)

    def key(r):
        # §10.1: очки → личная встреча (учитывается ниже через h2h при равенстве пар) →
        # разница шайб → заброшенные → меньше штрафных минут
        return (-r["pts"], -(r["gf"] - r["ga"]), -r["gf"], r["pim"], tm[r["team"]]["name"])

    table = sorted(rows.values(), key=key)
    # личная встреча как первый критерий для пары с равными очками
    for i in range(len(table) - 1):
        a, b = table[i], table[i + 1]
        if a["pts"] == b["pts"] and h2h.get((b["team"], a["team"]), 0) > h2h.get((a["team"], b["team"]), 0):
            table[i], table[i + 1] = b, a
    for i, r in enumerate(table, 1):
        r["pos"] = i
        r["diff"] = r["gf"] - r["ga"]
    return table


def compute_skaters(data):
    pm = player_map(data)
    st = {pid: dict(player=pid, gp=0, g=0, a=0, pts=0, pim=0)
          for pid, p in pm.items() if p.get("position") != "G"}
    for g in final_games(data):
        for side in ("home", "away"):
            for pid in (g.get("lineups", {}) or {}).get(side, []):
                if pid in st:
                    st[pid]["gp"] += 1
        for ev in g.get("events", []):
            if ev.get("type") == "goal":
                if ev.get("scorer") in st:
                    st[ev["scorer"]]["g"] += 1
                    st[ev["scorer"]]["pts"] += 1
                for pid in ev.get("assists", []):
                    if pid in st:
                        st[pid]["a"] += 1
                        st[pid]["pts"] += 1
            elif ev.get("type") == "penalty" and ev.get("player") in st:
                st[ev["player"]]["pim"] += int(ev.get("minutes", 0))
    rows = [r for r in st.values() if r["gp"] or r["pts"] or r["pim"]]
    rows.sort(key=lambda r: (-r["pts"], -r["g"], r["pim"], pm[r["player"]]["name"]))
    return rows


def compute_goalies(data):
    pm = player_map(data)
    st = {}
    for g in final_games(data):
        for gk in g.get("goalies", []):
            pid = gk.get("player")
            if pid not in pm:
                continue
            r = st.setdefault(pid, dict(player=pid, gp=0, mins=0, sa=0, ga=0, so=0, w=0, l=0))
            r["gp"] += 1
            r["mins"] += int(gk.get("minutes", 0))
            r["sa"] += int(gk.get("shotsAgainst", 0))
            r["ga"] += int(gk.get("goalsAgainst", 0))
            if int(gk.get("goalsAgainst", 0)) == 0 and int(gk.get("minutes", 0)) >= 60:
                r["so"] += 1
            if gk.get("decision") == "W":
                r["w"] += 1
            elif gk.get("decision") == "L":
                r["l"] += 1
    rows = list(st.values())
    for r in rows:
        r["svp"] = (r["sa"] - r["ga"]) / r["sa"] if r["sa"] else None
        r["gaa"] = r["ga"] * 60 / r["mins"] if r["mins"] else None
    rows.sort(key=lambda r: (-(r["svp"] or 0), r["ga"], pm[r["player"]]["name"]))
    return rows


# ---------------------------------------------------------------- рендер
def shell(data, page, title, desc, head_html, body_html):
    nav = "".join(
        '<li><a href="{}"{}>{}</a></li>'.format(href, ' class="on"' if href == page else "", label)
        for href, label in NAV)
    season = data["season"]["name"]
    league = data["league"]["name"]
    updated = data.get("updated") or datetime.date.today().isoformat()
    site = data["league"].get("website", "")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)} — {esc(league)} {esc(season)}</title>
<meta name="description" content="{esc(desc)}">
<link rel="icon" href="../assets/bhc-logo-white.png">
{FONTS}
<link rel="stylesheet" href="stats.css">
</head>
<body>

<header class="top">
  <div class="wrap">
    <a class="brand" href="index.html"><img src="../assets/bhc-logo-white.png" alt="BHC"></a>
    <ul class="nav">{nav}</ul>
  </div>
</header>

<section class="page-head">
  <div class="wrap">{head_html}</div>
</section>

<main class="wrap">
{body_html}
</main>

<footer>
  <div class="wrap">
    <div class="src">Official source: {esc(league)}</div>
    <p>{esc(league)} ({esc(data['league']['abbr'])}) — official league data for {esc(season)}.
       All statistics on this page come from official league game sheets signed after each match.
       Last updated: {esc(updated)}. League website: {esc(site)}.</p>
    <p>Contact: {' · '.join(esc(x) for x in [
        ('Instagram ' + data['league']['contact']['instagram']) if data['league']['contact'].get('instagram') else '',
        ('Telegram ' + data['league']['contact']['telegram']) if data['league']['contact'].get('telegram') else '',
        ('WhatsApp ' + data['league']['contact']['whatsapp']) if data['league']['contact'].get('whatsapp') else '',
        data['league']['contact'].get('email', '')] if x)}</p>
  </div>
</footer>
</body>
</html>
"""


def note(text):
    """Пустое состояние — отдельным блоком под таблицей: внутри таблицы его на телефоне обрезает прокрутка."""
    return f'<div class="note">{esc(text)}</div>'


EMPTY = "Season starts in October 2026 — results will appear here after the first game round."

MSO_BASE = "https://www.mystatsonline.com/hockey/visitor/league/"


def mso_url(data, path, **extra):
    """Ссылка на публичную страницу MyStatsOnline (с 28.10 секретарь ведёт матчи там)."""
    m = data["league"]["mso"]
    q = f"IDLeague={m['league']}&IDSeason={m['season']}" + "".join(f"&{k}={v}" for k, v in extra.items())
    return f"{MSO_BASE}{path}?{q}"


def mso_frame(data, path, height, title, **extra):
    """Окно MSO в нашей рамке + прямая ссылка: внутри iframe данные не видны парсеру, а EP нужен источник."""
    url = mso_url(data, path, **extra)
    return (f'<div class="mso"><iframe src="{esc(url)}&amp;iframe=yes" title="{esc(title)}" loading="lazy" '
            f'style="height:{height}px"></iframe></div>'
            f'<p class="legend">Live data from the official league scoresheet system. '
            f'<a class="dl" href="{esc(url)}" target="_blank" rel="noopener">Open on MyStatsOnline</a></p>')


def page_index(data):
    s, lg = data["season"], data["league"]
    teams = "".join(
        f'<div class="card"><img src="{esc(t["logo"])}" alt="{esc(t["name"])}">'
        f'<div class="nm">{esc(t["name"])}</div>'
        f'<div class="ct">{esc(t["city"])} · {esc(t["country"])}</div></div>'
        for t in data["teams"])
    links = "".join(f'<a href="{h}">{l}</a>' for h, l in NAV[1:])
    head = (f'<div class="kick">{esc(lg["name"])} · {esc(s["name"])}</div>'
            f'<h1>Official <span class="accent">statistics</span></h1>'
            f'<p class="lead">{esc(lg["name"])} ({esc(lg["abbr"])}) is an international ice hockey championship '
            f'for clubs from different countries. The first season runs from {esc(s["startsText"])} to '
            f'{esc(s["endsText"])}. Games are played under the IIHF Official Rule Book; the base arena of the '
            f'league is in {esc(lg["baseArena"])}. Every match is streamed live on YouTube and recorded in an '
            f'official game sheet signed by both teams.</p>')
    body = f"""
  <div class="facts">
    <span>IIHF Official Rule Book</span><span>3 × 20 min stop time</span>
    <span>Points 3 · 2 · 1 · 0</span><span>5 min 3-on-3 overtime, then a shootout</span>
    <span>Players 16+, no upper age limit</span><span>Roster up to 30, 20 skaters + 2 goalies per game</span>
  </div>

  <h2>Season format</h2>
  <p>{esc(s['notes'])} Teams gather for several days about once a month and play several rounds at a time.
     Every pair of teams meets the same number of times and every team plays the same number of games.
     One table, place decided by total points. The season ends with a play-off weekend in January 2027:
     a Final Four with a third-place game.</p>

  <h2>Teams</h2>
  <div class="cards">{teams}</div>

  <h2>Data pages</h2>
  <p>Permanent pages, updated after every game round:</p>
  <div class="links">{links}</div>

  <h2>Documents</h2>
  <ul class="plain">
    <li><b>Regulation {esc(data['season']['name'])}</b> — <a class="dl" href="docs/BHC-Regulation-2026-27-EN.pdf">PDF</a>,
        the full competition regulation (IIHF-based).</li>
    <li><b>Official game sheets</b> — <a class="dl" href="game-sheets.html">index of match protocols</a>,
        one PDF per game.</li>
    {f"<li><b>Video archive</b> — {esc(lg['youtube'])}</li>" if lg.get('youtube') else ''}
  </ul>
"""
    return shell(data, "index.html", "Official statistics",
                 f"Official statistics of the {lg['name']} ({lg['abbr']}), {s['name']}: schedule, results, "
                 f"standings, player and goalie stats, rosters and official game sheets.", head, body)


def page_standings(data):
    if data["league"].get("mso"):
        head = ('<div class="kick">' + esc(data["season"]["name"]) + '</div><h1>Standings</h1>'
                '<p class="lead">One table for all teams. Points: 3 for a win in regulation, 2 for an overtime or '
                'shootout win, 1 for an overtime or shootout loss, 0 for a loss in regulation.</p>')
        body = mso_frame(data, "standings/standings_hockey.aspx", 620, "Standings")
        return shell(data, "standings.html", "Standings",
                     f"{data['league']['name']} {data['season']['name']} standings: points, wins, losses, "
                     f"goals for and against.", head, body)
    table = compute_standings(data)
    tm = team_map(data)
    note_html = ""
    if any(r["gp"] for r in table):
        rows = "".join(
            f'<tr><td>{r["pos"]}</td><td class="l"><div class="tm">'
            f'<img src="{esc(tm[r["team"]]["logo"])}" alt=""><b>{esc(tm[r["team"]]["name"])}</b></div></td>'
            f'<td>{r["gp"]}</td><td>{r["w"]}</td><td>{r["otw"]}</td><td>{r["otl"]}</td><td>{r["l"]}</td>'
            f'<td>{r["gf"]}</td><td>{r["ga"]}</td><td>{r["diff"]:+d}</td><td><b>{r["pts"]}</b></td></tr>'
            for r in table)
    else:
        rows = "".join(
            f'<tr><td>—</td><td class="l"><div class="tm"><img src="{esc(tm[r["team"]]["logo"])}" alt="">'
            f'<b>{esc(tm[r["team"]]["name"])}</b></div></td>'
            f'<td>0</td><td>0</td><td>0</td><td>0</td><td>0</td><td>0</td><td>0</td><td>0</td><td><b>0</b></td></tr>'
            for r in sorted(table, key=lambda r: tm[r["team"]]["name"]))
        note_html = note(EMPTY)
    head = ('<div class="kick">' + esc(data["season"]["name"]) + '</div><h1>Standings</h1>'
            '<p class="lead">One table for all teams. Points: 3 for a win in regulation, 2 for an overtime or '
            'shootout win, 1 for an overtime or shootout loss, 0 for a loss in regulation.</p>')
    body = f"""
  <div class="tbl-wrap"><table>
    <thead><tr><th>#</th><th class="l">Team</th><th>GP</th><th>W</th><th>OTW</th><th>OTL</th><th>L</th>
    <th>GF</th><th>GA</th><th>DIFF</th><th>PTS</th></tr></thead>
    <tbody>{rows}</tbody>
  </table></div>
  {note_html}
  <p class="legend">GP — games played · W — wins in regulation · OTW — overtime/shootout wins ·
     OTL — overtime/shootout losses · L — losses in regulation · GF — goals for · GA — goals against ·
     DIFF — goal difference · PTS — points. Ties are broken by head-to-head record, then goal difference,
     then goals scored, then fewer penalty minutes (Regulation §10).</p>
"""
    return shell(data, "standings.html", "Standings",
                 f"{data['league']['name']} {data['season']['name']} standings: points, wins, losses, "
                 f"goals for and against.", head, body)


def page_schedule(data):
    tm = team_map(data)
    games = sorted(data.get("games", []), key=lambda g: (g.get("date", ""), g.get("time", "")))
    note_html = ""
    if games:
        rows = ""
        for g in games:
            if g.get("status") == "final":
                score = (f'<b>{g["score"]["home"]["total"]} : {g["score"]["away"]["total"]}</b>'
                         + (f' <span class="legend">{esc(g.get("result"))}</span>'
                            if g.get("result", "REG") != "REG" else ""))
            else:
                score = "—"
            links = []
            if g.get("gameSheet"):
                links.append(f'<a class="dl" href="{esc(g["gameSheet"])}">Game sheet (PDF)</a>')
            if g.get("video"):
                links.append(f'<a class="dl" href="{esc(g["video"])}">Video</a>')
            rows += (f'<tr><td>{esc(g.get("round",""))}</td><td>{fmt_date(g.get("date"))}</td>'
                     f'<td>{esc(g.get("time",""))}</td><td>{esc(g.get("venue",""))}</td>'
                     f'<td class="l">{esc(tm[g["home"]]["name"])}</td><td>{score}</td>'
                     f'<td class="l">{esc(tm[g["away"]]["name"])}</td>'
                     f'<td class="l">{" · ".join(links) or "—"}</td></tr>')
    else:
        rows = ""
        note_html = note("The season calendar is published separately in the second half of September 2026. "
                         "Game dates, venues and results will appear here.")
    head = ('<div class="kick">' + esc(data["season"]["name"]) + '</div><h1>Schedule &amp; <span class="accent">results</span></h1>'
            '<p class="lead">Every game of the season with the venue, the final score, the official game sheet '
            'and the video of the match.</p>')
    mso_html = ""
    if data["league"].get("mso"):
        mso_html = ('<h2>Results and box scores</h2>'
                    + mso_frame(data, "schedule_scores/schedule.aspx", 900, "Schedule and scores")
                    + '<h2>Full season calendar</h2>')
    body = mso_html + f"""
  <div class="tbl-wrap"><table>
    <thead><tr><th>Round</th><th>Date</th><th>Time</th><th>Venue</th><th class="l">Home</th><th>Score</th>
    <th class="l">Away</th><th class="l">Official documents</th></tr></thead>
    <tbody>{rows}</tbody>
  </table></div>
  {note_html}
  <p class="legend">Scores marked OT or SO were decided in overtime or a shootout.
     Each finished game links to the official game sheet signed after the match.</p>
"""
    return shell(data, "schedule.html", "Schedule and results",
                 f"{data['league']['name']} {data['season']['name']} schedule and results with official "
                 f"game sheets and video.", head, body)


def page_players(data):
    if data["league"].get("mso"):
        head = ('<div class="kick">' + esc(data["season"]["name"]) + '</div><h1>Player <span class="accent">stats</span></h1>'
                '<p class="lead">Skater statistics for the season, taken from official game sheets.</p>')
        body = ('<h2>Leaders</h2>' + mso_frame(data, "stats/leaders_hockey.aspx", 700, "Player leaders")
                + '<h2>All skaters</h2>' + mso_frame(data, "stats/skater_hockey.aspx", 1100, "Player stats"))
        return shell(data, "players.html", "Player stats",
                     f"{data['league']['name']} {data['season']['name']} player statistics: games, goals, assists, "
                     f"points, penalty minutes.", head, body)
    pm, tm = player_map(data), team_map(data)
    rows_data = compute_skaters(data)
    if rows_data:
        rows = "".join(
            f'<tr><td>{i}</td><td class="l"><b>{esc(pm[r["player"]]["name"])}</b></td>'
            f'<td class="l">{esc(tm[pm[r["player"]]["team"]]["name"])}</td>'
            f'<td>{esc(pm[r["player"]].get("position",""))}</td><td>{r["gp"]}</td><td>{r["g"]}</td>'
            f'<td>{r["a"]}</td><td><b>{r["pts"]}</b></td><td>{r["pim"]}</td></tr>'
            for i, r in enumerate(rows_data, 1))
        note_html = ""
    else:
        rows, note_html = "", note(EMPTY)
    head = ('<div class="kick">' + esc(data["season"]["name"]) + '</div><h1>Player <span class="accent">stats</span></h1>'
            '<p class="lead">Skater statistics for the season, taken from official game sheets.</p>')
    body = f"""
  <div class="tbl-wrap"><table>
    <thead><tr><th>#</th><th class="l">Player</th><th class="l">Team</th><th>Pos</th><th>GP</th><th>G</th>
    <th>A</th><th>PTS</th><th>PIM</th></tr></thead>
    <tbody>{rows}</tbody>
  </table></div>
  {note_html}
  <p class="legend">GP — games played · G — goals · A — assists · PTS — points · PIM — penalties in minutes.
     Full rosters with dates of birth and positions: <a class="dl" href="teams.html">Teams &amp; Rosters</a>.</p>
"""
    return shell(data, "players.html", "Player stats",
                 f"{data['league']['name']} {data['season']['name']} player statistics: games, goals, assists, "
                 f"points, penalty minutes.", head, body)


def page_goalies(data):
    if data["league"].get("mso"):
        head = ('<div class="kick">' + esc(data["season"]["name"]) + '</div><h1>Goalie <span class="accent">stats</span></h1>'
                '<p class="lead">Goaltender statistics for the season, taken from official game sheets.</p>')
        body = mso_frame(data, "stats/goalie_hockey.aspx", 800, "Goalie stats")
        return shell(data, "goalies.html", "Goalie stats",
                     f"{data['league']['name']} {data['season']['name']} goaltender statistics: save percentage, "
                     f"goals against, shutouts.", head, body)
    pm, tm = player_map(data), team_map(data)
    rows_data = compute_goalies(data)
    if rows_data:
        rows = "".join(
            f'<tr><td>{i}</td><td class="l"><b>{esc(pm[r["player"]]["name"])}</b></td>'
            f'<td class="l">{esc(tm[pm[r["player"]]["team"]]["name"])}</td><td>{r["gp"]}</td>'
            f'<td>{r["sa"]}</td><td>{r["ga"]}</td>'
            f'<td><b>{r["svp"]*100:.1f}%</b></td><td>{r["gaa"]:.2f}</td><td>{r["so"]}</td></tr>'
            if r["svp"] is not None and r["gaa"] is not None else
            f'<tr><td>{i}</td><td class="l"><b>{esc(pm[r["player"]]["name"])}</b></td>'
            f'<td class="l">{esc(tm[pm[r["player"]]["team"]]["name"])}</td><td>{r["gp"]}</td>'
            f'<td>{r["sa"]}</td><td>{r["ga"]}</td><td>—</td><td>—</td><td>{r["so"]}</td></tr>'
            for i, r in enumerate(rows_data, 1))
        note_html = ""
    else:
        rows, note_html = "", note(EMPTY)
    head = ('<div class="kick">' + esc(data["season"]["name"]) + '</div><h1>Goalie <span class="accent">stats</span></h1>'
            '<p class="lead">Goaltender statistics for the season, taken from official game sheets.</p>')
    body = f"""
  <div class="tbl-wrap"><table>
    <thead><tr><th>#</th><th class="l">Goaltender</th><th class="l">Team</th><th>GP</th><th>SA</th><th>GA</th>
    <th>SV%</th><th>GAA</th><th>SO</th></tr></thead>
    <tbody>{rows}</tbody>
  </table></div>
  {note_html}
  <p class="legend">GP — games played · SA — shots against · GA — goals against · SV% — save percentage ·
     GAA — goals against average per 60 minutes · SO — shutouts.</p>
"""
    return shell(data, "goalies.html", "Goalie stats",
                 f"{data['league']['name']} {data['season']['name']} goaltender statistics: save percentage, "
                 f"goals against, shutouts.", head, body)


def page_teams(data):
    mso = data["league"].get("mso")
    if mso:
        blocks = "".join(
            f"<h2>{esc(t['name'])}</h2><p>{esc(t['city'])}, {esc(t['country'])}</p>"
            + mso_frame(data, "stats/team_hockey.aspx", 1000, t["name"], IDTeam=mso["teams"][t["id"]])
            for t in data["teams"] if t["id"] in mso.get("teams", {}))
        head = ('<div class="kick">' + esc(data["season"]["name"]) + '</div><h1>Teams &amp; <span class="accent">rosters</span></h1>'
                '<p class="lead">Season rosters and team statistics of all participating clubs. A team may register '
                'up to 30 players for the season and dress 20 skaters and 2 goaltenders for a game.</p>')
        return shell(data, "teams.html", "Teams and rosters",
                     f"{data['league']['name']} {data['season']['name']} teams and full season rosters.", head, blocks)
    pm = player_map(data)
    blocks = ""
    for t in data["teams"]:
        roster = [p for p in data.get("players", []) if p.get("team") == t["id"]]
        roster.sort(key=lambda p: (p.get("position") != "G", p.get("jersey") or 999, p.get("name", "")))
        if roster:
            rows = "".join(
                f'<tr><td>{esc(p.get("jersey",""))}</td><td class="l"><b>{esc(p["name"])}</b></td>'
                f'<td>{esc(p.get("position",""))}</td>'
                f'<td>{esc(p.get("shoots") or p.get("catches") or "")}</td>'
                f'<td>{esc(p.get("dob",""))}</td>'
                f'<td>{esc(p.get("heightCm","") and str(p["heightCm"]) + " cm")}</td>'
                f'<td>{esc(p.get("weightKg","") and str(p["weightKg"]) + " kg")}</td>'
                f'<td class="l">{esc(p.get("nationality",""))}</td>'
                f'<td class="l">{esc(p.get("previousClub",""))}</td></tr>'
                for p in roster)
            note_html = ""
        else:
            rows = ""
            note_html = note("Roster registration is open until 30 September 2026 — "
                             "the squad will be published here.")
        blocks += f"""
  <h2>{esc(t['name'])}</h2>
  <p>{esc(t['city'])}, {esc(t['country'])}</p>
  <div class="tbl-wrap"><table>
    <thead><tr><th>#</th><th class="l">Player</th><th>Pos</th><th>S/C</th><th>Date of birth</th><th>Height</th>
    <th>Weight</th><th class="l">Nationality</th><th class="l">Previous club</th></tr></thead>
    <tbody>{rows}</tbody>
  </table></div>
  {note_html}
"""
    head = ('<div class="kick">' + esc(data["season"]["name"]) + '</div><h1>Teams &amp; <span class="accent">rosters</span></h1>'
            '<p class="lead">Season rosters of all participating clubs. Player data is kept in the fields used by '
            'hockey databases: full name, date of birth, position, shoots/catches, height, weight, nationality '
            'and previous club. A team may register up to 30 players for the season and dress 20 skaters and '
            '2 goaltenders for a game.</p>')
    body = blocks + ('<div class="note">The fifth place in the championship is open until the season starts. '
                     'Clubs interested in joining can contact the league through the details below.</div>')
    return shell(data, "teams.html", "Teams and rosters",
                 f"{data['league']['name']} {data['season']['name']} teams and full season rosters.", head, body)


def page_sheets(data):
    tm = team_map(data)
    games = [g for g in sorted(data.get("games", []), key=lambda g: g.get("date", "")) if g.get("gameSheet")]
    if games:
        rows = "".join(
            f'<tr><td>{esc(g["id"])}</td><td>{fmt_date(g.get("date"))}</td>'
            f'<td class="l">{esc(tm[g["home"]]["name"])} – {esc(tm[g["away"]]["name"])}</td>'
            f'<td>{g["score"]["home"]["total"]} : {g["score"]["away"]["total"]}</td>'
            f'<td class="l"><a class="dl" href="{esc(g["gameSheet"])}">Download PDF</a></td></tr>'
            for g in games)
        note_html = ""
    else:
        rows = ""
        note_html = note("Game sheets will be published here after the first games in October 2026.")
    head = ('<div class="kick">' + esc(data["season"]["name"]) + '</div><h1>Official <span class="accent">game sheets</span></h1>'
            '<p class="lead">The game sheet is the official record of a match: line-ups with jersey numbers, '
            'goals with assists and times, penalties, goaltenders and the final score. It is completed by the '
            'league secretary and signed by both teams after the final siren, then published here as a PDF.</p>')
    body = f"""
  <div class="tbl-wrap"><table class="narrow">
    <thead><tr><th>Game</th><th>Date</th><th class="l">Teams</th><th>Score</th><th class="l">Document</th></tr></thead>
    <tbody>{rows}</tbody>
  </table></div>
  {note_html}
  <p class="legend">File naming: BHC-2026-27-G001-2026-10-16-VUK-WOL.pdf — league, season, game number, date,
     home and away team codes. Every file keeps its address permanently.</p>
"""
    return shell(data, "game-sheets.html", "Official game sheets",
                 f"Official game sheets (match protocols) of the {data['league']['name']} "
                 f"{data['season']['name']}, one PDF per game.", head, body)


# ---------------------------------------------------------------- сборка
PAGES = [("index.html", page_index), ("schedule.html", page_schedule), ("standings.html", page_standings),
         ("players.html", page_players), ("goalies.html", page_goalies), ("teams.html", page_teams),
         ("game-sheets.html", page_sheets)]


def main():
    ap = argparse.ArgumentParser(description="Сборка англоязычного раздела статистики BHC")
    ap.add_argument("--data", default=DEFAULT_DATA, help="JSON сезона")
    ap.add_argument("--out", default=DEFAULT_OUT, help="папка вывода")
    args = ap.parse_args()

    with open(args.data, encoding="utf-8") as f:
        data = json.load(f)
    os.makedirs(args.out, exist_ok=True)

    # при сборке в другую папку (проверка на образце) переносим CSS рядом
    css_src = os.path.join(DEFAULT_OUT, "stats.css")
    css_dst = os.path.join(args.out, "stats.css")
    if os.path.abspath(css_src) != os.path.abspath(css_dst) and os.path.exists(css_src):
        shutil.copyfile(css_src, css_dst)

    for name, fn in PAGES:
        path = os.path.join(args.out, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(fn(data))
        print(f"  {os.path.relpath(path, ROOT)}")

    st = compute_standings(data)
    print(f"собрано: {len(PAGES)} страниц · команд {len(data.get('teams', []))} · "
          f"игроков {len(data.get('players', []))} · матчей {len(data.get('games', []))} "
          f"(сыграно {sum(r['gp'] for r in st) // 2 if st else 0})")


if __name__ == "__main__":
    sys.exit(main())
