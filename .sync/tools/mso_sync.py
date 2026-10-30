#!/usr/bin/env python3
"""mso_sync.py — автообновление сайта из MyStatsOnline (MSO), где секретарь ведёт матчи.

    python3 tools/mso_sync.py            — забрать с MSO, при изменениях пересобрать и опубликовать
    python3 tools/mso_sync.py --dry-run  — только показать, что изменилось бы (ничего не пишет)
    python3 tools/mso_sync.py --force    — пересобрать и опубликовать, даже если данные не менялись

Что берём: счёт завершённых матчей (schedule.aspx) → JSON сезона; игроков и вратарей (skater/goalie_hockey.aspx)
→ site-v2/en/data/mso-stats.json (вкладки Players и Goalies на главной).
Что обновляем в _site: раздел /en/, страницы команд, блок Stats на главной, счёт в schedule.html.
Остальные страницы не пересобираются и в коммит не попадают: незаконченные правки в site-v2 так на сайт не утекут.
Запуск по расписанию — GitHub Actions в репозитории сайта, каждые 15 минут (.github/workflows/mso-sync.yml):
там этот скрипт лежит в .sync/tools/ вместе с копией site-v2, BHC_SITE = корень репозитория. Копию обновляет tools/build_site.py.
"""
import datetime, html, json, os, re, shutil, subprocess, sys, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
from site_results import fill, results_fill, SEASON_FILE, MSO_STATS_FILE, SRC

SITE = os.environ.get('BHC_SITE') or os.path.join(ROOT, '_site')
CLOUD = os.path.abspath(ROOT).startswith(os.path.abspath(SITE) + os.sep)   # копия в .sync/ внутри репозитория сайта
BASE = 'https://www.mystatsonline.com/hockey/visitor/league/'
DRY, FORCE = '--dry-run' in sys.argv, '--force' in sys.argv

def log(*a):
    print(datetime.datetime.now().strftime('%Y-%m-%d %H:%M'), *a, flush=True)

def get(path, q):
    req = urllib.request.Request(BASE + path + '?' + q, headers={'User-Agent': 'Mozilla/5.0 (BHC site sync)'})
    return urllib.request.urlopen(req, timeout=40).read().decode('utf-8', 'replace')

def text(s):
    return html.unescape(re.sub(r'<[^>]+>', ' ', s)).replace('\xa0', ' ').strip()

def mso_games(page):
    """Завершённые матчи: номер протокола → (id команды MSO хозяев, гостей, голы хозяев, гостей, REG|OT|SO, дата)."""
    out, day = {}, ''
    for kind, row in re.findall(r'<tr class="(day-row|detail[^"]*)">(.*?)</tr>', page, re.S):
        if kind == 'day-row':   # «Friday October 30, 2026» → 2026-10-30
            try: day = datetime.datetime.strptime(text(row), '%A %B %d, %Y').date().isoformat()
            except ValueError: day = ''
            continue
        if 'title="Completed"' not in row:
            continue
        num = re.search(r'class="game_datetime"[^>]*>\s*(\d+)\s*-', row)
        teams = re.findall(r'IDTeam=(\d+)', row)
        scores = re.findall(r'<td class="text-center score-col">(.*?)</td>', row, re.S)
        extra = re.search(r'<td class="text-center inning-col">(.*?)</td>', row, re.S)
        if not (num and len(teams) >= 2 and len(scores) == 2):
            continue
        h, a = (text(x) for x in scores)
        if not (h.isdigit() and a.isdigit()):
            continue
        ex = text(extra.group(1)).upper() if extra else ''
        res = 'SO' if 'SO' in ex or 'SHOOT' in ex else 'OT' if 'OT' in ex else 'REG'
        out[int(num.group(1))] = (int(teams[0]), int(teams[-1]), int(h), int(a), res, day)
    return out

def rows(page):
    """Строки таблицы статистики MSO: [имя, команда, ячейки…]."""
    out = []
    for r in re.findall(r'<tr>\s*(<td class=" text-center"></td><td class=" players_name_col.*?)</tr>', page, re.S):
        cells = [text(c) for c in re.findall(r'<td[^>]*>(.*?)</td>', r, re.S)]
        out.append(cells[1:])
    return out

def name(n):
    last, _, first = n.partition(',')
    return f'{first.strip()} {last.strip()}'.strip()

num = lambda v: int(v) if re.fullmatch(r'-?\d+', v or '') else 0

