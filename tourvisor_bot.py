import sqlite3
import requests
import datetime
import time
import schedule

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
            link TEXT
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
    conn.commit()
    conn.close()

def fetch_tours():
    today = datetime.date.today()
    date_from = today + datetime.timedelta(days=30)
    date_to = date_from + datetime.timedelta(days=7)

    df_str = date_from.strftime("%d.%m.%Y")
    dt_str = date_to.strftime("%d.%m.%Y")

    print(f"Searching tours from {df_str} to {dt_str}...")

    search_url = f"https://tourvisor.ru/xml/modsearch.php?datefrom={df_str}&dateto={dt_str}&directflight=0&regular=1&nightsfrom=10&nightsto=10&adults=2&child=2&childage=7,14&meal=7,9&rating=4.5&stars=5,6&country=4&departure=3&pricefrom=0&priceto=0&currency=0&formmode=0&pricetype=0"

    try:
        resp = requests.get(search_url, headers=HEADERS, timeout=10)
        reqid = resp.json()['result']['requestid']
    except Exception as e:
        print("Error initiating search:", e)
        return []

    print(f"Request ID: {reqid}, polling...")

    hotels = []
    for _ in range(15): # poll up to ~30s
        time.sleep(2)
        res_url = f"https://tourvisor.ru/xml/result.php?requestid={reqid}&type=result&format=json"
        try:
            res_resp = requests.get(res_url, headers=HEADERS, timeout=10)
            res_data = res_resp.json()
            status = res_data.get('data', {}).get('status', {})

            if status.get('state') == 'finished':
                hotels = res_data.get('data', {}).get('result', {}).get('hotel', [])
                break
        except Exception as e:
            print("Error polling:", e)
            continue

    if not hotels:
        print("Failed to get results or search timed out.")
        return []

    tours = []
    for h in hotels:
        flydate = ""
        if 'tours' in h and 'tour' in h['tours'] and len(h['tours']['tour']) > 0:
            flydate = h['tours']['tour'][0].get('flydate', '')

        tours.append({
            'hotel_id': h.get('hotelcode'),
            'hotel_name': h.get('hotelname'),
            'price': h.get('price'),
            'flydate': flydate,
            'link': h.get('fulldesclink', f"https://tourvisor.ru/countries#!/hotel={h.get('hotelcode')}")
        })

    tours.sort(key=lambda x: x['price'])
    return tours[:15]

def send_telegram(message):
    print(f"[TELEGRAM to @ehsrop48]:\n{message}")
    token = '8716203026:AAFEeNjtR_bPRFY7o1Mv-OOpTuIehtDolas'
    chat_id = '@ehsrop48'
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        resp = requests.post(url, json={"chat_id": chat_id, "text": message}, timeout=10)
        if resp.status_code != 200:
            print("Telegram Error:", resp.text)
    except Exception as e:
        print("Failed to send Telegram message:", e)

def send_email(subject, body):
    print(f"[EMAIL to supercuper@mail.ru]:\nSubject: {subject}\nBody: {body}")

def check_and_save_tours(tours):
    if not tours:
        return

    conn = sqlite3.connect('tours.db')
    c = conn.cursor()
    now = datetime.datetime.now().isoformat()

    for t in tours:
        hotel_id = t['hotel_id']
        current_price = t['price']
        hotel_name = t['hotel_name']

        c.execute('SELECT MIN(price) FROM results WHERE hotel_id = ?', (hotel_id,))
        row = c.fetchone()
        min_price = row[0]

        if min_price is not None:
            drop_percentage = ((min_price - current_price) / min_price) * 100
            if drop_percentage >= 5.0:
                msg = f"PRICE DROP ALERT!\nHotel: {hotel_name}\nOld Lowest: {min_price} RUB\nNew Price: {current_price} RUB\nDrop: {drop_percentage:.1f}%"
                send_telegram(msg)
                send_email(f"Price Drop: {hotel_name}", msg)

        c.execute('''
            INSERT INTO results (timestamp, hotel_id, hotel_name, price, flydate, link)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (now, hotel_id, hotel_name, current_price, t.get('flydate', ''), t.get('link', '')))

    conn.commit()
    conn.close()
    print("Checked prices and saved to DB.")

def generate_html(tours):
    if not tours:
        return

    html = """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Top 15 Tours</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 40px; }
        table { border-collapse: collapse; width: 100%; margin-top: 20px; }
        th, td { border: 1px solid #ddd; padding: 12px; text-align: left; }
        th { background-color: #027ad0; color: white; }
        tr:nth-child(even) { background-color: #f2f2f2; }
        .update-time { color: #555; font-size: 0.9em; }
        a { color: #027ad0; text-decoration: none; font-weight: bold; }
        a:hover { text-decoration: underline; }
    </style>
</head>
<body>
    <h2>Top 15 Tours (Turkey from Yekaterinburg, 10 nights)</h2>
    <p class="update-time">Last updated: {update_time}</p>
    <table>
        <tr>
            <th>Rank</th>
            <th>Hotel</th>
            <th>Price (RUB)</th>
            <th>Fly Date</th>
        </tr>
"""

    for i, t in enumerate(tours, 1):
        html += f"""        <tr>
            <td>{i}</td>
            <td><a href="{t['link']}" target="_blank">{t['hotel_name']}</a></td>
            <td>{t['price']:,}</td>
            <td>{t['flydate']}</td>
        </tr>
"""

    html += """    </table>
</body>
</html>"""

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    html = html.replace("{update_time}", now)

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("HTML updated.")

def run_job():
    print(f"[{datetime.datetime.now()}] Running scheduled job...")
    res = fetch_tours()
    if res:
        check_and_save_tours(res)
        generate_html(res)
    else:
        print("No tours found.")

if __name__ == "__main__":
    init_db()

    # Run once at startup
    run_job()

    # Schedule logic
    schedule.every().day.at("04:00").do(run_job)
    schedule.every().day.at("15:00").do(run_job)

    print("Scheduler started. Waiting for jobs...")
    while True:
        schedule.run_pending()
        time.sleep(60)
