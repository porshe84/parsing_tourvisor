import sqlite3
import requests
import datetime
import time
import schedule
import json
import threading
from flask import Flask, request, jsonify, send_file, render_template_string

app = Flask(__name__)

# Moving the contents of tourvisor_bot.py over to app.py
import sqlite3
import requests
import datetime
import time
import schedule
import json

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://tourvisor.ru/"
}

def init_db():
    conn = sqlite3.connect('tours.db')
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME,
            hotel_id INTEGER,
            hotel_name TEXT,
            price INTEGER,
            flydate TEXT,
            link TEXT,
            usd_rate REAL,
            search_df TEXT,
            search_dt TEXT
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS manual_hotels (
            hotel_id INTEGER PRIMARY KEY
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')

    # Also we might need to add these columns if the table exists
    try:
        c.execute('ALTER TABLE results ADD COLUMN flydate TEXT')
    except sqlite3.OperationalError:
        pass
    try:
        c.execute('ALTER TABLE results ADD COLUMN link TEXT')
    except sqlite3.OperationalError:
        pass
    try:
        c.execute('ALTER TABLE results ADD COLUMN usd_rate REAL')
    except sqlite3.OperationalError:
        pass
    try:
        c.execute('ALTER TABLE results ADD COLUMN search_df TEXT')
    except sqlite3.OperationalError:
        pass
    try:
        c.execute('ALTER TABLE results ADD COLUMN search_dt TEXT')
    except sqlite3.OperationalError:
        pass

    # Initialize default settings if empty
    c.execute('SELECT COUNT(*) FROM settings')
    if c.fetchone()[0] == 0:
        today = datetime.date.today()
        date_from = today + datetime.timedelta(days=30)
        date_to = date_from + datetime.timedelta(days=7)
        c.execute("INSERT INTO settings (key, value) VALUES ('search_df', ?)", (date_from.strftime('%d.%m.%Y'),))
        c.execute("INSERT INTO settings (key, value) VALUES ('search_dt', ?)", (date_to.strftime('%d.%m.%Y'),))

    conn.commit()
    conn.close()

def get_search_dates():
    conn = sqlite3.connect('tours.db')
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key='search_df'")
    row_df = c.fetchone()
    c.execute("SELECT value FROM settings WHERE key='search_dt'")
    row_dt = c.fetchone()
    conn.close()

    df_str = row_df[0] if row_df else ""
    dt_str = row_dt[0] if row_dt else ""
    return df_str, dt_str

def get_usd_rate():
    try:
        r = requests.get("https://www.cbr-xml-daily.ru/daily_json.js", timeout=10)
        return r.json()['Valute']['USD']['Value']
    except:
        return 0.0

def fetch_search_results(df_str, dt_str, extra_hotels=""):
    hotels_param = f"&hotels={extra_hotels}" if extra_hotels else ""
    search_url = f"https://tourvisor.ru/xml/modsearch.php?datefrom={df_str}&dateto={dt_str}&directflight=0&regular=1&nightsfrom=10&nightsto=10&adults=2&child=2&childage1=7&childage2=14&meal=7,9&rating=4.5&stars=5,6&country=4&departure=3&pricefrom=0&priceto=0&currency=0&formmode=0&pricetype=0{hotels_param}"

    try:
        resp = requests.get(search_url, headers=HEADERS, timeout=30)
        reqid = resp.json()['result']['requestid']
    except Exception as e:
        print("Error initiating search:", e)
        return []

    print(f"Request ID: {reqid}, polling...")

    hotels = []
    for _ in range(25):
        time.sleep(2)
        res_url = f"https://tourvisor.ru/xml/result.php?requestid={reqid}&type=result&format=json"
        try:
            res_resp = requests.get(res_url, headers=HEADERS, timeout=30)
            res_data = res_resp.json()
            status = res_data.get('data', {}).get('status', {})

            if status.get('state') == 'finished':
                hotels = res_data.get('data', {}).get('result', {}).get('hotel', [])
                break
        except Exception as e:
            print("Error polling:", e)
            continue

    return hotels

def extract_tours(hotels):
    tours = []
    for h in hotels:
        flydate = ""
        tour_link = f"https://tourvisor.ru/countries#!/hotel={h.get('hotelcode')}"
        if 'tours' in h and 'tour' in h['tours'] and len(h['tours']['tour']) > 0:
            first_tour = h['tours']['tour'][0]
            flydate = first_tour.get('flydate', '')
            tourid = first_tour.get('tourid', '')
            if tourid:
                tour_link = f"https://tourvisor.ru/tours/turkey/ekaterinburg#tvtourid={tourid}"

        tours.append({
            'hotel_id': h.get('hotelcode'),
            'hotel_name': h.get('hotelname'),
            'price': h.get('price'),
            'flydate': flydate,
            'link': tour_link,
            'rating': h.get('hotelrating'),
            'manual': False
        })
    return tours

def fetch_tours():
    df_str, dt_str = get_search_dates()

    print(f"Searching standard tours from {df_str} to {dt_str}...")

    raw_hotels = fetch_search_results(df_str, dt_str)
    all_tours = extract_tours(raw_hotels)
    all_tours.sort(key=lambda x: x['price'])

    # User requested: Skip first 10, keep next 15
    selected_tours = all_tours[10:25]

    # Check for manual hotels
    conn = sqlite3.connect('tours.db')
    c = conn.cursor()
    c.execute('SELECT hotel_id FROM manual_hotels')
    manual_ids = [str(row[0]) for row in c.fetchall()]
    conn.close()

    if manual_ids:
        print(f"Searching manual hotels: {manual_ids}")
        manual_hotels_raw = fetch_search_results(df_str, dt_str, extra_hotels=",".join(manual_ids))
        manual_tours = extract_tours(manual_hotels_raw)

        for mt in manual_tours:
            mt['manual'] = True

        selected_tours.extend(manual_tours)

    return selected_tours

def get_chat_id(token, username):
    try:
        r = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=10).json()
        for res in r.get("result", []):
            msg = res.get("message", {})
            chat = msg.get("chat", {})
            if chat.get("username") == username.lstrip('@'):
                return chat.get("id")
    except:
        pass
    return None

