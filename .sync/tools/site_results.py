# Общие куски сборки сайта: подстановка контактов (fill) и данные сезона в страницах (results_fill).
# Используют tools/build_site.py (полная сборка) и tools/mso_sync.py (автообновление после матчей).
#   results_fill('index', html) — блок Stats на главной: Results и Teams из JSON сезона, Players и Goalies из mso-stats.json
#   results_fill('schedule', html) — счёт в schedule.html (const RES)
import json, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, 'site-v2')
SEASON_FILE = os.path.join(SRC, 'en', 'data', 'season-2026-27.json')
MSO_STATS_FILE = os.path.join(SRC, 'en', 'data', 'mso-stats.json')   # пишет tools/mso_sync.py

sys.path.insert(0, os.path.join(ROOT, 'tools'))
from build_stats import compute_standings, final_games, fmt_date, esc as hesc

c = json.load(open(os.path.join(SRC, 'contacts.json'))) if os.path.exists(os.path.join(SRC, 'contacts.json')) else {}
g = lambda k: (c.get(k) or '').strip().lstrip('@')

def fill(s):
    # ссылки на формы и иконку: из корня site-v2 (../docs/ru) → в корень сайта (docs/en)
    s = s.replace('../docs/ru/', 'docs/en/').replace('../docs/en/', 'docs/en/').replace('../logos/final/raster/bhc-64.png', 'assets/bhc-64.png')
    # строки подвала «Связь»: <li><a href="#" class="ph">Instagram · [@ник]</a></li> и т.п.
    nets = {'Instagram': ('instagram', 'https://instagram.com/{}', '@{}'), 'Threads': ('threads', 'https://www.threads.net/@{}', '@{}'),
            'TikTok': ('tiktok', 'https://www.tiktok.com/@{}', '@{}'), 'Telegram': ('telegram', 'https://t.me/{}', '@{}')}
    for label, (key, url, shown) in nets.items():
        pat = re.compile(r'<li><a href="#" class="ph">' + label + r' · \[(?:@ник|канал)\]</a></li>')
        v = g(key)
        s = pat.sub(f'<li><a href="{url.format(v)}" target="_blank" rel="noopener">{label} · {shown.format(v)}</a></li>' if v else '', s)
    # строка «имя · email · телефон» → email-строка и отдельная строка WhatsApp (wa.me)
    wa = (c.get('whatsapp') or '').strip()
    wa_url = 'https://wa.me/' + re.sub(r'\D', '', wa) if wa else ''
    parts = [p for p in (c.get('name', '').strip(), g('email'), c.get('phone', '').strip()) if p]
    line = ((f'<li><a href="mailto:{g("email")}">' + ' · '.join(parts) + '</a></li>') if g('email') else
            (f'<li>{" · ".join(parts)}</li>' if parts else ''))
    if wa:
        line += f'<li><a href="{wa_url}" target="_blank" rel="noopener">WhatsApp · {wa}</a></li>'
    s = re.sub(r'<li><a href="mailto:\[email\]" class="ph">\[имя\] · \[email\] · \[телефон\]</a></li>', line, s)
    # кнопки «Write to us»: пока нет email — ведут в WhatsApp
    if not g('email') and wa:
        s = s.replace('href="mailto:[email]"', f'href="{wa_url}" target="_blank" rel="noopener"')
    # остальные места
    if g('email'): s = s.replace('[email]', g('email'))
    if g('instagram'): s = s.replace('[@ник]', '@' + g('instagram'))
    if c.get('phone'): s = s.replace('[телефон]', c['phone'].strip())
    if c.get('name'): s = s.replace('[имя]', c['name'].strip())
    if g('telegram'): s = s.replace('[канал]', '@' + g('telegram'))
    return s

def _tbody(s, pane, rows):
    return re.sub(r'(<div class="tbl-wrap" data-pane="' + pane + r'"[^>]*>.*?<tbody>).*?(</tbody>)',
                  lambda m: m.group(1) + rows + m.group(2), s, count=1, flags=re.S)

