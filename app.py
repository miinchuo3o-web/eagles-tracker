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
    }
    session = requests.Session()
    res = session.get(url, headers=headers)
    soup = BeautifulSoup(res.text, 'html.parser')

    viewstate = soup.find('input', {'id': '__VIEWSTATE'})
    viewstate_gen = soup.find('input', {'id': '__VIEWSTATEGENERATOR'})
    event_validation = soup.find('input', {'id': '__EVENTVALIDATION'})

    data = {
        '__VIEWSTATE': viewstate['value'] if viewstate else '',
        '__VIEWSTATEGENERATOR': viewstate_gen['value'] if viewstate_gen else '',
        '__EVENTVALIDATION': event_validation['value'] if event_validation else '',
        '__EVENTTARGET': 'ddlMonth',
        '__EVENTARGUMENT': '',
        'ddlYear': str(year),
        'ddlMonth': str(month).zfill(2),
        'ddlSeries': '0,9,6',
    }

    res2 = session.post(url, data=data, headers=headers)
    soup2 = BeautifulSoup(res2.text, 'html.parser')

    games = []
    table = soup2.find('table', {'id': 'tblScheduleList'})
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
                m, d = date_text.split('.')
                current_date = f"{year}-{int(m):02d}-{int(d):02d}"
            except:
                pass

        if not current_date:
            continue

        # 팀명 추출
        team_spans = play_cell.find_all('span')
        team_names = []
        for sp in team_spans:
            txt = sp.get_text(strip=True)
            if txt and not sp.find('em') and len(txt) <= 4:
                team_names.append(txt)

        # 점수 추출
        scores = []
        for em in play_cell.find_all('em'):
            for s in em.find_all('span'):
                try:
                    scores.append(int(s.get_text(strip=True)))
                except:
                    pass

        away_team = team_names[0] if len(team_names) > 0 else ''
        home_team = team_names[1] if len(team_names) > 1 else ''
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
    date_str = request.args.get('date', '')
    if not date_str:
        return jsonify({'error': 'date 파라미터가 필요해요 (예: ?date=2025-05-01)'}), 400

    try:
        date_obj = datetime.strptime(date_str, '%Y-%m-%d')
    except:
        return jsonify({'error': '날짜 형식이 올바르지 않아요 (예: 2025-05-01)'}), 400

    year = date_obj.year
    month = date_obj.month

    try:
        games = get_kbo_schedule(year, month)
    except Exception as e:
        return jsonify({'error': f'KBO 데이터 수집 실패: {str(e)}'}), 500

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


@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok'})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
