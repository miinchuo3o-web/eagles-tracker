from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
from bs4 import BeautifulSoup
from datetime import datetime

app = Flask(__name__)
CORS(app)

def get_kbo_schedule(year, month):
    url = "https://www.koreabaseball.com/Schedule/Schedule.aspx"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://www.koreabaseball.com/",
        "Accept-Language": "ko-KR,ko;q=0.9",
    }
    session = requests.Session()

    # 먼저 페이지 로드
    res = session.get(url, headers=headers, timeout=15)
    soup = BeautifulSoup(res.text, 'html.parser')

    viewstate = soup.find('input', {'id': '__VIEWSTATE'})
    viewstate_gen = soup.find('input', {'id': '__VIEWSTATEGENERATOR'})
    event_validation = soup.find('input', {'id': '__EVENTVALIDATION'})

    # 연도 먼저 변경
    data_year = {
        '__VIEWSTATE': viewstate['value'] if viewstate else '',
        '__VIEWSTATEGENERATOR': viewstate_gen['value'] if viewstate_gen else '',
        '__EVENTVALIDATION': event_validation['value'] if event_validation else '',
        '__EVENTTARGET': 'ddlYear',
        '__EVENTARGUMENT': '',
        'ddlYear': str(year),
        'ddlMonth': str(month).zfill(2),
        'ddlSeries': '0,9,6',
    }
    res2 = session.post(url, data=data_year, headers=headers, timeout=15)
    soup2 = BeautifulSoup(res2.text, 'html.parser')

    viewstate2 = soup2.find('input', {'id': '__VIEWSTATE'})
    viewstate_gen2 = soup2.find('input', {'id': '__VIEWSTATEGENERATOR'})
    event_validation2 = soup2.find('input', {'id': '__EVENTVALIDATION'})

    # 월 변경
    data_month = {
        '__VIEWSTATE': viewstate2['value'] if viewstate2 else '',
        '__VIEWSTATEGENERATOR': viewstate_gen2['value'] if viewstate_gen2 else '',
        '__EVENTVALIDATION': event_validation2['value'] if event_validation2 else '',
        '__EVENTTARGET': 'ddlMonth',
        '__EVENTARGUMENT': '',
        'ddlYear': str(year),
        'ddlMonth': str(month).zfill(2),
        'ddlSeries': '0,9,6',
    }
    res3 = session.post(url, data=data_month, headers=headers, timeout=15)
    soup3 = BeautifulSoup(res3.text, 'html.parser')

    games = []
    table = soup3.find('table', {'id': 'tblScheduleList'})
    if not table:
        return games

    tbody = table.find('tbody')
    if not tbody:
        return games

    current_date = None
    for row in tbody.find_all('tr'):
        play_cell = row.find('td', class_='play')
        if not play_cell:
            continue

        day_cell = row.find('td', class_='day')
        if day_cell:
            date_text = day_cell.get_text(strip=True)[:5]
            try:
                parts = date_text.replace(' ', '').split('.')
                m = int(parts[0])
                d = int(parts[1])
                current_date = f"{year}-{m:02d}-{d:02d}"
            except Exception as e:
                pass

        if not current_date:
            continue

        # 팀명 추출 - 여러 방법 시도
        team_names = []

        # 방법 1: span 직접 추출
        all_spans = play_cell.find_all('span')
        for sp in all_spans:
            if sp.find('em'):
                continue
            txt = sp.get_text(strip=True)
            if txt and len(txt) <= 6 and not txt.isdigit():
                team_names.append(txt)

        # 점수 추출
        scores = []
        for em in play_cell.find_all('em'):
            for s in em.find_all('span'):
                try:
                    scores.append(int(s.get_text(strip=True)))
                except:
                    pass

        if len(team_names) < 2:
            continue

        away_team = team_names[0]
        home_team = team_names[1]
        away_score = scores[0] if len(scores) > 0 else None
        home_score = scores[1] if len(scores) > 1 else None

        games.append({
            'date': current_date,
            'away_team': away_team,
            'home_team': home_team,
            'away_score': away_score,
            'home_score': home_score,
        })

    return games


@app.route('/game', methods=['GET'])
def get_game():
    date_str = request.args.get('date', '').strip()
    if not date_str:
        return jsonify({'error': 'date 파라미터가 필요해요 (예: ?date=2026-03-28)'}), 400

    try:
        date_obj = datetime.strptime(date_str, '%Y-%m-%d')
    except:
        return jsonify({'error': '날짜 형식이 올바르지 않아요 (예: 2026-03-28)'}), 400

    year = date_obj.year
    month = date_obj.month

    games = []
    try:
        games = get_kbo_schedule(year, month)
    except Exception as e:
        return jsonify({'error': f'KBO 데이터 수집 실패: {str(e)}', 'found': False}), 500

    # 데이터 없으면 인접 월도 시도 (3월 경기가 다음달에 묶이는 경우)
    if not games:
        try:
            next_month = month + 1 if month < 12 else 1
            next_year = year if month < 12 else year + 1
            games = get_kbo_schedule(next_year, next_month)
        except:
            pass

    HANWHA_NAMES = ['한화', 'HH', '이글스']

    for game in games:
        if game['date'] != date_str:
            continue

        away = game['away_team']
        home = game['home_team']
        away_score = game['away_score']
        home_score = game['home_score']

        is_hanwha_away = any(n in away for n in HANWHA_NAMES)
        is_hanwha_home = any(n in home for n in HANWHA_NAMES)

        if not (is_hanwha_away or is_hanwha_home):
            continue

        opponent = home if is_hanwha_away else away
        hanwha_score = away_score if is_hanwha_away else home_score
        opp_score = home_score if is_hanwha_away else away_score
        home_away = '원정' if is_hanwha_away else '홈'

        result = None
        if hanwha_score is not None and opp_score is not None:
            if hanwha_score > opp_score:
                result = '승'
            elif hanwha_score < opp_score:
                result = '패'
            else:
                result = '무'

        return jsonify({
            'found': True,
            'date': date_str,
            'opponent': opponent,
            'hanwha_score': hanwha_score,
            'opponent_score': opp_score,
            'result': result,
            'home_away': home_away,
        })

    return jsonify({'found': False, 'date': date_str})


@app.route('/debug', methods=['GET'])
def debug():
    """날짜의 파싱 결과를 디버그용으로 반환"""
    date_str = request.args.get('date', '2026-03-28')
    try:
        date_obj = datetime.strptime(date_str, '%Y-%m-%d')
        games = get_kbo_schedule(date_obj.year, date_obj.month)
        return jsonify({
            'requested_date': date_str,
            'total_games_found': len(games),
            'games': games[:20]
        })
    except Exception as e:
        return jsonify({'error': str(e)})


@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok'})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
