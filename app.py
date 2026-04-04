from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import re

app = Flask(__name__)
CORS(app)

# 대전 = 한화 홈, 나머지 = 원정
HOME_STADIUM = '대전'
AWAY_STADIUMS = ['잠실', '문학', '대구', '창원', '수원', '사직', '고척', '광주']

# 팀명 정규화
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

def get_hidden(soup, field):
    el = soup.find('input', {'id': field})
    return el['value'] if el else ''

def fetch_schedule(year, month):
    url = "https://www.koreabaseball.com/Schedule/Schedule.aspx"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Referer": "https://www.koreabaseball.com/",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9",
    }

    session = requests.Session()
    res = session.get(url, headers=headers, timeout=20)
    soup = BeautifulSoup(res.text, 'html.parser')

    # 연도 선택
    res2 = session.post(url, headers=headers, timeout=20, data={
        '__VIEWSTATE': get_hidden(soup, '__VIEWSTATE'),
        '__VIEWSTATEGENERATOR': get_hidden(soup, '__VIEWSTATEGENERATOR'),
        '__EVENTVALIDATION': get_hidden(soup, '__EVENTVALIDATION'),
        '__EVENTTARGET': 'ddlYear',
        '__EVENTARGUMENT': '',
        'ddlYear': str(year),
        'ddlMonth': str(month).zfill(2),
        'ddlSeries': '0,9,6',
    })
    soup2 = BeautifulSoup(res2.text, 'html.parser')

    # 월 선택
    res3 = session.post(url, headers=headers, timeout=20, data={
        '__VIEWSTATE': get_hidden(soup2, '__VIEWSTATE'),
        '__VIEWSTATEGENERATOR': get_hidden(soup2, '__VIEWSTATEGENERATOR'),
        '__EVENTVALIDATION': get_hidden(soup2, '__EVENTVALIDATION'),
        '__EVENTTARGET': 'ddlMonth',
        '__EVENTARGUMENT': '',
        'ddlYear': str(year),
        'ddlMonth': str(month).zfill(2),
        'ddlSeries': '0,9,6',
    })
    return BeautifulSoup(res3.text, 'html.parser'), res3.text

def parse_games(soup, year):
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

        # 날짜
        day = row.find('td', class_='day')
        if day:
            nums = re.findall(r'\d+', day.get_text())
            if len(nums) >= 2:
                current_date = f"{year}-{int(nums[0]):02d}-{int(nums[1]):02d}"

        if not current_date:
            continue

        # 팀명 (em 없는 span)
        teams = []
        for sp in play.find_all('span'):
            if sp.find('em'):
                continue
            t = sp.get_text(strip=True)
            if t and not t.isdigit() and len(t) <= 8:
                teams.append(normalize_team(t))

        # 점수
        scores = []
        for em in play.find_all('em'):
            for sp in em.find_all('span'):
                try:
                    scores.append(int(sp.get_text(strip=True)))
                except:
                    pass

        # 구장명 — class 없는 td들 중에서 찾기
        stadium = ''
        plain_tds = row.find_all('td', class_=False)
        for td in plain_tds:
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
        away, home = g['away'], g['home']
        is_hanwha = '한화' in away or '한화' in home
        if not is_hanwha:
            continue

        # 구장으로 홈/원정 판단
        stadium = g.get('stadium', '')
        if HOME_STADIUM in stadium:
            home_away = '홈'
        elif any(s in stadium for s in AWAY_STADIUMS):
            home_away = '원정'
        else:
            # 구장 모르면 팀 순서로 판단 (away팀이 한화면 원정)
            home_away = '원정' if '한화' in away else '홈'

        is_away = home_away == '원정'
        opponent = home if is_away else away
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
        soup, _ = fetch_schedule(dt.year, dt.month)
        games = parse_games(soup, dt.year)
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
        soup, raw_html = fetch_schedule(dt.year, dt.month)

        table = soup.find('table', {'id': 'tblScheduleList'})
        ddl_year = soup.find('select', {'id': 'ddlYear'})
        ddl_month = soup.find('select', {'id': 'ddlMonth'})

        selected_year = ddl_year.find('option', selected=True).get_text() if ddl_year and ddl_year.find('option', selected=True) else None
        selected_month = ddl_month.find('option', selected=True).get_text() if ddl_month and ddl_month.find('option', selected=True) else None

        games = parse_games(soup, dt.year)
        hanwha_games = [g for g in games if '한화' in g['away'] or '한화' in g['home']]

        return jsonify({
            'requested_date': date_str,
            'has_table': table is not None,
            'selected_year': selected_year,
            'selected_month': selected_month,
            'total_games': len(games),
            'hanwha_games': hanwha_games,
            'sample_games': games[:5],
            'html_snippet': raw_html[raw_html.find('tblScheduleList'):raw_html.find('tblScheduleList')+500] if 'tblScheduleList' in raw_html else 'TABLE NOT FOUND',
        })
    except Exception as e:
        return jsonify({'error': str(e)})


@app.route('/health')
def health():
    return jsonify({'status': 'ok'})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
