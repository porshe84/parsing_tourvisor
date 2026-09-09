import requests
TOKEN = '8716203026:AAFEeNjtR_bPRFY7o1Mv-OOpTuIehtDolas'
CHAT_ID = '@ehsrop48'
resp = requests.post(
    f"https://api.telegram.org/bot{TOKEN}/sendMessage",
    json={"chat_id": CHAT_ID, "text": "Test from Tourvisor Bot"}
)
print(resp.status_code, resp.text)
