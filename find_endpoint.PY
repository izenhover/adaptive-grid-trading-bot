import requests

base_url = "https://api.bitpin.org"

# لیست آدرس‌های احتمالی
endpoints = [
    "/api/v1/mkt/currencies/",
    "/api/mkt/currencies/",
    "/v1/mkt/currencies/",
    "/mkt/currencies/",
    "/api/v1/currencies/",
    "/api/currencies/",
]

for endpoint in endpoints:
    url = base_url + endpoint
    try:
        response = requests.get(url, timeout=10)
        print(f"{endpoint:<30} → {response.status_code}")
        if response.status_code == 200:
            print(f"✅ آدرس درست پیدا شد: {url}")
            print("نمونه داده:", response.json()[:2])
            break
    except Exception as e:
        print(f"{endpoint:<30} → خطا: {e}")