def results_fill(p, s):
    season = json.load(open(SEASON_FILE, encoding='utf-8'))
    tm = {t['id']: t['name'] for t in season.get('teams', [])}
    games = sorted(final_games(season), key=lambda g: (g['date'], g.get('time', '')), reverse=True)
    res_tag = lambda g: '' if g.get('result', 'REG') == 'REG' else g['result']
    if p == 'index':
        if games:
            s = _tbody(s, 'res', ''.join(
                f'<tr><td>{fmt_date(g["date"])}</td><td class="l"><b>{hesc(tm[g["home"]])}</b></td>'
                f'<td><b>{g["score"]["home"]["total"]}:{g["score"]["away"]["total"]}</b></td>'
                f'<td class="l"><b>{hesc(tm[g["away"]])}</b></td><td>{res_tag(g)}</td></tr>' for g in games))
        s = _tbody(s, 'tm', ''.join(
            f'<tr><td>{r["pos"] if games else "—"}</td><td class="l"><b>{hesc(tm[r["team"]])}</b></td><td>{r["gp"]}</td><td>{r["w"]}</td>'
            f'<td>{r["otw"]}</td><td>{r["otl"]}</td><td>{r["l"]}</td><td>{r["gf"]}–{r["ga"]}</td><td><b>{r["pts"]}</b></td></tr>'
            for r in compute_standings(season)))
        mso = json.load(open(MSO_STATS_FILE, encoding='utf-8')) if os.path.exists(MSO_STATS_FILE) else {}
        sk = [x for x in mso.get('skaters', []) if x['pts'] or x['pim']][:10]
        if sk:
            s = _tbody(s, 'pl', ''.join(
                f'<tr><td>{i}</td><td class="l"><b>{hesc(x["name"])}</b></td><td class="l">{hesc(x["team"])}</td><td>{hesc(x["pos"])}</td>'
                f'<td>{x["gp"]}</td><td>{x["g"]}</td><td>{x["a"]}</td><td><b>{x["pts"]}</b></td><td>{x["pim"]}</td></tr>'
                for i, x in enumerate(sk, 1)))
        gk = [x for x in mso.get('goalies', []) if x['sa']]
        if gk:
            s = _tbody(s, 'gk', ''.join(
                f'<tr><td>{i}</td><td class="l"><b>{hesc(x["name"])}</b></td><td class="l">{hesc(x["team"])}</td><td>{x["gp"]}</td>'
                f'<td><b>{hesc(x["svp"])}</b></td><td>{hesc(x["gaa"])}</td><td>{x["so"]}</td></tr>'
                for i, x in enumerate(gk, 1)))
    if p == 'schedule':
        res = ','.join(f'{int(g["id"][1:])}:[{g["score"]["home"]["total"]},{g["score"]["away"]["total"]},\'{res_tag(g)}\']' for g in games)
        s = re.sub(r'const RES=\{.*?\};', 'const RES={' + res + '};', s, count=1)
    return s

# ---------------------------------------------------------------- связка с облачным автосинком (GitHub Actions)
SITE = os.path.join(ROOT, '_site')
BUNDLE = os.path.join(SITE, '.sync')   # копия скриптов и site-v2 для mso_sync.py в облаке; Jekyll папки с точкой не публикует
SYNC_TOOLS = ['mso_sync.py', 'site_results.py', 'build_stats.py', 'build_teams.py']

def pull_published():
    """Перед локальной сборкой: забрать из репозитория сайта то, что записал облачный синк (счёт и статистика с MSO)."""
    import shutil, subprocess
    if not os.path.isdir(os.path.join(SITE, '.git')) or ROOT.startswith(SITE):
        return
    subprocess.run(['git', 'pull', '--rebase', '--autostash', '-q'], cwd=SITE)
    # облако владеет только результатами сыгранных матчей и mso-stats.json; расписание, игроки, команды — локальные
    remote = os.path.join(BUNDLE, os.path.relpath(SEASON_FILE, ROOT))
    if os.path.exists(remote):
        mine, theirs = json.load(open(SEASON_FILE, encoding='utf-8')), json.load(open(remote, encoding='utf-8'))
        # берём только результат сыгранных матчей; дата, время, команды и отмены — локальные (их правим здесь)
        got = []
        for g in mine.get('games', []):
            r = next((x for x in theirs.get('games', []) if x['id'] == g['id']), None)
            if r and r.get('status') == 'final' and (g.get('status') != 'final' or g.get('score') != r.get('score')):
                for k in ('status', 'result', 'score', 'events', 'goalies', 'lineups'):
                    if k in r: g[k] = r[k]
                got.append(g['id'])
        if got:
            mine['updated'] = max(mine.get('updated', ''), theirs.get('updated', ''))
            json.dump(mine, open(SEASON_FILE, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
            print('из облачного синка: счёт', ', '.join(got))
    remote = os.path.join(BUNDLE, os.path.relpath(MSO_STATS_FILE, ROOT))
    if os.path.exists(remote) and (not os.path.exists(MSO_STATS_FILE) or open(remote, 'rb').read() != open(MSO_STATS_FILE, 'rb').read()):
        shutil.copy(remote, MSO_STATS_FILE); print('из облачного синка: статистика игроков')

def export_bundle():
    """После локальной сборки: обновить копию в _site/.sync, чтобы облачный синк собирал теми же скриптами и шаблонами."""
    import shutil
    if ROOT.startswith(SITE):
        return
    os.makedirs(os.path.join(BUNDLE, 'tools'), exist_ok=True)
    for t in SYNC_TOOLS:
        shutil.copy(os.path.join(ROOT, 'tools', t), os.path.join(BUNDLE, 'tools', t))
    shutil.rmtree(os.path.join(BUNDLE, 'tools', '__pycache__'), ignore_errors=True)
    dst = os.path.join(BUNDLE, 'site-v2')
    os.makedirs(dst, exist_ok=True)
    for f in ('about.html', 'contacts.json'):
        shutil.copy(os.path.join(SRC, f), os.path.join(dst, f))
    shutil.copytree(os.path.join(SRC, 'en'), os.path.join(dst, 'en'), dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('*.bak*', '*.prev.json', '*.pre-*', '_example.json'))
    for d in ('teams', 'players'):
        os.makedirs(os.path.join(dst, d), exist_ok=True)
