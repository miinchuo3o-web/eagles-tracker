from flask import Flask, jsonify, request, g
from flask_cors import CORS
import requests
from datetime import datetime
import calendar
import sqlite3
import hashlib
import os
import secrets

app = Flask(__name__)
CORS(app)

HOME_STADIUM = '대전'
AWAY_STADIUMS = ['잠실', '문학', '대구', '창원', '수원', '사직', '고척', '광주', '마산']
DB_PATH = os.environ.get('DB_PATH', '/data/eagles.db')

# ── DB 초기화 ──────────────────────────────────────────────
def get_db():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return db

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    db = get_db()
    db.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            opponent TEXT NOT NULL,
            hanwha_score INTEGER,
            opponent_score INTEGER,
            result TEXT,
            home_away TEXT,
            stadium TEXT,
            people INTEGER DEFAULT 1,
            cost INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id),
            UNIQUE(user_id, date)
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        );
    ''')
    db.commit()
    db.close()

init_db()

# ── 인증 헬퍼 ──────────────────────────────────────────────
def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def get_user_from_token(token):
    if not token:
        return None
    db = get_db()
    row = db.execute('SELECT user_id FROM sessions WHERE token=?', (token,)).fetchone()
    db.close()
    return row['user_id'] if row else None

def auth_required():
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    user_id = get_user_from_token(token)
    return user_id

# ── 인증 API ───────────────────────────────────────────────
@app.route('/auth/register', methods=['POST'])
def register():
    data = request.json or {}
    username = data.get('username', '').strip()
    password = data.get('password', '')
    if not username or not password:
        return jsonify({'error': '아이디와 비밀번호를 입력해주세요'}), 400
    if len(username) < 2:
        return jsonify({'error': '아이디는 2자 이상이어야 해요'}), 400
    if len(password) < 4:
        return jsonify({'error': '비밀번호는 4자 이상이어야 해요'}), 400
    db = get_db()
    try:
        db.execute('INSERT INTO users (username, password_hash) VALUES (?,?)',
                   (username, hash_pw(password)))
        db.commit()
        user_id = db.execute('SELECT id FROM users WHERE username=?', (username,)).fetchone()['id']
        token = secrets.token_hex(32)
        db.execute('INSERT INTO sessions (token, user_id) VALUES (?,?)', (token, user_id))
        db.commit()
        return jsonify({'token': token, 'username': username})
    except sqlite3.IntegrityError:
        return jsonify({'error': '이미 사용 중인 아이디예요'}), 409
    finally:
        db.close()

@app.route('/auth/login', methods=['POST'])
def login():
    data = request.json or {}
    username = data.get('username', '').strip()
    password = data.get('password', '')
    db = get_db()
    user = db.execute('SELECT * FROM users WHERE username=? AND password_hash=?',
                      (username, hash_pw(password))).fetchone()
    if not user:
        db.close()
        return jsonify({'error': '아이디 또는 비밀번호가 틀렸어요'}), 401
    token = secrets.token_hex(32)
    db.execute('INSERT INTO sessions (token, user_id) VALUES (?,?)', (token, user['id']))
    db.commit()
    db.close()
    return jsonify({'token': token, 'username': username})

@app.route('/auth/logout', methods=['POST'])
def logout():
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    db = get_db()
    db.execute('DELETE FROM sessions WHERE token=?', (token,))
    db.commit()
    db.close()
    return jsonify({'ok': True})

# ── 기록 API ───────────────────────────────────────────────
@app.route('/records', methods=['GET'])
def get_records():
    user_id = auth_required()
    if not user_id:
        return jsonify({'error': '로그인이 필요해요'}), 401
    db = get_db()
    rows = db.execute('SELECT * FROM records WHERE user_id=? ORDER BY date DESC', (user_id,)).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])

@app.route('/records', methods=['POST'])
def add_record():
    user_id = auth_required()
    if not user_id:
        return jsonify({'error': '로그인이 필요해요'}), 401
    d = request.json or {}
    db = get_db()
    try:
        db.execute('''INSERT INTO records
            (user_id, date, opponent, hanwha_score, opponent_score, result, home_away, stadium, people, cost)
            VALUES (?,?,?,?,?,?,?,?,?,?)''',
            (user_id, d['date'], d['opponent'], d.get('hanwha_score'), d.get('opponent_score'),
             d.get('result'), d.get('home_away',''), d.get('stadium',''),
             d.get('people', 1), d.get('cost', 0)))
        db.commit()
        return jsonify({'ok': True})
    except sqlite3.IntegrityError:
        return jsonify({'error': '해당 날짜 기록이 이미 있어요'}), 409
    finally:
        db.close()

@app.route('/records/<int:record_id>', methods=['DELETE'])
def delete_record(record_id):
    user_id = auth_required()
    if not user_id:
        return jsonify({'error': '로그인이 필요해요'}), 401
    db = get_db()
    db.execute('DELETE FROM records WHERE id=? AND user_id=?', (record_id, user_id))
    db.commit()
    db.close()
    return jsonify({'ok': True})

# ── KBO 경기 조회 ──────────────────────────────────────────
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

def find_hanwha(games, date_str):
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

        is_hanwha_home = home_code == 'HH' or '한화' in home_name
        is_hanwha_away = away_code == 'HH' or '한화' in away_name
        if not (is_hanwha_home or is_hanwha_away):
            continue

        if HOME_STADIUM in stadium:
            home_away = '홈'
        elif any(s in stadium for s in AWAY_STADIUMS):
            home_away = '원정'
        else:
            home_away = '홈' if is_hanwha_home else '원정'

        if is_hanwha_home:
            hanwha_score, opp_score, opponent = home_score, away_score, away_name
            result = None if status != 'RESULT' else ('무' if winner=='DRAW' else ('승' if winner=='HOME' else '패'))
        else:
            hanwha_score, opp_score, opponent = away_score, home_score, home_name
            result = None if status != 'RESULT' else ('무' if winner=='DRAW' else ('승' if winner=='AWAY' else '패'))

        return {'found': True, 'date': date_str, 'opponent': opponent,
                'hanwha_score': hanwha_score, 'opponent_score': opp_score,
                'result': result, 'home_away': home_away, 'stadium': stadium}
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
        return jsonify(result if result else {'found': False, 'date': date_str})
    except Exception as e:
        return jsonify({'found': False, 'error': str(e)}), 500

@app.route('/health')
def health():
    return jsonify({'status': 'ok'})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
