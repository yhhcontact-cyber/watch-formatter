import os
from datetime import datetime, timedelta, timezone
from functools import wraps

import psycopg2
import psycopg2.extras
from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

HK = timezone(timedelta(hours=8))

DEFAULT_SUPPLIERS = [
    ("+85254664292", "韓國人LUXETIME", ""),
    ("+12295101449", "JERRY", ""),
    ("+85260681901", "Henson D.L", ""),
    ("+8619388924279", "Becky'watches", ""),
    ("+85252816834", "萬事昌10樓He", ""),
    ("+85255868103", "Yoco", ""),
    ("+85265470069", "Li Li watches", ""),
    ("+85251788842", "Jordan Pp Used", ""),
    ("+8618145839070", "Liz", ""),
    ("+85269050448", "Tom watch Yama", ""),
    ("+85263506004", "Don.S", ""),
    ("+85263640033", "Legacy Artisan", ""),
    ("+85267038205", "KEN AU", ""),
    ("+601121110924", "Yew曜 watch", ""),
    ("+85261637668", "SHING Worldtime 18A", ""),
    ("+85267503855", "FH", ""),
    ("+85265551059", "Allen @@", ""),
    ("+85266765777", "Kou", ""),
    ("+85259205732", "Suzanna Mauck", ""),
    ("+18328007624", "Khoa Ng Texas USA", ""),
    ("+85264159223", "Kit World Time", ""),
    ("+85266707420", "合勝改卡錶Yìu", ""),
    ("+85269518626", "恆耀鐘錶 啊一", ""),
    ("+85296306585", "真珍時間", ""),
    ("+85291561900", "Simon Lee", ""),
    ("+85292115831", "Fan@LUXY TIMEPIECES", "Fan@LUXY TIMEPIECES Client LTD 124060"),
    ("+85366505508", "澳門紅利豐Nic Ng", ""),
    ("+60163062406", "Evoanne Cheah", ""),
    ("+85290898060", "First Rolex Sue 老闆", ""),
    ("+8617620193618", "Bebe", ""),
    ("+84963000000", "CV越南", "越南CV"),
]

BRAND_HEADER = {
    "rolex": "ROLEX",
    "tudor": "TUDOR",
    "cartier": "CARTIER",
    "patek philippe": "PATEK PHILIPPE",
    "patek": "PATEK PHILIPPE",
    "vacheron constantin": "VACHERON CONSTANTIN",
    "audemars piguet": "AUDEMARS PIGUET",
    "richard mille": "RICHARD MILLE",
}

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or "watch-formatter-session"
app.permanent_session_lifetime = timedelta(days=7)


def database_url():
    return os.environ.get("DATABASE_URL", "").strip()


def connect():
    url = database_url()
    if not url:
        raise RuntimeError("尚未設定 DATABASE_URL")
    try:
        return psycopg2.connect(url, connect_timeout=20)
    except Exception:
        if ":6543/" not in url:
            raise
        return psycopg2.connect(url.replace(":6543/", ":5432/", 1), connect_timeout=20)


def query(sql, params=None, one=False):
    conn = connect()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SET statement_timeout = '25s'")
            cur.execute(sql, params or ())
            if cur.description is None:
                conn.commit()
                return None
            rows = cur.fetchall()
            conn.commit()
            return rows[0] if one and rows else (None if one else rows)
    finally:
        conn.close()


def execute(sql, params=None):
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = '25s'")
            cur.execute(sql, params or ())
            count = cur.rowcount
        conn.commit()
        return count
    finally:
        conn.close()