def send_telegram(message):
    print(f"[TELEGRAM to @ehsrop48]:\n{message}")
    import os
    token = os.environ.get('TELEGRAM_BOT_TOKEN')

    if not token:
        print("Error: TELEGRAM_BOT_TOKEN environment variable not set.")
        return

    # Try to resolve chat_id from username if user has sent a message to the bot
    chat_id = os.environ.get('TELEGRAM_CHAT_ID')
    if not chat_id:
        chat_id = get_chat_id(token, 'ehsrop48')

    if not chat_id:
        print("Telegram Error: Could not resolve numeric chat_id for @ehsrop48. Please send a message to the bot first, or set TELEGRAM_CHAT_ID env var.")
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        resp = requests.post(url, json={"chat_id": chat_id, "text": message}, timeout=10)
        if resp.status_code != 200:
            print("Telegram Error:", resp.text)
    except Exception as e:
        print("Failed to send Telegram message:", e)

def send_email(subject, body):
    print(f"[EMAIL to supercuper@mail.ru]:\nSubject: {subject}\nBody: {body}")

def check_and_save_tours(tours, usd_rate):
    if not tours:
        return

    conn = sqlite3.connect('tours.db')
    c = conn.cursor()
    now = datetime.datetime.now().isoformat()
    df_str, dt_str = get_search_dates()

    for t in tours:
        hotel_id = t['hotel_id']
        current_price = t['price']
        hotel_name = t['hotel_name']

        # Only compare minimums for the currently active search date range
        c.execute('SELECT MIN(price) FROM results WHERE hotel_id = ? AND search_df = ? AND search_dt = ?', (hotel_id, df_str, dt_str))
        row = c.fetchone()
        min_price = row[0]

        if min_price is not None:
            drop_percentage = ((min_price - current_price) / min_price) * 100
            if drop_percentage >= 5.0:
                msg = f"PRICE DROP ALERT!\nHotel: {hotel_name}\nOld Lowest: {min_price} RUB\nNew Price: {current_price} RUB\nDrop: {drop_percentage:.1f}%"
                send_telegram(msg)
                send_email(f"Price Drop: {hotel_name}", msg)

        c.execute('''
            INSERT INTO results (timestamp, hotel_id, hotel_name, price, flydate, link, usd_rate, search_df, search_dt)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (now, hotel_id, hotel_name, current_price, t.get('flydate', ''), t.get('link', ''), usd_rate, df_str, dt_str))

    conn.commit()
    conn.close()
    print("Checked prices and saved to DB.")

def generate_html(tours):
    if not tours:
        return

    conn = sqlite3.connect('tours.db')
    c = conn.cursor()

    df_str, dt_str = get_search_dates()
    hotel_ids = [str(t['hotel_id']) for t in tours]
    placeholders = ','.join('?' * len(hotel_ids))

    # Extract unique timestamps for the shared X-axis, scoped to current search date
    c.execute(f'''
        SELECT DISTINCT timestamp
        FROM results
        WHERE hotel_id IN ({placeholders}) AND search_df = ? AND search_dt = ?
        ORDER BY timestamp ASC
    ''', (*hotel_ids, df_str, dt_str))

    raw_timestamps = [row[0] for row in c.fetchall()]
    # Format labels for the chart
    chart_labels = []
    for ts in raw_timestamps:
        dt_obj = datetime.datetime.fromisoformat(ts)
        chart_labels.append(dt_obj.strftime("%d.%m %H:%M"))

    chart_datasets = []

    # Convert active df/dt strings back to YYYY-MM-DD for the HTML input values
    try:
        html_df = datetime.datetime.strptime(df_str, "%d.%m.%Y").strftime("%Y-%m-%d")
        html_dt = datetime.datetime.strptime(dt_str, "%d.%m.%Y").strftime("%Y-%m-%d")
    except:
        html_df = ""
        html_dt = ""

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Tours Tracker</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 40px; }}
        table {{ border-collapse: collapse; width: 100%; margin-top: 20px; }}
        th, td {{ border: 1px solid #ddd; padding: 12px; text-align: left; vertical-align: middle; }}
        th {{ background-color: #027ad0; color: white; }}
        tr:nth-child(even) {{ background-color: #f2f2f2; }}
        .update-time {{ color: #555; font-size: 0.9em; }}
        a {{ color: #027ad0; text-decoration: none; font-weight: bold; vertical-align: middle; }}
        a:hover {{ text-decoration: underline; }}
        .chart-container {{ width: 100%; height: 500px; margin-top: 40px; }}
        .controls {{ margin-bottom: 20px; padding: 15px; background: #f9f9f9; border: 1px solid #ddd; display: flex; flex-wrap: wrap; gap: 20px; align-items: center; }}
        .control-group {{ border-right: 1px solid #ccc; padding-right: 20px; }}
        .control-group:last-child {{ border-right: none; }}
        input[type="text"], input[type="date"] {{ padding: 8px; }}
        input[type="text"] {{ width: 250px; }}
        button {{ padding: 8px 15px; background: #027ad0; color: white; border: none; cursor: pointer; }}
        button:hover {{ background: #025b9c; }}
        .remove-btn {{ background: #d9534f; padding: 5px 10px; font-size: 0.8em; margin-top: 0; }}
        .remove-btn:hover {{ background: #c9302c; }}
        .rating-badge {{ display: inline-block; background-color: #5cb85c; color: white; padding: 3px 8px; border-radius: 4px; font-size: 0.85em; font-weight: bold; margin-left: 10px; vertical-align: middle; }}
    </style>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
</head>
<body>
    <h2>Tours Tracker (Turkey from Yekaterinburg, 10 nights)</h2>

    <div class="controls">
        <div class="control-group">
            <form action="/update_dates" method="post">
                <strong>Даты вылета:</strong>
                <input type="date" name="date_from" value="{html_df}" required> -
                <input type="date" name="date_to" value="{html_dt}" required>
                <button type="submit">Изменить интервал</button>
            </form>
        </div>

        <div class="control-group">
            <form action="/add_hotel" method="post">
                <input type="text" name="hotel_input" placeholder="Tourvisor Hotel ID or Link..." required>
                <button type="submit">Добавить отель</button>
            </form>
        </div>

        <div class="control-group">
            <form action="/force_update" method="post">
                <button type="submit">Принудительно обновить цены</button>
            </form>
        </div>

        <div class="control-group">
            <p class="update-time" style="margin: 0;">Last updated: {{update_time}}</p>
        </div>
    </div>

    <table>
        <tr>
            <th>Rank</th>
            <th>Hotel</th>
            <th>Price (RUB)</th>
            <th>Fly Date</th>
            <th>Action</th>
        </tr>
"""

    rank = 1
    for t in tours:
        rating = t.get('rating') or 'N/A'
        hotel_id = t['hotel_id']
        is_manual = t.get('manual', False)

        display_rank = "Manual" if is_manual else rank
        if not is_manual:
            rank += 1

        # Get history from DB scoped to current search date
        c.execute('SELECT timestamp, price, usd_rate FROM results WHERE hotel_id = ? AND search_df = ? AND search_dt = ? ORDER BY timestamp DESC LIMIT 10', (hotel_id, df_str, dt_str))
        rows = c.fetchall()

        history_tooltip = "Price History:&#10;"
        if rows:
            for row in rows:
                dt_obj = datetime.datetime.fromisoformat(row[0])
                formatted_date = dt_obj.strftime("%d.%m.%Y %H:%M")
                usd_rate = row[2]

                if usd_rate:
                    history_tooltip += f"{formatted_date}: {row[1]:,} RUB (USD: {usd_rate})&#10;"
                else:
                    history_tooltip += f"{formatted_date}: {row[1]:,} RUB&#10;"
        else:
            history_tooltip += "No previous data."

        # Build dataset for chart scoped to current search date
        c.execute('SELECT timestamp, price FROM results WHERE hotel_id = ? AND search_df = ? AND search_dt = ? ORDER BY timestamp ASC', (hotel_id, df_str, dt_str))
        hotel_history = {row[0]: row[1] for row in c.fetchall()}

        data_points = []
        for ts in raw_timestamps:
            data_points.append(hotel_history.get(ts, None))

        chart_datasets.append({
            'label': t['hotel_name'],
            'data': data_points,
            'fill': False,
            'tension': 0.1
        })

        action_html = ""
        if is_manual:
            action_html = f'<form action="/remove_hotel" method="post"><input type="hidden" name="hotel_id" value="{hotel_id}"><button type="submit" class="remove-btn">Удалить</button></form>'

        html += f"""        <tr>
            <td>{display_rank}</td>
            <td>
                <a href="{t['link']}" target="_blank" title="{history_tooltip}">{t['hotel_name']}</a>
                <span class="rating-badge">{rating}</span>
            </td>
            <td>{t['price']:,}</td>
            <td>{t['flydate']}</td>
            <td>{action_html}</td>
        </tr>
"""

    conn.close()

    html += """    </table>

    <div class="chart-container">
        <canvas id="priceChart"></canvas>
    </div>

    <script>
        const ctx = document.getElementById('priceChart').getContext('2d');
        const chartLabels = {chart_labels_json};
        const chartDatasets = {chart_datasets_json};

        const myChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: chartLabels,
                datasets: chartDatasets
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    title: {
                        display: true,
                        text: 'История изменения цен'
                    },
                    tooltip: {
                        mode: 'index',
                        intersect: false,
                    },
                    legend: {
                        position: 'right',
                        onClick: function(e, legendItem, legend) {
                            const index = legendItem.datasetIndex;
                            const ci = legend.chart;

                            // Check if the clicked dataset is currently the *only* visible dataset.
                            let visibleCount = 0;
                            let isTargetVisible = false;

                            ci.data.datasets.forEach((ds, i) => {
                                if (ci.isDatasetVisible(i)) {
                                    visibleCount++;
                                    if (i === index) {
                                        isTargetVisible = true;
                                    }
                                }
                            });

                            const isIsolated = isTargetVisible && visibleCount === 1;

                            if (!isIsolated) {
                                // Isolate it.
                                ci.data.datasets.forEach((ds, i) => {
                                    if (i === index) {
                                        ci.show(i);
                                    } else {
                                        ci.hide(i);
                                    }
                                });
                            } else {
                                // Restore all.
                                ci.data.datasets.forEach((ds, i) => {
                                    ci.show(i);
                                });
                            }
                            ci.update();
                        }
                    }
                },
                scales: {
                    x: {
                        display: true,
                        title: {
                            display: true,
                            text: 'Дата и время опроса'
                        }
                    },
                    y: {
                        display: true,
                        title: {
                            display: true,
                            text: 'Цена (RUB)'
                        }
                    }
                }
            }
        });
    </script>
</body>
</html>"""

    now = datetime.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    html = html.replace("{update_time}", now)
    html = html.replace("{chart_labels_json}", json.dumps(chart_labels))
    html = html.replace("{chart_datasets_json}", json.dumps(chart_datasets))

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("HTML updated.")

def run_job():
    print(f"[{datetime.datetime.now()}] Running scheduled job...")
    res = fetch_tours()
    usd_rate = get_usd_rate()
    if res:
        check_and_save_tours(res, usd_rate)
        generate_html(res)
    else:
        print("No tours found.")

@app.route('/')
def index():
    try:
        with open("index.html", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "Not generated yet. Please wait or force update."

@app.route('/add_hotel', methods=['POST'])
def add_hotel():
    hotel_input = request.form.get('hotel_input', '')
    hotel_id = ""
    hotel_name = "Unknown Hotel"

    # Extract ID from link if provided, otherwise assume it's an ID
    if "hotel=" in hotel_input:
        hotel_id = hotel_input.split("hotel=")[-1].split("&")[0].split("#")[0]
    elif "tvtourid=" in hotel_input:
        tour_id = hotel_input.split("tvtourid=")[-1].split("&")[0].split("#")[0]
        try:
            r = requests.get(f"https://tourvisor.ru/xml/actualize.php?tourid={tour_id}&format=json", headers=HEADERS, timeout=10)
            data = r.json()
            hotel_id = data.get('data', {}).get('tour', {}).get('hotelcode', '')
            hotel_name = data.get('data', {}).get('tour', {}).get('hotelname', 'Unknown Hotel')
        except:
            pass
    else:
        hotel_id = hotel_input.strip()

    if hotel_id.isdigit():
        conn = sqlite3.connect('tours.db')
        c = conn.cursor()
        c.execute('INSERT OR IGNORE INTO manual_hotels (hotel_id) VALUES (?)', (int(hotel_id),))
        conn.commit()
        conn.close()

        msg = f"✅ Добавлен новый отель для отслеживания!\nID: {hotel_id}\nНазвание: {hotel_name}"
        send_telegram(msg)

        # Trigger an immediate run in a background thread so UI doesn't block
        threading.Thread(target=run_job, daemon=True).start()

    return "<script>window.history.back();</script>"

@app.route('/remove_hotel', methods=['POST'])
def remove_hotel():
    hotel_id = request.form.get('hotel_id')
    if hotel_id and hotel_id.isdigit():
        conn = sqlite3.connect('tours.db')
        c = conn.cursor()
        c.execute('DELETE FROM manual_hotels WHERE hotel_id = ?', (int(hotel_id),))
        conn.commit()
        conn.close()

        # Trigger immediate run to update table
        threading.Thread(target=run_job, daemon=True).start()

    return "<script>window.history.back();</script>"

@app.route('/force_update', methods=['POST'])
def force_update():
    threading.Thread(target=run_job, daemon=True).start()
    return "<script>window.history.back();</script>"

@app.route('/update_dates', methods=['POST'])
def update_dates():
    df_input = request.form.get('date_from')
    dt_input = request.form.get('date_to')

    if df_input and dt_input:
        # Expected format from HTML5 input type="date" is YYYY-MM-DD
        try:
            df_obj = datetime.datetime.strptime(df_input, "%Y-%m-%d")
            dt_obj = datetime.datetime.strptime(dt_input, "%Y-%m-%d")

            df_str = df_obj.strftime("%d.%m.%Y")
            dt_str = dt_obj.strftime("%d.%m.%Y")

            conn = sqlite3.connect('tours.db')
            c = conn.cursor()
            c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('search_df', ?)", (df_str,))
            c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('search_dt', ?)", (dt_str,))
            conn.commit()
            conn.close()

            msg = f"📅 Даты поиска изменены:\nС {df_str} по {dt_str}"
            send_telegram(msg)

            threading.Thread(target=run_job, daemon=True).start()
        except ValueError:
            pass

    return "<script>window.history.back();</script>"

def run_schedule():
    import os
    t1 = os.environ.get("SCHEDULE_TIME_1", "04:00")
    t2 = os.environ.get("SCHEDULE_TIME_2", "15:00")
    schedule.every().day.at(t1).do(run_job)
    schedule.every().day.at(t2).do(run_job)

    print("Scheduler started. Waiting for jobs...")
    while True:
        schedule.run_pending()
        time.sleep(60)

if __name__ == "__main__":
    init_db()

    # Run once at startup
    run_job()

    # Start scheduler in a background thread
    t = threading.Thread(target=run_schedule, daemon=True)
    t.start()

    # Start Flask app
    app.run(host='127.0.0.1', port=5001)
