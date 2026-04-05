from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
from datetime import datetime
import calendar
import hashlib
import os
import secrets
import psycopg2
from psycopg2.extras import RealDictCursor

app = Flask(__name__)
CORS(app)

DATABASE_URL = os.environ.get('DATABASE_URL', '')

TEAMS = {
    'HH': {'name': '한화', 'full': '한화 이글스', 'home': '대전', 'color': '#f97316'},
    'LT': {'name': '롯데', 'full': '롯데 자이언츠', 'home': '사직', 'color': '#e31837'},
    'LG': {'name': 'LG',   'full': 'LG 트윈스',    'home': '잠실', 'color': '#c60c30'},
    'OB': {'name': '두산', 'full': '두산 베어스',   'home': '잠실', 'color': '#131230'},
    'SS': {'name': '삼성', 'full': '삼성 라이온즈', 'home': '대구', 'color': '#1428a0'},
    'SK': {'name': 'SSG',  'full': 'SSG 랜더스',   'home': '문학', 'color': '#ce0e2d'},
    'NC': {'name': 'NC',   'full': 'NC 다이노스',   'home': '창원', 'color': '#071d49'},
    'KT': {'name': 'KT',   'full': 'KT 위즈',      'home': '수원', 'color': '#000000'},
    'WO': {'name': '키움', 'full': '키움 히어로즈', 'home': '고척', 'color': '#820024'},
    'HT': {'name': 'KIA',  'full': 'KIA 타이거즈',  'home': '광주', 'color': '#ea0029'},
}
ALL_STADIUMS = ['잠실', '문학', '대구', '창원', '대전', '수원', '사직', '고척', '광주', '마산']

def get_db():
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    return conn

def init_db():
    conn = get_db()
    cur = conn.cursor()

    # 테이블 생성
    cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            created_at TIMESTAMP DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS records (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            date TEXT NOT NULL,
            opponent TEXT NOT NULL,
            team_score INTEGER,
            opponent_score INTEGER,
            result TEXT,
            home_away TEXT,
            stadium TEXT,
            people INTEGER DEFAULT 1,
            cost INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT NOW()
        );
    ''')

    # 컬럼 개별 추가 (이미 있으면 무시)
    columns = [
        ('users', 'favorite_team', 'TEXT DEFAULT \'\''),
        ('records', 'team', 'TEXT DEFAULT \'HH\''),
        ('records', 'mood', 'TEXT DEFAULT \'\''),
        ('records', 'memo', 'TEXT DEFAULT \'\''),
        ('records', 'team_score', 'INTEGER'),
        ('records', 'hanwha_score', 'INTEGER'),
    ]
    for table, col, coltype in columns:
        try:
            cur.execute(f'ALTER TABLE {table} ADD COLUMN {col} {coltype}')
            conn.commit()
        except Exception:
            conn.rollback()

    # UNIQUE 제약 업데이트
    try:
        cur.execute('ALTER TABLE records DROP CONSTRAINT IF EXISTS records_user_id_date_key')
        conn.commit()
    except Exception:
        conn.rollback()

    try:
        cur.execute('ALTER TABLE records ADD CONSTRAINT records_user_team_date_key UNIQUE(user_id, team, date)')
        conn.commit()
    except Exception:
        conn.rollback()

    cur.close()
    conn.close()

try:
    init_db()
except Exception as e:
    print(f"DB init error: {e}")

def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def get_user_from_token(token):
    if not token:
        return None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT user_id FROM sessions WHERE token=%s', (token,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        return row['user_id'] if row else None
    except:
        return None

def auth_required():
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    return get_user_from_token(token)

# ── 인증 ───────────────────────────────────────────
@app.route('/auth/register', methods=['POST'])
def register():
    data = request.json or {}
    username = data.get('username', '').strip()
    password = data.get('password', '')
    favorite_team = data.get('favorite_team', '')
    if not username or not password:
        return jsonify({'error': '아이디와 비밀번호를 입력해주세요'}), 400
    if len(username) < 2:
        return jsonify({'error': '아이디는 2자 이상이어야 해요'}), 400
    if len(password) < 4:
        return jsonify({'error': '비밀번호는 4자 이상이어야 해요'}), 400
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            'INSERT INTO users (username, password_hash, favorite_team) VALUES (%s,%s,%s) RETURNING id',
            (username, hash_pw(password), favorite_team)
        )
        user_id = cur.fetchone()['id']
        token = secrets.token_hex(32)
        cur.execute('INSERT INTO sessions (token, user_id) VALUES (%s,%s)', (token, user_id))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'token': token, 'username': username, 'favorite_team': favorite_team})
    except psycopg2.errors.UniqueViolation:
        return jsonify({'error': '이미 사용 중인 아이디예요'}), 409
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/auth/login', methods=['POST'])
def login():
    data = request.json or {}
    username = data.get('username', '').strip()
    password = data.get('password', '')
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT * FROM users WHERE username=%s AND password_hash=%s',
                    (username, hash_pw(password)))
        user = cur.fetchone()
        if not user:
            cur.close()
            conn.close()
            return jsonify({'error': '아이디 또는 비밀번호가 틀렸어요'}), 401
        token = secrets.token_hex(32)
        cur.execute('INSERT INTO sessions (token, user_id) VALUES (%s,%s)', (token, user['id']))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'token': token, 'username': username, 'favorite_team': user.get('favorite_team') or ''})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/auth/logout', methods=['POST'])
def logout():
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('DELETE FROM sessions WHERE token=%s', (token,))
        conn.commit()
        cur.close()
        conn.close()
    except:
        pass
    return jsonify({'ok': True})

@app.route('/auth/team', methods=['POST'])
def update_team():
    user_id = auth_required()
    if not user_id:
        return jsonify({'error': '로그인이 필요해요'}), 401
    data = request.json or {}
    team = data.get('favorite_team', '')
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('UPDATE users SET favorite_team=%s WHERE id=%s', (team, user_id))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'ok': True, 'favorite_team': team})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ── 기록 ───────────────────────────────────────────
@app.route('/records', methods=['GET'])
def get_records():
    user_id = auth_required()
    if not user_id:
        return jsonify({'error': '로그인이 필요해요'}), 401
    team = request.args.get('team', '')
    try:
        conn = get_db()
        cur = conn.cursor()
        if team:
            cur.execute('SELECT * FROM records WHERE user_id=%s AND team=%s ORDER BY date DESC', (user_id, team))
        else:
            cur.execute('SELECT * FROM records WHERE user_id=%s ORDER BY date DESC', (user_id,))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return jsonify([dict(r) for r in rows])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/records', methods=['POST'])
def add_record():
    user_id = auth_required()
    if not user_id:
        return jsonify({'error': '로그인이 필요해요'}), 401
    d = request.json or {}
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('''INSERT INTO records
            (user_id, team, date, opponent, team_score, opponent_score, result, home_away, stadium, people, cost, mood, memo)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
            (user_id, d.get('team', 'HH'), d['date'], d['opponent'],
             d.get('team_score'), d.get('opponent_score'),
             d.get('result'), d.get('home_away', ''), d.get('stadium', ''),
             d.get('people', 1), d.get('cost', 0),
             d.get('mood', ''), d.get('memo', '')))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'ok': True})
    except psycopg2.errors.UniqueViolation:
        return jsonify({'error': '해당 날짜 기록이 이미 있어요'}), 409
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/records/<int:record_id>', methods=['DELETE'])
def delete_record(record_id):
    user_id = auth_required()
    if not user_id:
        return jsonify({'error': '로그인이 필요해요'}), 401
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('DELETE FROM records WHERE id=%s AND user_id=%s', (record_id, user_id))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ── KBO 경기 조회 ───────────────────────────────────
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
    return res.json().get('result', {}).get('games', [])

