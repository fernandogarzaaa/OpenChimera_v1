import requests
import json

url = "http://localhost:7870/token/fracture"
payload = {
    "text": "This is a test message that should be compressed by the token fracture system. It contains some filler words that serve no purpose other than to take up space.",
    "ratio": 0.5
}

try:
    print(f"Testing {url} with payload: {json.dumps(payload)}")
    response = requests.post(url, json=payload, timeout=5)
    print(f"Status Code: {response.status_code}")
    if response.status_code == 200:
        print("Success!")
        print(json.dumps(response.json(), indent=2))
    else:
        print(f"Error: {response.text}")
except Exception as e:
    print(f"Exception: {e}")
