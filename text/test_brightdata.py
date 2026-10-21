import os
import requests
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("BRIGHT_DATA_API_KEY")

url = "https://api.brightdata.com/datasets/v3/trigger"

headers = {
    "Authorization": f"Bearer {api_key}",
    "Content-Type": "application/json",
}

params = {
    "dataset_id": "gd_le8e811kzy4ggddlq"
}

payload = [
    {
        "url": "https://www.amazon.com/dp/B094NC89P9",
        "max_reviews": 1,
    }
]

response = requests.post(
    url,
    headers=headers,
    params=params,
    json=payload,
    timeout=60,
)
print(api_key)
print("HTTP 状态码：", response.status_code)
print("响应内容：", response.text[:1000])