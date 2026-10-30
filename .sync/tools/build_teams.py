#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_teams.py — раздел «Команды» сайта BHC (site-v2) из того же JSON, что и статистика.

    python3 tools/build_teams.py                      # из site-v2/en/data/season-2026-27.json
    python3 tools/build_teams.py --data site-v2/en/data/_example.json --out /tmp/bhc-teams   # проверка на образце

Страницы (по образцу НХЛ/КХЛ: карточка клуба + вкладки состав / календарь / статистика, у игрока своя страница):
    teams.html                 — хаб: все команды
    teams/<slug>.html          — команда: Overview · Roster · Schedule & results · Stats
    players/<id>.html          — игрок: био в формате Elite Prospects, статистика сезона, матч за матчем
Всё уже в HTML (вкладки — якоря + немного JS), чтобы страницы читали и люди, и парсеры (Elite Prospects).
Шапка, подвал и стили берутся с about.html, чтобы раздел выглядел как весь сайт.
"""
import argparse, datetime, html, json, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
import build_stats as bs  # расчёты таблицы, бомбардиров, вратарей — одни на весь сайт

SITE = os.path.join(ROOT, 'site-v2')
esc = bs.esc
POS = {'G': 'Goalie', 'D': 'Defense', 'F': 'Forward', 'C': 'Forward', 'LW': 'Forward', 'RW': 'Forward'}
GROUPS = [('Goalies', 'G'), ('Defense', 'D'), ('Forwards', 'F')]


def group_of(p):
    return {'G': 'G', 'D': 'D'}.get(p.get('position', 'F'), 'F')


def born(p):
    """Полная дата с возрастом, если есть dob; иначе только год (born) — в публичный JSON даты рождения не пишем."""
    if p.get('dob'):
        return bs.fmt_date(p['dob']) + (f' ({age(p["dob"])})' if age(p['dob']) != '' else '')
    return str(p.get('born', ''))


def age(dob, on=None):
    try:
        b = datetime.date.fromisoformat(dob)
    except (TypeError, ValueError):
        return ''
    on = on or datetime.date.today()
    return on.year - b.year - ((on.month, on.day) < (b.month, b.day))


def logo_t(t, up):
    # прозрачный логотип (logos/<id>-t.png) — для цветных плашек; иначе обычный
    f = f'logos/{t["id"]}-t.png'
    return up + (f if os.path.exists(os.path.join(SITE, f)) else t['logo'].replace('../', ''))


# ---------------------------------------------------------------- каркас страницы
def chrome():
    s = open(os.path.join(SITE, 'about.html'), encoding='utf-8').read()
    head = re.search(r'<head>.*?</head>', s, re.S).group(0)
    head = re.sub(r'<title>.*?</title>|<meta name="description"[^>]*>|<style>.*?</style>', '', head, flags=re.S)
    header = re.search(r'<header class="top">.*?</header>', s, re.S).group(0)
    footer = re.search(r'<footer.*?</footer>', s, re.S).group(0)
    header = header.replace(' class="on"', '').replace('href="index.html#teams"', 'href="teams.html" class="on"')
    return head, header, footer


def fix_links(h, up):
    # страницы в подпапках teams/ и players/ — относительные ссылки на корень site-v2 с префиксом ../
    if not up:
        return h
    def rep(m):
        v = m.group(2)
        if v.startswith(('http', 'mailto:', 'tel:', '#', 'data:', '/')):
            return m.group(0)
        if v.startswith('../'):   # ../logos/final → ../../logos/final
            return f'{m.group(1)}="{up}{v}"'
        return f'{m.group(1)}="{up}{v}"'
    return re.sub(r'(href|src)="([^"]*)"', rep, h)


CSS = """<style>
  .th-head{display:grid;grid-template-columns:1fr auto;align-items:center;gap:24px}
  .th-logo{width:clamp(110px,15vw,190px);height:auto;filter:drop-shadow(0 8px 18px rgba(17,47,99,.18))}
  .tabs-bar{position:sticky;top:0;z-index:5;background:var(--paper);box-shadow:0 1px 0 var(--hair);margin-bottom:clamp(24px,4vw,40px)}
  .tabs-bar ul{list-style:none;display:flex;gap:4px;overflow-x:auto;scrollbar-width:none}
  .tabs-bar a{display:block;padding:16px 16px 13px;text-decoration:none;font-size:13px;letter-spacing:.2em;text-transform:uppercase;font-weight:600;color:var(--mid);border-bottom:3px solid transparent;white-space:nowrap}
  .tabs-bar a.on,.tabs-bar a:hover{color:var(--blue);border-bottom-color:var(--red)}
  .pane{padding-bottom:clamp(56px,8vw,96px)}
  .pane h2{font-family:var(--display);text-transform:uppercase;font-weight:900;color:var(--blue);font-size:clamp(34px,4vw,48px);line-height:.9;margin:0 0 18px}
  .pane h3{font-family:var(--display);text-transform:uppercase;font-weight:900;color:var(--ink);font-size:26px;margin:28px 0 10px}
  .js .pane{display:none}.js .pane.on{display:block}
  .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px}
  .cards .c{background:var(--card);box-shadow:inset 0 0 0 1px var(--hair);padding:20px 22px}
  .cards .c .k{font-size:11px;letter-spacing:.28em;text-transform:uppercase;color:var(--red);font-weight:600}
  .cards .c b{display:block;font-family:var(--display);font-weight:900;text-transform:uppercase;color:var(--blue);font-size:34px;line-height:.95;margin-top:8px}
  .cards .c p{color:var(--mid);font-size:15px;margin-top:6px}
  .facts{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:8px;margin-top:26px}
  .facts div{background:var(--card);box-shadow:inset 0 0 0 1px var(--hair);padding:14px 18px}
  .facts dt{font-size:11px;letter-spacing:.24em;text-transform:uppercase;color:var(--dim);font-weight:600}
  .facts dd{margin:4px 0 0;font-weight:600;color:var(--ink)}
  .facts a{color:var(--blue)}
  .pane .tbl table,main .tbl table{min-width:640px}  /* на телефоне таблица листается вбок, а не сжимается */
  .pane .tbl td,main .tbl td{white-space:nowrap}
  .tbl td a{color:var(--blue);font-weight:600;text-decoration:none}
  .tbl td a:hover{color:var(--red)}
  .tbl .num{text-align:right}
  .opp{display:flex;align-items:center;gap:10px}
  .opp img{width:30px;height:30px;object-fit:contain}
  .res-w{color:#0E7A3E;font-weight:700}.res-l{color:var(--red);font-weight:700}
  .empty{background:var(--card);box-shadow:inset 0 0 0 1px var(--hair);border-left:3px solid var(--red);padding:18px 20px;color:var(--mid)}
  .hub{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:16px;padding-bottom:clamp(56px,8vw,96px)}
  .hub a{display:flex;flex-direction:column;align-items:flex-start;gap:14px;text-decoration:none;background:var(--card);box-shadow:inset 0 0 0 1px var(--hair);padding:26px 24px;transition:box-shadow .15s,transform .15s}
  .hub a:hover{box-shadow:inset 0 0 0 2px var(--red);transform:translateY(-2px)}
  .hub img{height:96px;width:auto;max-width:100%;object-fit:contain}
  .hub b{font-family:var(--display);font-weight:900;text-transform:uppercase;color:var(--blue);font-size:30px;line-height:.95}
  .hub span{font-size:12px;letter-spacing:.2em;text-transform:uppercase;color:var(--mid)}
  .hub i{font-style:normal;font-size:13px;color:var(--red);font-weight:600;letter-spacing:.14em;text-transform:uppercase;margin-top:auto}
  .pl-num{font-family:var(--display);font-weight:900;color:var(--red)}
  @media (max-width:640px){.th-head{grid-template-columns:1fr}.th-logo{order:-1;width:96px}}
</style>"""

TABS_JS = """<script>
  // вкладки: без JS видны все разделы; с JS — один, по якорю (#roster и т.п.), ссылки можно пересылать
  document.documentElement.classList.add('js');
  function showTab(){var h=(location.hash||'#overview').slice(1),p=document.getElementById(h);if(!p||!p.classList.contains('pane'))p=document.querySelector('.pane');
    document.querySelectorAll('.pane').forEach(function(x){x.classList.toggle('on',x===p)});
    document.querySelectorAll('.tabs-bar a').forEach(function(a){a.classList.toggle('on',a.getAttribute('href')==='#'+p.id)});}
  addEventListener('hashchange',showTab);showTab();
</script>"""


def page(up, title, desc, body, js=''):
    head, header, footer = (fix_links(x, up) for x in chrome())   # тело страницы уже пишется с нужными путями
    head = head.replace('</head>', f'<title>{esc(title)}</title>\n<meta name="description" content="{html.escape(desc)}">\n{CSS}\n</head>')
    return f'<!doctype html>\n<html lang="en">\n{head}\n<body>\n\n{header}\n\n{body}\n\n{footer}\n{js}\n</body>\n</html>\n'


# ---------------------------------------------------------------- данные
def load(path):
    data = json.load(open(path, encoding='utf-8'))
    for t in data['teams']:
        t.setdefault('slug', t['id'])
    tm = bs.team_map(data)
    pm = bs.player_map(data)
    table = bs.compute_standings(data)
    sk = {r['player']: r for r in bs.compute_skaters(data)}
    gk = {r['player']: r for r in bs.compute_goalies(data)}
    return data, tm, pm, table, sk, gk


def game_date(g):
    return bs.fmt_date(g['date']) if g.get('date') else esc(g.get('dateText', 'TBD'))


def result_for(g, tid):
    if g.get('status') in ('cancelled', 'postponed'):
        return f'<span class="res-l">{g["status"].capitalize()}</span>'
    if g.get('status') != 'final':
        return ''
    me, them = ('home', 'away') if g['home'] == tid else ('away', 'home')
    a, b = g['score'][me]['total'], g['score'][them]['total']
    suf = '' if g.get('result', 'REG') == 'REG' else ' ' + esc(g['result'])
    return f'<span class="{"res-w" if a > b else "res-l"}">{"W" if a > b else "L"} {a}:{b}{suf}</span>'


# ---------------------------------------------------------------- страницы
def hub(data, tm, table):
    pos = {r['team']: r for r in table}
    played = any(r['gp'] for r in table)   # до первых игр места в таблице — просто алфавит, не показываем
    cards = ''.join(
        f'<a href="teams/{t["slug"]}.html"><img src="{logo_t(t, "")}" alt="">'
        f'<div><b>{esc(t["name"])}</b><br><span>{esc(t["city"])} · {esc(t["country"])}</span></div>'
        f'<i>{(str(pos[t["id"]]["pts"]) + " pts · #" + str(pos[t["id"]]["pos"])) if played else "Team page"} →</i></a>'
        for t in sorted(data['teams'], key=lambda t: t['name']))
    s = data['season']
    body = f'''<section class="page-head"><div class="wrap">
  <div class="kick">{esc(s["name"])}</div>
  <h1>Teams</h1>
  <p class="lead">{len(data["teams"])} clubs from {len({t["country"] for t in data["teams"]})} countries. Each team has its own page: roster, schedule and results, team and player stats.</p>
</div></section>
<main class="wrap"><div class="hub">{cards}</div></main>'''
    return page('', f'Teams · BHC', f'All teams of the Balkan Hockey Championship {s["name"]}: rosters, schedules and stats.', body)


def team_page(data, t, tm, pm, table, sk, gk):
    tid = t['id']
    st = next(r for r in table if r['team'] == tid)
    games = sorted((g for g in data['games'] if tid in (g['home'], g['away'])), key=lambda g: (g.get('date') or '9999', g.get('time', ''), g['id']))
    rn = lambda g: int(re.sub(r'\D', '', g.get('round', '')) or 0)
    games.sort(key=lambda g: (rn(g), g.get('date') or '9999', g.get('time', '')))
    nxt = next((g for g in games if g.get('status') == 'scheduled' and g.get('date')), None)
    last = next((g for g in reversed(games) if g.get('status') == 'final'), None)
    roster = [p for p in data.get('players', []) if p.get('team') == tid]

    def opp(g):
        o = tm[g['away'] if g['home'] == tid else g['home']]
        pre = 'vs' if g['home'] == tid else '@'
        return f'<span class="opp">{pre} <img src="../{logo_t(o, "")}" alt=""><a href="{o["slug"]}.html">{esc(o["name"])}</a></span>'

    # Overview
    first = min((g['date'] for g in data['games'] if g.get('date')), default='')
    if any(r['gp'] for r in table):
        cards = f'<div class="c"><div class="k">Standings</div><b>#{st["pos"]} · {st["pts"]} pts</b><p>{st["gp"]} GP · {st["w"]+st["otw"]} W · {st["l"]+st["otl"]} L</p></div>'
    else:
        cards = f'<div class="c"><div class="k">Season</div><b>Starts {bs.fmt_date(first)[:6] if first else "soon"}</b><p>{esc(data["season"]["name"])} · regular season</p></div>'
    if nxt:
        cards += f'<div class="c"><div class="k">Next game</div><b>{game_date(nxt)}</b><p>{esc(nxt.get("time",""))} · {opp(nxt)} · {esc(nxt["venue"])}</p></div>'
    if last:
        cards += f'<div class="c"><div class="k">Last result</div><b>{result_for(last, tid)}</b><p>{opp(last)}</p></div>'
    top = sorted([sk[p['id']] for p in roster if p['id'] in sk], key=lambda r: (-r['pts'], -r['g']))
    if top:
        p = pm[top[0]['player']]
        cards += f'<div class="c"><div class="k">Top scorer</div><b>{esc(p["name"])}</b><p>{top[0]["g"]} G · {top[0]["a"]} A · {top[0]["pts"]} PTS</p></div>'
    facts = [('City', f'{t["city"]}, {t["country"]}'), ('Founded', t.get('founded')), ('Home rink', t.get('homeRink')),
             ('Head coach', t.get('headCoach')), ('Captain', t.get('captain')), ('Colors', t.get('colors'))]
    fl = ''.join(f'<div><dt>{k}</dt><dd>{esc(v)}</dd></div>' for k, v in facts if v)
    if t.get('instagram'):
        fl += f'<div><dt>Instagram</dt><dd><a href="https://instagram.com/{esc(t["instagram"])}" target="_blank" rel="noopener">@{esc(t["instagram"])}</a></dd></div>'
    if t.get('website'):
        site = re.sub(r'^https?://(www\.)?', '', t['website']).rstrip('/')
        fl += f'<div><dt>Website</dt><dd><a href="{esc(t["website"])}" target="_blank" rel="noopener">{esc(site)}</a></dd></div>'
    about = f'<p style="margin-top:22px;color:var(--mid)">{esc(t["about"])}</p>' if t.get('about') else ''
    overview = f'<div class="cards">{cards}</div><dl class="facts">{fl}</dl>{about}'

    # Roster — как у НХЛ/КХЛ: по позициям
    if roster:
        rs = ''
        for title, code in GROUPS:
            ps = sorted([p for p in roster if group_of(p) == code], key=lambda p: (int(p.get('jersey') or 999), p['name'].split()[-1]))
            if not ps:
                continue
            # колонки без данных у всей группы не показываем (рост/вес/хват пока не собираем)
            cols = [('#', lambda p: esc(p.get('jersey', ''))),
                    ('Player', lambda p: f'<a href="../players/{esc(p["id"])}.html">{esc(p["name"])}</a>' + (' <b title="Captain">(C)</b>' if p.get('captain') else '')),
                    ('Pos', lambda p: esc(p.get('position', ''))),
                    ('Catches' if code == 'G' else 'Shoots', lambda p: esc(p.get('catches' if code == 'G' else 'shoots', ''))),
                    ('Born', lambda p: esc(born(p))),
                    ('Height', lambda p: esc(p.get('heightCm', '') and str(p['heightCm']) + ' cm')),
                    ('Weight', lambda p: esc(p.get('weightKg', '') and str(p['weightKg']) + ' kg')),
                    ('Nationality', lambda p: esc(p.get('nationality', ''))),
                    ('Previous club', lambda p: esc(p.get('previousClub', ''))),
                    ('EP', lambda p: f'<a href="{esc(p["ep"])}" target="_blank" rel="noopener">Profile</a>' if p.get('ep') else '')]
            cols = [c for c in cols if c[0] == 'Player' or any(c[1](p) for p in ps)]
            rows = ''.join('<tr>' + ''.join(f'<td{" class=\"pl-num\"" if h == "#" else ""}>{fn(p)}</td>' for h, fn in cols) + '</tr>' for p in ps)
            rs += (f'<h3>{title}</h3><div class="tbl"><table><thead><tr>' + ''.join(f'<th>{h}</th>' for h, _ in cols) +
                   f'</tr></thead><tbody>{rows}</tbody></table></div>')
    else:
        rs = '<div class="empty">The roster will be published soon.</div>'

    # Schedule & results
    rows = ''.join(
        f'<tr><td>{esc(g.get("round",""))}</td><td>{game_date(g)}</td><td>{esc(g.get("time",""))}</td><td>{opp(g)}</td>'
        f'<td>{esc(g.get("venue",""))}</td><td>{result_for(g, tid)}</td>'
        f'<td>{("<a href=../en/" + esc(g["gameSheet"]) + ">Sheet</a>") if g.get("gameSheet") else ""}'
        f'{(" <a href=" + esc(g["video"]) + " target=_blank rel=noopener>Video</a>") if g.get("video") else ""}</td></tr>'
        for g in games)
    sched = (f'<div class="tbl"><table><thead><tr><th>Round</th><th>Date</th><th>Time</th><th>Opponent</th><th>Venue</th>'
             f'<th>Result</th><th></th></tr></thead><tbody>{rows}</tbody></table></div>') if games else '<div class="empty">No games yet.</div>'

    # Stats
    team_line = (f'<div class="tbl"><table><thead><tr><th>GP</th><th>W</th><th>OTW</th><th>OTL</th><th>L</th><th>GF</th><th>GA</th>'
                 f'<th>+/−</th><th>PTS</th><th>PIM</th></tr></thead><tbody><tr><td>{st["gp"]}</td><td>{st["w"]}</td><td>{st["otw"]}</td>'
                 f'<td>{st["otl"]}</td><td>{st["l"]}</td><td>{st["gf"]}</td><td>{st["ga"]}</td><td>{st["diff"]:+d}</td><td><b>{st["pts"]}</b></td>'
                 f'<td>{st["pim"]}</td></tr></tbody></table></div>')
    skr = [sk[p['id']] for p in roster if p['id'] in sk]
    skr.sort(key=lambda r: (-r['pts'], -r['g']))
    sk_html = ''.join(f'<tr><td><a href="../players/{r["player"]}.html">{esc(pm[r["player"]]["name"])}</a></td><td>{esc(pm[r["player"]].get("position",""))}</td>'
                      f'<td>{r["gp"]}</td><td>{r["g"]}</td><td>{r["a"]}</td><td><b>{r["pts"]}</b></td><td>{r["pim"]}</td></tr>' for r in skr)
    gkr = [gk[p['id']] for p in roster if p['id'] in gk]
    gk_html = ''.join(f'<tr><td><a href="../players/{r["player"]}.html">{esc(pm[r["player"]]["name"])}</a></td><td>{r["gp"]}</td>'
                      f'<td>{"%.3f" % r["svp"] if r["svp"] is not None else "—"}</td><td>{"%.2f" % r["gaa"] if r["gaa"] is not None else "—"}</td><td>{r["so"]}</td></tr>' for r in gkr)
    stats = f'<h3>Team</h3>{team_line}'
    stats += (f'<h3>Skaters</h3><div class="tbl"><table><thead><tr><th>Player</th><th>Pos</th><th>GP</th><th>G</th><th>A</th><th>PTS</th><th>PIM</th></tr></thead><tbody>{sk_html}</tbody></table></div>'
              if sk_html else '<h3>Skaters</h3><div class="empty">Player stats appear after the first games.</div>')
    if gk_html:
        stats += f'<h3>Goalies</h3><div class="tbl"><table><thead><tr><th>Player</th><th>GP</th><th>SV%</th><th>GAA</th><th>SO</th></tr></thead><tbody>{gk_html}</tbody></table></div>'

    s = data['season']
    body = f'''<section class="page-head"><div class="wrap th-head">
  <div><div class="kick"><a href="../teams.html" style="color:inherit;text-decoration:none">Teams</a> · {esc(s["name"])}</div>
  <h1>{esc(t["name"])}</h1>
  <p class="lead">{esc(t["city"])}, {esc(t["country"])}</p></div>
  <img class="th-logo" src="../{logo_t(t, "")}" alt="{esc(t["name"])} logo">
</div></section>
<nav class="tabs-bar"><div class="wrap"><ul>
  <li><a href="#overview">Overview</a></li><li><a href="#roster">Roster</a></li><li><a href="#schedule">Schedule &amp; results</a></li><li><a href="#stats">Stats</a></li>
</ul></div></nav>
<main class="wrap">
  <section class="pane" id="overview"><h2>Overview</h2>{overview}</section>
  <section class="pane" id="roster"><h2>Roster</h2>{rs}</section>
  <section class="pane" id="schedule"><h2>Schedule &amp; results</h2>{sched}</section>
  <section class="pane" id="stats"><h2>Stats</h2>{stats}</section>
</main>'''
    return page('../', f'{t["name"]} · Teams · BHC',
                f'{t["name"]} ({t["city"]}, {t["country"]}) in the Balkan Hockey Championship {s["name"]}: roster, schedule, results and stats.',
                body, TABS_JS)


def player_page(data, p, tm, sk, gk):
    t = tm[p['team']]
    facts = [('Team', None), ('Position', POS.get(p.get('position', ''), p.get('position', ''))),
             ('Catches' if p.get('position') == 'G' else 'Shoots', p.get('shoots')),
             ('Born', born(p)),
             ('Height', p.get('heightCm') and f'{p["heightCm"]} cm'), ('Weight', p.get('weightKg') and f'{p["weightKg"]} kg'),
             ('Nationality', p.get('nationality')), ('Previous club', p.get('previousClub'))]
    fl = f'<div><dt>Team</dt><dd><a href="../teams/{t["slug"]}.html">{esc(t["name"])}</a></dd></div>'
    fl += ''.join(f'<div><dt>{k}</dt><dd>{esc(v)}</dd></div>' for k, v in facts[1:] if v)
    if p.get('ep'):
        fl += f'<div><dt>Elite Prospects</dt><dd><a href="{esc(p["ep"])}" target="_blank" rel="noopener">Player profile</a></dd></div>'
    if p.get('position') == 'G':
        r = gk.get(p['id'])
        season = ('<div class="tbl"><table><thead><tr><th>Season</th><th>GP</th><th>W</th><th>L</th><th>SV%</th><th>GAA</th><th>SO</th></tr></thead><tbody>'
                  f'<tr><td>{esc(data["season"]["name"])}</td><td>{r["gp"]}</td><td>{r["w"]}</td><td>{r["l"]}</td>'
                  f'<td>{"%.3f" % r["svp"] if r["svp"] is not None else "—"}</td><td>{"%.2f" % r["gaa"] if r["gaa"] is not None else "—"}</td><td>{r["so"]}</td></tr></tbody></table></div>') if r else ''
    else:
        r = sk.get(p['id'])
        season = ('<div class="tbl"><table><thead><tr><th>Season</th><th>GP</th><th>G</th><th>A</th><th>PTS</th><th>PIM</th></tr></thead><tbody>'
                  f'<tr><td>{esc(data["season"]["name"])}</td><td>{r["gp"]}</td><td>{r["g"]}</td><td>{r["a"]}</td><td><b>{r["pts"]}</b></td><td>{r["pim"]}</td></tr></tbody></table></div>') if r else ''
    # матч за матчем
    log = ''
    for g in bs.final_games(data):
        side = 'home' if p['id'] in (g.get('lineups', {}) or {}).get('home', []) else 'away' if p['id'] in (g.get('lineups', {}) or {}).get('away', []) else None
        if not side:
            continue
        o = tm[g['away'] if side == 'home' else g['home']]
        G = sum(1 for e in g.get('events', []) if e.get('type') == 'goal' and e.get('scorer') == p['id'])
        A = sum(1 for e in g.get('events', []) if e.get('type') == 'goal' and p['id'] in e.get('assists', []))
        PIM = sum(int(e.get('minutes', 0)) for e in g.get('events', []) if e.get('type') == 'penalty' and e.get('player') == p['id'])
        log += (f'<tr><td>{game_date(g)}</td><td>{"vs" if side == "home" else "@"} <a href="../teams/{o["slug"]}.html">{esc(o["name"])}</a></td>'
                f'<td>{result_for(g, p["team"])}</td><td>{G}</td><td>{A}</td><td>{G + A}</td><td>{PIM}</td></tr>')
    log_html = (f'<div class="tbl"><table><thead><tr><th>Date</th><th>Opponent</th><th>Result</th><th>G</th><th>A</th><th>PTS</th><th>PIM</th></tr></thead><tbody>{log}</tbody></table></div>'
                if log else '<div class="empty">Game log appears after the player’s first game.</div>')
    body = f'''<section class="page-head"><div class="wrap th-head">
  <div><div class="kick"><a href="../teams/{t["slug"]}.html" style="color:inherit;text-decoration:none">{esc(t["name"])}</a> · {esc(data["season"]["name"])}</div>
  <h1>{("#" + esc(p["jersey"]) + " ") if p.get("jersey") else ""}{esc(p["name"])}</h1>
  <p class="lead">{esc(POS.get(p.get("position",""), ""))}{" · " + esc(p["nationality"]) if p.get("nationality") else ""}</p></div>
  <img class="th-logo" src="../{logo_t(t, "")}" alt="{esc(t["name"])} logo">
</div></section>
<main class="wrap" style="padding-bottom:clamp(56px,8vw,96px)">
  <dl class="facts">{fl}</dl>
  <div class="pane on" style="display:block;padding-bottom:0"><h3>Season stats</h3>{season or '<div class="empty">Stats appear after the first games.</div>'}
  <h3>Game log</h3>{log_html}</div>
</main>'''
    return page('../', f'{p["name"]} · {t["name"]} · BHC',
                f'{p["name"]}, {POS.get(p.get("position",""), "player")} of {t["name"]} — Balkan Hockey Championship {data["season"]["name"]}: bio and stats.', body)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', default=bs.DEFAULT_DATA)
    ap.add_argument('--out', default=SITE)
    a = ap.parse_args()
    data, tm, pm, table, sk, gk = load(a.data)
    os.makedirs(os.path.join(a.out, 'teams'), exist_ok=True)
    os.makedirs(os.path.join(a.out, 'players'), exist_ok=True)
    open(os.path.join(a.out, 'teams.html'), 'w', encoding='utf-8').write(hub(data, tm, table))
    for t in data['teams']:
        open(os.path.join(a.out, 'teams', t['slug'] + '.html'), 'w', encoding='utf-8').write(team_page(data, t, tm, pm, table, sk, gk))
    # страницы игроков: только текущий состав; старые файлы удалённых игроков убираем
    keep = set()
    for p in data.get('players', []):
        if p.get('team') in tm and not p['id'].startswith('_'):
            f = p['id'] + '.html'; keep.add(f)
            open(os.path.join(a.out, 'players', f), 'w', encoding='utf-8').write(player_page(data, p, tm, sk, gk))
    for f in os.listdir(os.path.join(a.out, 'players')):
        if f.endswith('.html') and f not in keep:
            os.remove(os.path.join(a.out, 'players', f))
    print(f'teams.html + {len(data["teams"])} team pages + {len(keep)} player pages → {a.out}')


if __name__ == '__main__':
    main()
