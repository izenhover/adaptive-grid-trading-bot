from bitpin import Client
import os
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).resolve().parent / ".env")

api_key = os.getenv("BITPIN_API_KEY")
api_secret = os.getenv("BITPIN_API_SECRET")
if not api_secret:
    api_secret = os.getenv("BITPIN_SECRET_KEY")

client = Client(api_key=api_key, api_secret=api_secret)

print("متدهای موجود در کلاینت:")
for method in dir(client):
    if not method.startswith("_"):
        print("  - " + method)