from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
from datetime import datetime
import calendar

app = Flask(__name__)
CORS(app)

HOME_STADIUM = '대전'
AWAY_STADIUMS = ['잠실', '문학', '대구', '창원', '수원', '사직', '고척', '광주', '마산']

def fetch_naver_kbo(year, month):
    last_day = calendar.monthrange(year, month)[1]
    url = "https://api-gw.sports.naver.com/schedule/games"
    params = {
        'fields': 'basic,schedule,baseball,manualRelayUrl',
        'upperCategoryId': 'kbaseball',
        'categoryId': 'kbo',
        'fromDate': f"{year}-{month:02d}-01",
        'toDate': f"{year}-{month:02d}-{last_day:02d}",
        'roundCodes': '',
        'size': 500,
    }
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36',
        'Referer': 'https://m.sports.naver.com/kbaseball/schedule/index',
        'Origin': 'https://m.sports.naver.com',
    }
    res = requests.get(url, params=params, headers=headers, timeout=15)
    data = res.json()
    return data.get('result', {}).get('games', [])


def find_hanwha(games, date_str):
    for g in games:
        if g.get('gameDate', '')[:10] != date_str:
            continue

        home_code = g.get('homeTeamCode', '')
        away_code = g.get('awayTeamCode', '')
        home_name = g.get('homeTeamName', '')
        away_name = g.get('awayTeamName', '')
        reversed_ha = g.get('reversedHomeAway', False)
        stadium = g.get('stadium', '')

        is_hanwha_home_field = home_code == 'HH' or '한화' in home_name
        is_hanwha_away_field = away_code == 'HH' or '한화' in away_name

        if not (is_hanwha_home_field or is_hanwha_away_field):
            continue

        # reversedHomeAway=True면 homeTeam이 실제로는 원정팀
        # 즉 실제 홈팀은 awayTeam, 실제 원정팀은 homeTeam
        if reversed_ha:
            real_home_name = away_name
            real_away_name = home_name
            real_home_code = away_code
            real_away_code = home_code
            real_home_score = g.get('awayTeamScore')
            real_away_score = g.get('homeTeamScore')
        else:
            real_home_name = home_name
            real_away_name = away_name
            real_home_code = home_code
            real_away_code = away_code
            real_home_score = g.get('homeTeamScore')
            real_away_score = g.get('awayTeamScore')

        # 실제 홈/원정 기준으로 한화 위치 파악
        is_hanwha_real_home = real_home_code == 'HH' or '한화' in real_home_name
        is_hanwha_real_away = real_away_code == 'HH' or '한화' in real_away_name

        # 구장으로 최종 확인
        if HOME_STADIUM in stadium:
            home_away = '홈'
        elif any(s in stadium for s in AWAY_STADIUMS):
            home_away = '원정'
        else:
            home_away = '홈' if is_hanwha_real_home else '원정'

        if home_away == '홈':
            opponent = real_away_name
            hanwha_score = real_home_score
            opp_score = real_away_score
        else:
            opponent = real_home_name
            hanwha_score = real_away_score
            opp_score = real_home_score

        # 승패 계산
        result = None
        winner = g.get('winner', '')
        if g.get('statusCode') == 'RESULT':
            if winner == 'DRAW':
                result = '무'
            else:
                # winner는 원래 homeTeam/awayTeam 기준 (reversed 적용 전)
                # reversed=True면 winner HOME = 실제 원정팀 승리
                if reversed_ha:
                    hanwha_won = (winner == 'AWAY' and is_hanwha_home_field) or \
                                 (winner == 'HOME' and is_hanwha_away_field)
                else:
                    hanwha_won = (winner == 'HOME' and is_hanwha_home_field) or \
                                 (winner == 'AWAY' and is_hanwha_away_field)
                result = '승' if hanwha_won else '패'

        return {
            'found': True,
            'date': date_str,
            'opponent': opponent,
            'hanwha_score': hanwha_score,
            'opponent_score': opp_score,
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
        games = fetch_naver_kbo(dt.year, dt.month)
        result = find_hanwha(games, date_str)
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
        games = fetch_naver_kbo(dt.year, dt.month)
        result = find_hanwha(games, date_str)
        return jsonify({
            'requested_date': date_str,
            'total_games': len(games),
            'result': result,
        })
    except Exception as e:
        return jsonify({'error': str(e)})


@app.route('/health')
def health():
    return jsonify({'status': 'ok'})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
