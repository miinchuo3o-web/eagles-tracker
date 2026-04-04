from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import re

app = Flask(__name__)
CORS(app)

# KBO 팀명 매핑 (영문 약자 포함)
TEAM_NAMES = {
    'HH': '한화', '한화': '한화', '이글스': '한화',
    'OB': '두산', 'DB': '두산', '두산': '두산', '베어스': '두산',
    'LG': 'LG', '트윈스': 'LG',
    'SS': '삼성', '삼성': '삼성', '라이온즈': '삼성',
    'SK': 'SSG', 'SSG': 'SSG', '랜더스': 'SSG',
    'NC': 'NC', '다이노스': 'NC',
    'KT': 'KT', '위즈': 'KT',
    'LT': '롯데', '롯데': '롯데', '자이언츠': '롯데',
    'WO': '키움', 'HO': '키움', '키움': '키움', '히어로즈': '키움',
    'HT': 'KIA', 'KIA': 'KIA', '타이거즈': 'KIA',
}

HANWHA_KEYS = ['HH', '한화', '이글스']

def normalize_team(name):
    name = name.strip()
    for key, val in TEAM_NAMES.items():
        if key in name:
            return val
    return name

def fetch_schedule(year, month):
    url = "https://www.koreabaseball.com/Schedule/Schedule.aspx"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://www.koreabaseball.com/Schedule/Schedule.aspx",
        "Accept-Language": "ko-KR,ko;q=0.9",
        "Content-Type": "application/x-www-form-urlencoded",
    }

    session = requests.Session()
    # 초기 페이지 로드
    res = session.get(url, headers=headers, timeout=20)
    soup = BeautifulSoup(res.text, 'html.parser')

    def get_hidden(s, field):
        el = s.find('input', {'id': field})
        return el['value'] if el else ''

    # 연도 변경 요청
    data = {
        '__VIEWSTATE': get_hidden(soup, '__VIEWSTATE'),
        '__VIEWSTATEGENERATOR': get_hidden(soup, '__VIEWSTATEGENERATOR'),
        '__EVENTVALIDATION': get_hidden(soup, '__EVENTVALIDATION'),
        '__EVENTTARGET': 'ddlYear',
        '__EVENTARGUMENT': '',
        'ddlYear': str(year),
        'ddlMonth': str(month).zfill(2),
        'ddlSeries': '0,9,6',
    }
    res2 = session.post(url, data=data, headers=headers, timeout=20)
    soup2 = BeautifulSoup(res2.text, 'html.parser')

    # 월 변경 요청
    data2 = {
        '__VIEWSTATE': get_hidden(soup2, '__VIEWSTATE'),
        '__VIEWSTATEGENERATOR': get_hidden(soup2, '__VIEWSTATEGENERATOR'),
        '__EVENTVALIDATION': get_hidden(soup2, '__EVENTVALIDATION'),
        '__EVENTTARGET': 'ddlMonth',
        '__EVENTARGUMENT': '',
        'ddlYear': str(year),
        'ddlMonth': str(month).zfill(2),
        'ddlSeries': '0,9,6',
    }
    res3 = session.post(url, data=data2, headers=headers, timeout=20)
    soup3 = BeautifulSoup(res3.text, 'html.parser')

    return parse_schedule(soup3, year)

def parse_schedule(soup, year):
    games = []
    table = soup.find('table', {'id': 'tblScheduleList'})
    if not table:
        return games

    tbody = table.find('tbody')
    if not tbody:
        return games

    current_date = None

    for row in tbody.find_all('tr'):
        # 경기 정보 없는 행 스킵
        play_cell = row.find('td', class_='play')
        if not play_cell:
            continue

        # 날짜 파싱
        day_cell = row.find('td', class_='day')
        if day_cell:
            raw = day_cell.get_text(strip=True)
            # "03.28(토)" 또는 "03.28" 형태
            nums = re.findall(r'\d+', raw)
            if len(nums) >= 2:
                m, d = int(nums[0]), int(nums[1])
                current_date = f"{year}-{m:02d}-{d:02d}"

        if not current_date:
            continue

        # 팀명 파싱 — span.team 또는 일반 span
        teams = []
        # 방법1: class=team 인 span
        team_spans = play_cell.find_all('span', class_='team')
        if team_spans:
            teams = [s.get_text(strip=True) for s in team_spans]
        else:
            # 방법2: em 태그 제외한 span
            for sp in play_cell.find_all('span'):
                if sp.find('em'):
                    continue
                t = sp.get_text(strip=True)
                if t and not t.isdigit() and len(t) <= 8:
                    teams.append(t)

        if len(teams) < 2:
            continue

        # 점수 파싱
        scores = []
        for em in play_cell.find_all('em'):
            for sp in em.find_all('span'):
                try:
                    scores.append(int(sp.get_text(strip=True)))
                except:
                    pass

        games.append({
            'date': current_date,
            'away_team': normalize_team(teams[0]),
            'home_team': normalize_team(teams[1]),
            'away_score': scores[0] if len(scores) > 0 else None,
            'home_score': scores[1] if len(scores) > 1 else None,
        })

    return games


@app.route('/game')
def get_game():
    date_str = request.args.get('date', '').strip()
    if not date_str:
        return jsonify({'error': 'date 파라미터 필요 (예: ?date=2026-03-28)'}), 400
    try:
        dt = datetime.strptime(date_str, '%Y-%m-%d')
    except:
        return jsonify({'error': '날짜 형식 오류 (예: 2026-03-28)'}), 400

    # 해당 월 조회
    games = []
    try:
        games = fetch_schedule(dt.year, dt.month)
    except Exception as e:
        return jsonify({'found': False, 'error': str(e)}), 500

    # 해당 날짜 한화 경기 찾기
    result = find_hanwha_game(games, date_str)
    if result:
        return jsonify(result)

    return jsonify({'found': False, 'date': date_str})


def find_hanwha_game(games, date_str):
    for g in games:
        if g['date'] != date_str:
            continue
        away, home = g['away_team'], g['home_team']
        is_away = any(k in away for k in HANWHA_KEYS) or away == '한화'
        is_home = any(k in home for k in HANWHA_KEYS) or home == '한화'
        if not (is_away or is_home):
            continue

        opponent = home if is_away else away
        h_score = g['away_score'] if is_away else g['home_score']
        o_score = g['home_score'] if is_away else g['away_score']
        ha = '원정' if is_away else '홈'

        result = None
        if h_score is not None and o_score is not None:
            result = '승' if h_score > o_score else ('패' if h_score < o_score else '무')

        return {
            'found': True,
            'date': date_str,
            'opponent': opponent,
            'hanwha_score': h_score,
            'opponent_score': o_score,
            'result': result,
            'home_away': ha,
        }
    return None


@app.route('/debug')
def debug():
    date_str = request.args.get('date', '2026-03-28').strip()
    try:
        dt = datetime.strptime(date_str, '%Y-%m-%d')
        games = fetch_schedule(dt.year, dt.month)
        return jsonify({
            'requested_date': date_str,
            'total_games': len(games),
            'sample': games[:5],
            'hanwha_games': [g for g in games if any(k in g['away_team'] or k in g['home_team'] for k in HANWHA_KEYS) or '한화' in g['away_team'] or '한화' in g['home_team']],
        })
    except Exception as e:
        return jsonify({'error': str(e)})


@app.route('/health')
def health():
    return jsonify({'status': 'ok'})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
