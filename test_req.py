import requests
import time
import datetime

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://tourvisor.ru/"
}
today = datetime.date.today()
date_from = today + datetime.timedelta(days=30)
date_to = date_from + datetime.timedelta(days=7)
df_str = date_from.strftime("%d.%m.%Y")
dt_str = date_to.strftime("%d.%m.%Y")

# childage1=7&childage2=14 is giving the high prices in our test earlier (312k for Kirbiyik)
# Let's verify that again just to be sure.
search_url = f"https://tourvisor.ru/xml/modsearch.php?datefrom={df_str}&dateto={dt_str}&directflight=0&regular=1&nightsfrom=10&nightsto=10&adults=2&child=2&childage1=7&childage2=14&meal=7,9&rating=4.5&stars=5,6&country=4&departure=3&pricefrom=0&priceto=0&currency=0&formmode=0&pricetype=0"
resp = requests.get(search_url, headers=HEADERS, timeout=30)
reqid = resp.json()['result']['requestid']
print(f"reqid childage1=7&childage2=14: {reqid}")
for _ in range(25):
    time.sleep(2)
    res_url = f"https://tourvisor.ru/xml/result.php?requestid={reqid}&type=result&format=json"
    r = requests.get(res_url, headers=HEADERS, timeout=30).json()
    status = r.get('data', {}).get('status', {})
    if status.get('state') == 'finished':
        hotels = r.get('data', {}).get('result', {}).get('hotel', [])
        print("Got", len(hotels), "hotels")
        for h in hotels[:2]:
            print(f"Hotel: {h['hotelname']}, price: {h['price']}")
        break