def find_team_game(games, date_str, team_code):
    team_info = TEAMS.get(team_code, {})
    home_stadium = team_info.get('home', '')
    for g in games:
        if g.get('gameDate', '')[:10] != date_str:
            continue
        home_code = g.get('homeTeamCode', '')
        away_code = g.get('awayTeamCode', '')
        home_name = g.get('homeTeamName', '')
        away_name = g.get('awayTeamName', '')
        home_score = g.get('homeTeamScore')
        away_score = g.get('awayTeamScore')
        stadium = g.get('stadium', '')
        winner = g.get('winner', '')
        status = g.get('statusCode', '')

        is_home = home_code == team_code
        is_away = away_code == team_code
        if not (is_home or is_away):
            continue

        if home_stadium and home_stadium in stadium:
            home_away = '홈'
        elif any(s in stadium for s in ALL_STADIUMS):
            home_away = '홈' if is_home else '원정'
        else:
            home_away = '홈' if is_home else '원정'

        if is_home:
            team_score, opp_score, opponent = home_score, away_score, away_name
            result = None if status != 'RESULT' else ('무' if winner=='DRAW' else ('승' if winner=='HOME' else '패'))
        else:
            team_score, opp_score, opponent = away_score, home_score, home_name
            result = None if status != 'RESULT' else ('무' if winner=='DRAW' else ('승' if winner=='AWAY' else '패'))

        return {'found': True, 'date': date_str, 'opponent': opponent,
                'team_score': team_score, 'opponent_score': opp_score,
                'result': result, 'home_away': home_away, 'stadium': stadium}
    return None

@app.route('/game/<team_code>')
def get_game(team_code):
    if team_code not in TEAMS:
        return jsonify({'error': '알 수 없는 팀 코드'}), 400
    date_str = request.args.get('date', '').strip()
    if not date_str:
        return jsonify({'error': 'date 필요'}), 400
    try:
        dt = datetime.strptime(date_str, '%Y-%m-%d')
        games = fetch_naver_kbo(dt.year, dt.month)
        result = find_team_game(games, date_str, team_code)
        return jsonify(result if result else {'found': False, 'date': date_str})
    except Exception as e:
        return jsonify({'found': False, 'error': str(e)}), 500

@app.route('/game')
def get_game_legacy():
    date_str = request.args.get('date', '').strip()
    if not date_str:
        return jsonify({'error': 'date 필요'}), 400
    try:
        dt = datetime.strptime(date_str, '%Y-%m-%d')
        games = fetch_naver_kbo(dt.year, dt.month)
        result = find_team_game(games, date_str, 'HH')
        return jsonify(result if result else {'found': False, 'date': date_str})
    except Exception as e:
        return jsonify({'found': False, 'error': str(e)}), 500

@app.route('/teams')
def get_teams():
    return jsonify(TEAMS)

@app.route('/health')
def health():
    return jsonify({'status': 'ok'})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
