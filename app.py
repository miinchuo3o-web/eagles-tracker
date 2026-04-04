from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
from datetime import datetime
import calendar

app = Flask(__name__)
CORS(app)

HOME_STADIUM = '대전'
AWAY_STADIUMS = ['잠실', '문학', '대구', '창원', '수원', '사직', '고척', '광주']

def fetch_naver_kbo(year, month):
    last_day = calendar.monthrange(year, month)[1]
    from_date = f"{year}-{month:02d}-01"
    to_date = f"{year}-{month:02d}-{last_day:02d}"

    url = "https://api-gw.sports.naver.com/schedule/games"
    params = {
        'fields': 'basic,schedule,baseball,manualRelayUrl',
        'upperCategoryId': 'kbaseball',
        'categoryId': 'kbo',
        'fromDate': from_date,
        'toDate': to_date,
        'roundCodes': '',
        'size': 500,
    }
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36',
        'Referer': 'https://m.sports.naver.com/kbaseball/schedule/index',
        'Origin': 'https://m.sports.naver.com',
    }
    res = requests.get(url, params=params, headers=headers, timeout=15)
    return res.json()


def find_hanwha(data, date_str):
    # 결과 구조에서 게임 목록 추출
    games = []
    if isinstance(data, dict):
        result = data.get('result', data)
        games = result.get('games', []) if isinstance(result, dict) else []
        if not games:
            for key in ['games', 'data', 'list', 'schedule']:
                val = data.get(key, [])
                if isinstance(val, list) and val:
                    games = val
                    break

    for g in games:
        if not isinstance(g, dict):
            continue

        game_date = g.get('gameDate', '')[:10]
        if game_date != date_str:
            continue

        home_name = g.get('homeTeamName', '')
        away_name = g.get('awayTeamName', '')
        home_code = g.get('homeTeamCode', '')
        away_code = g.get('awayTeamCode', '')

        is_hanwha_home = '한화' in home_name or home_code == 'HH'
        is_hanwha_away = '한화' in away_name or away_code == 'HH'

        if not (is_hanwha_home or is_hanwha_away):
            continue

        stadium = g.get('stadium', '')

        if HOME_STADIUM in stadium:
            home_away = '홈'
        elif any(s in stadium for s in AWAY_STADIUMS):
            home_away = '원정'
        else:
            home_away = '홈' if is_hanwha_home else '원정'

        is_away = home_away == '원정'
        opponent = home_name if is_away else away_name
        h_score = g.get('awayTeamScore') if is_away else g.get('homeTeamScore')
        o_score = g.get('homeTeamScore') if is_away else g.get('awayTeamScore')

        result = None
        status = g.get('statusCode', '')
        if status in ('RESULT', 'CLOSE', 'END') or g.get('statusInfo', '') in ('종료', '경기종료'):
            try:
                hs, os = int(h_score), int(o_score)
                result = '승' if hs > os else ('패' if hs < os else '무')
            except:
                pass

        return {
            'found': True,
            'date': date_str,
            'opponent': opponent,
            'hanwha_score': h_score,
            'opponent_score': o_score,
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
        data = fetch_naver_kbo(dt.year, dt.month)
        result = find_hanwha(data, date_str)
        if result:
            return jsonify(result)
    except Exception as e:
        return jsonify({'found': False, 'error': str(e)}), 500

    return jsonify({'found': False, 'date': date_str})


@app.route('/debug')
def debug():
    date_str = request.args.get('date', '2026-03-28').strip()
    try:
        dt = datetime.strptime(date_str, '%Y-%m-%d')
        data = fetch_naver_kbo(dt.year, dt.month)

        # 게임 목록 추출
        games = []
        result = data.get('result', data)
        games = result.get('games', []) if isinstance(result, dict) else []

        hanwha_games = [g for g in games if '한화' in g.get('homeTeamName','') or '한화' in g.get('awayTeamName','') or g.get('homeTeamCode')=='HH' or g.get('awayTeamCode')=='HH']

        return jsonify({
            'requested_date': date_str,
            'total_games': len(games),
            'hanwha_games': hanwha_games,
            'sample': games[:3],
            'raw_keys': list(data.keys()) if isinstance(data, dict) else str(type(data)),
        })
    except Exception as e:
        return jsonify({'error': str(e)})


@app.route('/health')
def health():
    return jsonify({'status': 'ok'})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
