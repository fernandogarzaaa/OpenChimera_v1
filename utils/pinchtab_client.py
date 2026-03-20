import requests

BASE_URL = "http://localhost:9867"

def launch_instance(name="agent_browser", mode="headless"):
    """Launch a browser instance."""
    try:
        resp = requests.post(f"{BASE_URL}/instances/launch", json={"name": name, "mode": mode})
        return resp.json()
    except Exception as e:
        return {"status": "error", "message": str(e)}

def open_tab(instance_id, url):
    """Open a tab in an existing instance."""
    try:
        resp = requests.post(f"{BASE_URL}/instances/{instance_id}/tabs/open", json={"url": url})
        return resp.json()
    except Exception as e:
        return {"status": "error", "message": str(e)}

def get_snapshot(tab_id):
    """Get interactive snapshot (token-efficient text/element representation)."""
    try:
        resp = requests.get(f"{BASE_URL}/tabs/{tab_id}/snapshot?filter=interactive")
        return resp.json()
    except Exception as e:
        return {"status": "error", "message": str(e)}

def action(tab_id, action_name, **kwargs):
    """Perform action (click, type, etc). Params are passed as kwargs."""
    try:
        payload = {"action": action_name, **kwargs}
        resp = requests.post(f"{BASE_URL}/tabs/{tab_id}/action", json=payload)
        return resp.json()
    except Exception as e:
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    print("Testing PinchTab bridge...")
    inst = launch_instance()
    if "id" in inst:
        print(f"Launched instance: {inst['id']}")
        tab = open_tab(inst['id'], "https://google.com")
        if "tabId" in tab:
            print(f"Opened tab: {tab['tabId']}")
            snap = get_snapshot(tab['tabId'])
            print(f"Snapshot successful: {len(str(snap))} bytes of data")
        else:
            print("Failed to open tab.")
    else:
        print("Failed to launch instance.")
