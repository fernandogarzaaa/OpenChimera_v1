import argparse
import requests
import sys
import json

def fracture_text(text, ratio=0.5):
    url = "http://localhost:7870/token/fracture"
    try:
        response = requests.post(url, json={"text": text, "ratio": ratio})
        response.raise_for_status()
        data = response.json()
        print(json.dumps(data, indent=2))
        return data
    except Exception as e:
        print(f"Error calling CHIMERA Token Fracture: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compress text using CHIMERA Token Fracture")
    parser.add_argument("text", help="Text to compress")
    parser.add_argument("--ratio", type=float, default=0.5, help="Compression ratio (0.1-0.9)")
    args = parser.parse_args()
    
    fracture_text(args.text, args.ratio)