def ensure_tables():
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = '30s'")
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS formatter_suppliers (
                    phone TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    aliases TEXT NOT NULL DEFAULT ''
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS formatter_sheets (
                    id SERIAL PRIMARY KEY,
                    username TEXT NOT NULL,
                    supplier_phone TEXT,
                    supplier_name TEXT,
                    source_text TEXT,
                    result_text TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS formatter_settings (
                    setting_key TEXT PRIMARY KEY,
                    setting_value TEXT NOT NULL
                )
                """
            )
            cur.execute(
                """
                INSERT INTO formatter_settings (setting_key, setting_value)
                VALUES ('members_open', '0')
                ON CONFLICT (setting_key) DO NOTHING
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS formatter_members (
                    username TEXT PRIMARY KEY
                )
                """
            )
            cur.execute("SELECT COUNT(*) FROM formatter_members")
            member_count = cur.fetchone()[0]
            cur.execute("SELECT setting_value FROM formatter_settings WHERE setting_key = 'members_open'")
            opened = cur.fetchone()
            if member_count == 0 and opened and opened[0] == "1":
                cur.execute(
                    """
                    INSERT INTO formatter_members (username)
                    SELECT username FROM users WHERE username <> 'admin'
                    ON CONFLICT (username) DO NOTHING
                    """
                )
            cur.executemany(
                """
                INSERT INTO formatter_suppliers (phone, display_name, aliases)
                VALUES (%s, %s, %s)
                ON CONFLICT (phone) DO NOTHING
                """,
                DEFAULT_SUPPLIERS,
            )
        conn.commit()
    finally:
        conn.close()


def member_is_allowed(username):
    if username == "admin":
        return True
    row = query(
        "SELECT username FROM formatter_members WHERE username = %s",
        (username,),
        one=True,
    )
    return bool(row)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("username"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "請先登入"}), 401
            return redirect(url_for("login"))
        if session.get("username") != "admin" and not member_is_allowed(session.get("username")):
            session.clear()
            if request.path.startswith("/api/"):
                return jsonify({"error": "管理員尚未開放你的帳號。"}), 403
            return redirect(url_for("login", closed=1))
        return view(*args, **kwargs)
    return wrapped


def supplier_keys(row):
    keys = [row["phone"], row["display_name"]]
    extra = (row.get("aliases") or "").replace(",", "\n")
    keys.extend(part.strip() for part in extra.splitlines() if part.strip())
    seen = []
    for key in keys:
        if key and key not in seen:
            seen.append(key)
    return seen


def brand_header(brand):
    text = (brand or "").strip()
    return BRAND_HEADER.get(text.lower(), text.upper() or "ROLEX")


def price_token(price_hkd):
    if price_hkd is None:
        return ""
    number = float(price_hkd)
    if number <= 0:
        return ""
    if number.is_integer():
        return str(int(number))
    return str(number)


def formatter_line(row):
    parts = [str(row.get("model_no") or "").strip()]
    details = str(row.get("details") or "").strip()
    prod = str(row.get("prod_date") or "").strip()
    if details:
        parts.append(details)
    if prod:
        parts.append(prod)
    price = price_token(row.get("price_hkd"))
    if price:
        parts.append(price)
    line = " ".join(part for part in parts if part)
    condition = str(row.get("condition") or "").lower()
    if "二手" in condition or "used" in condition:
        line = "USED " + line
    return line


def money_label(row):
    display = str(row.get("price_display") or "").strip()
    if display:
        return display
    price = price_token(row.get("price_hkd"))
    return f"HK${int(float(price)):,}" if price else ""


@app.route("/login", methods=["GET", "POST"])
def login():
    error = "管理員尚未開放你的帳號。" if request.args.get("closed") else ""
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        try:
            user = query(
                "SELECT password_hash, expiry_date FROM users WHERE username = %s",
                (username,),
                one=True,
            )
        except Exception:
            user = None
            error = "資料庫暫時連不上，請稍後再試。"
        if user and not error:
            expiry = user.get("expiry_date") or ""
            expired = False
            if expiry:
                try:
                    exp = datetime.strptime(expiry[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=HK)
                    expired = exp < datetime.now(HK)
                except ValueError:
                    expired = False
            if expired:
                error = "此會員已過期。"
            elif check_password_hash(user["password_hash"], password):
                if username != "admin":
                    try:
                        ensure_tables()
                        opened = member_is_allowed(username)
                    except Exception:
                        opened = False
                    if not opened:
                        error = "管理員尚未開放你的帳號。"
                        user = None
                if user:
                    session.permanent = True
                    session["username"] = username
                    return redirect(url_for("desk"))
            else:
                error = "帳號或密碼不正確。"
        elif not error:
            error = "帳號或密碼不正確。"
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def desk():
    return render_template("desk.html", username=session["username"])


@app.route("/api/suppliers")
@login_required
def suppliers():
    rows = query("SELECT phone, display_name FROM formatter_suppliers ORDER BY display_name")
    people = [{"phone": row["phone"], "name": row["display_name"]} for row in rows]
    return jsonify({"suppliers": people})


@app.route("/api/suppliers", methods=["POST"])
@login_required
def add_supplier():
    payload = request.get_json(silent=True) or {}
    name = (payload.get("name") or "").strip()
    phone = (payload.get("phone") or "").strip().replace(" ", "")
    digits = phone[1:] if phone.startswith("+") else phone
    if not name or not digits.isdigit() or not 8 <= len(digits) <= 15:
        return jsonify({"error": "請填顯示名稱，以及帶國碼的電話。"}), 400
    if not phone.startswith("+"):
        phone = "+" + digits
    execute(
        """
        INSERT INTO formatter_suppliers (phone, display_name, aliases)
        VALUES (%s, %s, '')
        ON CONFLICT (phone) DO UPDATE SET display_name = EXCLUDED.display_name
        """,
        (phone, name),
    )
    return jsonify({"ok": True, "phone": phone, "name": name})


@app.route("/api/suppliers", methods=["DELETE"])
@login_required
def remove_supplier():
    payload = request.get_json(silent=True) or {}
    phones = [str(phone).strip() for phone in (payload.get("phones") or []) if str(phone).strip()]
    if not phones:
        one = (request.args.get("phone") or "").strip()
        if one:
            phones = [one]
    if not phones:
        return jsonify({"error": "請先勾選要刪除的供應商。"}), 400
    execute("DELETE FROM formatter_suppliers WHERE phone = ANY(%s)", (phones,))
    return jsonify({"ok": True, "removed": len(phones)})


@app.route("/api/access", methods=["GET", "POST"])
@login_required
def member_access():
    if session.get("username") != "admin":
        return jsonify({"error": "只有管理員可以指定會員。"}), 403
    if request.method == "POST":
        payload = request.get_json(silent=True) or {}
        names = [str(name).strip() for name in (payload.get("usernames") or []) if str(name).strip() and str(name).strip() != "admin"]
        conn = connect()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM formatter_members")
                if names:
                    cur.execute(
                        """
                        INSERT INTO formatter_members (username)
                        SELECT username FROM users
                        WHERE username = ANY(%s) AND username <> 'admin'
                        """,
                        (names,),
                    )
            conn.commit()
        finally:
            conn.close()
    rows = query(
        """
        SELECT users.username,
               EXISTS (
                   SELECT 1 FROM formatter_members
                   WHERE formatter_members.username = users.username
               ) AS allowed
        FROM users
        WHERE users.username <> 'admin'
        ORDER BY users.username
        """
    )
    return jsonify({
        "members": [{"username": row["username"], "allowed": bool(row["allowed"])} for row in rows]
    })


@app.route("/api/quotes")
@login_required
def quotes():
    phone = (request.args.get("phone") or "").strip()
    supplier = query(
        "SELECT phone, display_name, aliases FROM formatter_suppliers WHERE phone = %s",
        (phone,),
        one=True,
    )
    if not supplier:
        return jsonify({"error": "找不到這位供應商"}), 404
    rows = query(
        """
        SELECT DISTINCT ON (upper(model_no))
            brand, series, model_no, condition, prod_date, price_hkd, price_display, details, raw_text, timestamp
        FROM parsed_watches
        WHERE sender = ANY(%s) AND COALESCE(model_no, '') <> ''
        ORDER BY upper(model_no), timestamp DESC
        """,
        (supplier_keys(supplier),),
    )
    grouped = {}
    for row in rows:
        brand = (row.get("brand") or "未分類").strip() or "未分類"
        item = {
            "brand": brand,
            "header": brand_header(brand),
            "series": row.get("series") or "",
            "model": row.get("model_no") or "",
            "condition": row.get("condition") or "",
            "prod_date": row.get("prod_date") or "",
            "price": money_label(row),
            "time": row.get("timestamp") or "",
            "raw": (row.get("raw_text") or "").strip(),
            "line": formatter_line(row),
        }
        grouped.setdefault(brand, []).append(item)
    brands = []
    for brand, items in grouped.items():
        items.sort(key=lambda item: (item["series"], item["model"]))
        brands.append({"brand": brand, "items": items})
    brands.sort(key=lambda group: group["brand"])
    return jsonify({
        "phone": supplier["phone"],
        "name": supplier["display_name"],
        "brands": brands,
    })


@app.route("/api/archives", methods=["GET", "POST"])
@login_required
def archives():
    if request.method == "POST":
        payload = request.get_json(silent=True) or {}
        result = (payload.get("result_text") or "").strip()
        if not result or result in {"等待整理資料...", "未辨識到有效錶款資料。"}:
            return jsonify({"error": "還沒有可存檔的整理結果。"}), 400
        created = datetime.now(HK).strftime("%Y-%m-%d %H:%M:%S")
        execute(
            """
            INSERT INTO formatter_sheets
                (username, supplier_phone, supplier_name, source_text, result_text, created_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                session["username"],
                (payload.get("supplier_phone") or "")[:40],
                (payload.get("supplier_name") or "")[:80],
                payload.get("source_text") or "",
                result,
                created,
            ),
        )
        return jsonify({"ok": True, "created_at": created})
    rows = query(
        """
        SELECT id, supplier_name, supplier_phone, created_at,
               left(result_text, 80) AS preview
        FROM formatter_sheets
        WHERE username = %s
        ORDER BY id DESC
        LIMIT 40
        """,
        (session["username"],),
    )
    return jsonify({"archives": rows})


@app.route("/api/archives/<int:sheet_id>")
@login_required
def archive_detail(sheet_id):
    row = query(
        """
        SELECT id, supplier_name, supplier_phone, source_text, result_text, created_at
        FROM formatter_sheets
        WHERE id = %s AND username = %s
        """,
        (sheet_id, session["username"]),
        one=True,
    )
    if not row:
        return jsonify({"error": "找不到這份存檔"}), 404
    return jsonify(row)


_ready = False


@app.before_request
def prepare_db():
    global _ready
    if _ready or request.path == "/login":
        return None
    try:
        ensure_tables()
        _ready = True
    except Exception as exc:
        if request.path.startswith("/api/"):
            return jsonify({"error": "資料庫尚未就緒"}), 503
        return render_template("login.html", error="資料庫尚未就緒，請確認 Render 已設定 DATABASE_URL。"), 503


if __name__ == "__main__":
    from waitress import serve
    serve(app, host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))