def main():
    data = json.load(open(SEASON_FILE, encoding='utf-8'))
    mso = data['league']['mso']
    q = f'IDLeague={mso["league"]}&IDSeason={mso["season"]}'
    ours = {v: k for k, v in mso['teams'].items()}   # id команды MSO → наш id
    try:
        sched, sk_page, gk_page = (get(p, q) for p in ('schedule_scores/schedule.aspx', 'stats/skater_hockey.aspx', 'stats/goalie_hockey.aspx'))
    except Exception as e:
        log('MSO недоступен:', e); return 1

    # 1. счёт матчей
    changed = []
    games = {g['id']: g for g in data['games']}
    for n, (mh, ma, gh, ga, res, day) in sorted(mso_games(sched).items()):
        pair = {ours.get(mh), ours.get(ma)}
        g = games.get(f'G{n:03d}')
        if not g or {g['home'], g['away']} != pair:   # номера на MSO могли поменять (перенос, отмена) — ищем по паре команд и дате
            g = next((x for x in data['games'] if {x['home'], x['away']} == pair and x.get('date') == day and x.get('status') != 'cancelled'), None)
        if not g:
            log(f'⚠ матч MSO {n:03d} ({day}) не нашёлся в расписании — пропущен'); continue
        goals = {ours[mh]: gh, ours[ma]: ga}
        h, a = goals[g['home']], goals[g['away']]
        sc = g.get('score') or {}
        if g.get('status') == 'final' and sc.get('home', {}).get('total') == h and sc.get('away', {}).get('total') == a and g.get('result') == res:
            continue
        g['status'], g['result'] = 'final', res
        g['score'] = {'home': {'periods': sc.get('home', {}).get('periods', []), 'total': h},
                      'away': {'periods': sc.get('away', {}).get('periods', []), 'total': a}}
        for k, v in (('events', []), ('goalies', []), ('lineups', {'home': [], 'away': []})):
            g.setdefault(k, v)
        changed.append(f'{g["id"]} {h}:{a}{"" if res == "REG" else " " + res}')

    # 2. игроки и вратари
    skaters = [dict(name=name(r[0]), team=r[1], pos=r[2], gp=num(r[3]), g=num(r[4]), a=num(r[5]), pts=num(r[6]), pim=num(r[7]))
               for r in rows(sk_page) if len(r) >= 8]
    skaters.sort(key=lambda x: (-x['pts'], -x['g'], x['gp'], x['name']))
    goalies = [dict(name=name(r[0]), team=r[1], gp=num(r[2]), sa=num(r[4]), ga=num(r[5]), sv=num(r[6]), gaa=r[7], svp=r[8], so=num(r[10]))
               for r in rows(gk_page) if len(r) >= 11]
    goalies.sort(key=lambda x: (-(x['sv'] / x['sa'] if x['sa'] else 0), x['name']))
    stats = {'skaters': skaters, 'goalies': goalies}
    old = json.load(open(MSO_STATS_FILE, encoding='utf-8')) if os.path.exists(MSO_STATS_FILE) else {}
    stats_changed = {'skaters': old.get('skaters'), 'goalies': old.get('goalies')} != stats
    if stats_changed:
        changed.append(f'статистика: игроков {len(skaters)}, вратарей {len(goalies)}')

    if not changed and not FORCE:
        log('без изменений'); return 0
    log('изменения:', '; '.join(changed) or '(--force)')
    if DRY:
        return 0

    # 3. запись данных
    if any(c.startswith('G') for c in changed):
        shutil.copy(SEASON_FILE, SEASON_FILE.replace('.json', '.prev.json'))
        data['updated'] = datetime.date.today().isoformat()
        json.dump(data, open(SEASON_FILE, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    stats['updated'] = datetime.datetime.now().isoformat(timespec='minutes')
    json.dump(stats, open(MSO_STATS_FILE, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

    # 4. сборка только статистических частей
    py = sys.executable
    for t in ('build_teams.py', 'build_stats.py'):
        subprocess.run([py, os.path.join(ROOT, 'tools', t)], check=True, stdout=subprocess.DEVNULL)
    shutil.copytree(os.path.join(SRC, 'en'), os.path.join(SITE, 'en'), dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('*.bak*', '*.prev.json', '*.pre-*', '_example.json'))
    paths = ['en/*.html', 'en/stats.css', 'en/data/season-2026-27.json', 'en/data/mso-stats.json', 'teams.html', 'index.html', 'schedule.html']
    for d in ('teams', 'players'):
        os.makedirs(os.path.join(SITE, d), exist_ok=True)
        for f in os.listdir(os.path.join(SRC, d)):
            if f.endswith('.html'):
                open(os.path.join(SITE, d, f), 'w', encoding='utf-8').write(fill(open(os.path.join(SRC, d, f), encoding='utf-8').read()))
        paths.append(d)
    if CLOUD:   # данные сезона в .sync — источник для следующих запусков и для локальной сборки
        paths.append(os.path.relpath(os.path.join(SRC, 'en', 'data'), SITE))
    open(os.path.join(SITE, 'teams.html'), 'w', encoding='utf-8').write(fill(open(os.path.join(SRC, 'teams.html'), encoding='utf-8').read()))
    for p in ('index', 'schedule'):   # опубликованную страницу правим на месте, без пересборки из site-v2
        f = os.path.join(SITE, p + '.html')
        before = open(f, encoding='utf-8').read()   # читать до открытия на запись, иначе файл обнулится
        after = results_fill(p, before)
        if len(after) < len(before) * 0.8 or '</html>' not in after:
            log(f'⚠ {p}.html после правки подозрительно короткий — не пишу и не публикую'); return 1
        open(f, 'w', encoding='utf-8').write(after)

    # 5. публикация: только перечисленные пути
    git = lambda *a, **k: subprocess.run(['git', *a], cwd=SITE, **k)
    git('add', '--', *paths, check=True)
    if git('diff', '--cached', '--quiet').returncode == 0:
        log('на сайте уже актуально'); return 0
    git('commit', '-q', '-m', 'Stats sync from MyStatsOnline: ' + '; '.join(changed), check=True)
    r = git('push', '-q', capture_output=True, text=True)
    if r.returncode:   # пока шёл запуск, кто-то запушил (локальная сборка) — подтянуть и повторить
        git('pull', '--rebase', '--autostash', '-q')
        r = git('push', '-q', capture_output=True, text=True)
    if r.returncode:
        log('⚠ push не прошёл:', r.stderr.strip()); return 1
    log('опубликовано')
    if os.environ.get('GITHUB_OUTPUT'):
        open(os.environ['GITHUB_OUTPUT'], 'a').write('published=true\n')
    return 0

if __name__ == '__main__':
    sys.exit(main())
