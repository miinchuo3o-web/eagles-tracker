from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
from datetime import datetime

app = Flask(__name__)
CORS(app)

HOME_STADIUM = '대전'
AWAY_STADIUMS = ['잠실', '문학', '대구', '창원', '수원', '사직', '고척', '광주']

def fetch_naver_schedule(date_str):
    """네이버 스포츠 KBO 일정 API"""
    date_nodash = date_str.replace('-', '')  # 20260328
    url = f"https://sports.news.naver.com/kbaseball/schedule/index.nhn?year={date_str[:4]}&month={date_str[5:7]}"

    # 네이버 스포츠 KBO 경기 결과 API
    api_url = "https://api-gw.sports.naver.com/schedule/games"
    params = {
        'fields': 'basic,schedule,gameId,homeTeamCode,awayTeamCode,homeTeamScore,awayTeamScore,statusCode,stadium',
        'leagueCode': 'KBO',
        'fromDate': date_str,
        'toDate': date_str,
        'roundCode': '',
        'size': 20,
    }
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36',
        'Referer': 'https://sports.news.naver.com/',
        'Origin': 'https://sports.news.naver.com',
    }

    res = requests.get(api_url, params=params, headers=headers, timeout=15)
    return res.json()


def fetch_naver_schedule_v2(date_str):
    """네이버 스포츠 KBO 일정 API v2"""
    year = date_str[:4]
    month = date_str[5:7]
    date_nodash = date_str.replace('-', '')

    api_url = f"https://sports.news.naver.com/kbaseball/schedule/index.nhn"
    params = {
        'year': year,
        'month': month,
    }
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36',
        'Referer': 'https://sports.news.naver.com/kbaseball/schedule/index.nhn',
    }
    res = requests.get(api_url, params=params, headers=headers, timeout=15)

    from bs4 import BeautifulSoup
    soup = BeautifulSoup(res.text, 'html.parser')
    return soup, res.text


def fetch_daum_sports(date_str):
    """다음 스포츠 KBO API"""
    date_nodash = date_str.replace('-', '')
    api_url = f"https://sports.daum.net/api/game/schedule/kbo?date={date_nodash}"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36',
        'Referer': 'https://sports.daum.net/',
    }
    res = requests.get(api_url, headers=headers, timeout=15)
    return res.json()


TEAM_CODE = {
    'HH': '한화', 'OB': '두산', 'LG': 'LG', 'SS': '삼성',
    'SK': 'SSG', 'NC': 'NC', 'KT': 'KT', 'LT': '롯데',
    'WO': '키움', 'HT': 'KIA',
    # 다음 스포츠 코드
    'HAN': '한화', 'DUS': '두산', 'LGT': 'LG', 'SAM': '삼성',
    'SSG': 'SSG', 'NCO': 'NC', 'KTW': 'KT', 'LOT': '롯데',
    'KIW': '키움', 'KIA': 'KIA',
}

def code_to_name(code):
    return TEAM_CODE.get(code, code)


@app.route('/game')
def get_game():
    date_str = request.args.get('date', '').strip()
    if not date_str:
        return jsonify({'error': 'date 필요'}), 400
    try:
        datetime.strptime(date_str, '%Y-%m-%d')
    except:
        return jsonify({'error': '날짜 형식 오류'}), 400

    # 다음 스포츠 API 시도
    try:
        data = fetch_daum_sports(date_str)
        games = data.get('schedule', data.get('games', data.get('data', [])))
        if isinstance(data, dict):
            # 여러 키 시도
            for key in ['schedule', 'games', 'data', 'result', 'list']:
                if key in data and data[key]:
                    games = data[key]
                    break

        for g in (games if isinstance(games, list) else []):
            home_code = g.get('homeTeamCode', g.get('hometeamcode', ''))
            away_code = g.get('awayTeamCode', g.get('awayteamcode', ''))
            home_name = code_to_name(home_code) or g.get('homeTeamName', g.get('hometeamname', ''))
            away_name = code_to_name(away_code) or g.get('awayTeamName', g.get('awayteamname', ''))

            is_hanwha_home = '한화' in home_name
            is_hanwha_away = '한화' in away_name
            if not (is_hanwha_home or is_hanwha_away):
                continue

            stadium = g.get('stadium', g.get('stadiumName', g.get('stadiumname', '')))
            if HOME_STADIUM in stadium:
                home_away = '홈'
            elif any(s in stadium for s in AWAY_STADIUMS):
                home_away = '원정'
            else:
                home_away = '홈' if is_hanwha_home else '원정'

            is_away = home_away == '원정'
            opponent = home_name if is_away else away_name
            h_score = g.get('homeTeamScore', g.get('hometeamscore'))
            a_score = g.get('awayTeamScore', g.get('awayteamscore'))
            hanwha_score = a_score if is_away else h_score
            opp_score = h_score if is_away else a_score

            result = None
            if hanwha_score is not None and opp_score is not None:
                try:
                    hs, os = int(hanwha_score), int(opp_score)
                    result = '승' if hs > os else ('패' if hs < os else '무')
                except:
                    pass

            return jsonify({
                'found': True,
                'date': date_str,
                'opponent': opponent,
                'hanwha_score': hanwha_score,
                'opponent_score': opp_score,
                'result': result,
                'home_away': home_away,
                'stadium': stadium,
            })

    except Exception as e:
        pass

    return jsonify({'found': False, 'date': date_str})


@app.route('/debug')
def debug():
    date_str = request.args.get('date', '2026-03-28').strip()
    results = {}

    # 다음 스포츠 API 테스트
    try:
        data = fetch_daum_sports(date_str)
        results['daum_raw'] = str(data)[:2000]
    except Exception as e:
        results['daum_error'] = str(e)

    # 네이버 API 테스트
    try:
        data2 = fetch_naver_schedule(date_str)
        results['naver_raw'] = str(data2)[:2000]
    except Exception as e:
        results['naver_error'] = str(e)

    return jsonify(results)


@app.route('/health')
def health():
    return jsonify({'status': 'ok'})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
