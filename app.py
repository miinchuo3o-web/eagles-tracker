from flask import Flask, jsonify, request
from flask_cors import CORS
from playwright.sync_api import sync_playwright
from datetime import datetime
import re

app = Flask(__name__)
CORS(app)

HOME_STADIUM = '대전'
AWAY_STADIUMS = ['잠실', '문학', '대구', '창원', '수원', '사직', '고척', '광주']

TEAM_MAP = {
    'HH': '한화', '이글스': '한화',
    'OB': '두산', 'DB': '두산', '베어스': '두산',
    '트윈스': 'LG',
    'SS': '삼성', '라이온즈': '삼성',
    'SK': 'SSG', '랜더스': 'SSG',
    '다이노스': 'NC',
    '위즈': 'KT',
    'LT': '롯데', '자이언츠': '롯데',
    'WO': '키움', 'HO': '키움', '히어로즈': '키움',
    'HT': 'KIA', '타이거즈': 'KIA',
}

def normalize_team(name):
    name = name.strip()
    for k, v in TEAM_MAP.items():
        if k in name:
            return v
    return name

def fetch_schedule_playwright(year, month):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_extra_http_headers({
            'Accept-Language': 'ko-KR,ko;q=0.9'
        })

        page.goto('https://www.koreabaseball.com/Schedule/Schedule.aspx', timeout=30000)
        page.wait_for_load_state('networkidle')

        # 연도 선택
        page.select_option('#ddlYear', str(year))
        page.wait_for_load_state('networkidle')

        # 월 선택
        page.select_option('#ddlMonth', str(month).zfill(2))
        page.wait_for_load_state('networkidle')

        # 시리즈 선택 (전체)
        page.select_option('#ddlSeries', '0,9,6')
        page.wait_for_load_state('networkidle')

        html = page.content()
        browser.close()
        return html

def parse_games(html, year):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, 'html.parser')
    games = []

    table = soup.find('table', {'id': 'tblScheduleList'})
    if not table:
        return games

    tbody = table.find('tbody')
    if not tbody:
        return games

    current_date = None

    for row in tbody.find_all('tr'):
        play = row.find('td', class_='play')
        if not play:
            continue

        day = row.find('td', class_='day')
        if day:
            nums = re.findall(r'\d+', day.get_text())
            if len(nums) >= 2:
                current_date = f"{year}-{int(nums[0]):02d}-{int(nums[1]):02d}"

        if not current_date:
            continue

        teams = []
        for sp in play.find_all('span'):
            if sp.find('em'):
                continue
            t = sp.get_text(strip=True)
            if t and not t.isdigit() and len(t) <= 8:
                teams.append(normalize_team(t))

        scores = []
        for em in play.find_all('em'):
            for sp in em.find_all('span'):
                try:
                    scores.append(int(sp.get_text(strip=True)))
                except:
                    pass

        # 구장명
        stadium = ''
        for td in row.find_all('td'):
            txt = td.get_text(strip=True)
            if any(s in txt for s in ['잠실', '문학', '대구', '창원', '대전', '수원', '사직', '고척', '광주']):
                stadium = txt
                break

        if len(teams) >= 2:
            games.append({
                'date': current_date,
                'away': teams[0],
                'home': teams[1],
                'away_score': scores[0] if len(scores) > 0 else None,
                'home_score': scores[1] if len(scores) > 1 else None,
                'stadium': stadium,
            })

    return games


def find_hanwha(games, date_str):
    for g in games:
        if g['date'] != date_str:
            continue
        if '한화' not in g['away'] and '한화' not in g['home']:
            continue

        stadium = g.get('stadium', '')
        if HOME_STADIUM in stadium:
            home_away = '홈'
        elif any(s in stadium for s in AWAY_STADIUMS):
            home_away = '원정'
        else:
            home_away = '원정' if '한화' in g['away'] else '홈'

        is_away = home_away == '원정'
        opponent = g['home'] if is_away else g['away']
        h = g['away_score'] if is_away else g['home_score']
        o = g['home_score'] if is_away else g['away_score']

        result = None
        if h is not None and o is not None:
            result = '승' if h > o else ('패' if h < o else '무')

        return {
            'found': True,
            'date': date_str,
            'opponent': opponent,
            'hanwha_score': h,
            'opponent_score': o,
            'result': result,
            'home_away': home_away,
            'stadium': stadium,
        }
    return None


@app.route('/game')
def get_game():
    date_str = request.args.get('date', '').strip()
    if not date_str:
        return jsonify({'error': 'date 필요'}), 400
    try:
        dt = datetime.strptime(date_str, '%Y-%m-%d')
    except:
        return jsonify({'error': '날짜 형식 오류'}), 400

    try:
        html = fetch_schedule_playwright(dt.year, dt.month)
        games = parse_games(html, dt.year)
    except Exception as e:
        return jsonify({'found': False, 'error': str(e)}), 500

    result = find_hanwha(games, date_str)
    if result:
        return jsonify(result)
    return jsonify({'found': False, 'date': date_str})


@app.route('/debug')
def debug():
    date_str = request.args.get('date', '2026-03-28').strip()
    try:
        dt = datetime.strptime(date_str, '%Y-%m-%d')
        html = fetch_schedule_playwright(dt.year, dt.month)
        games = parse_games(html, dt.year)
        hanwha = [g for g in games if '한화' in g['away'] or '한화' in g['home']]
        return jsonify({
            'requested_date': date_str,
            'total_games': len(games),
            'hanwha_games': hanwha,
            'sample': games[:5],
        })
    except Exception as e:
        return jsonify({'error': str(e)})


@app.route('/health')
def health():
    return jsonify({'status': 'ok'})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
