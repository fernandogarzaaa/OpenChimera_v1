import cv2
import os
import time

# Imou Camera RTSP Configuration
IP_ADDRESS = "192.168.68.114"
PASSWORD = "L220341D"
USERNAME = "admin"

# Common Imou/Dahua RTSP patterns
RTSP_URLS = [
    f"rtsp://{USERNAME}:{PASSWORD}@{IP_ADDRESS}:554/live",
    f"rtsp://{USERNAME}:{PASSWORD}@{IP_ADDRESS}:554/cam/realmonitor?channel=1&subtype=0",
    f"rtsp://{USERNAME}:{PASSWORD}@{IP_ADDRESS}:554/live/ch0"
]

BUFFER_DIR = r"D:\openclaw\temp"
BUFFER_FILE = os.path.join(BUFFER_DIR, "cctv_latest.jpg")

os.makedirs(BUFFER_DIR, exist_ok=True)

def capture_stream():
    cap = None
    for url in RTSP_URLS:
        print(f"Attempting to connect to: {url}")
        cap = cv2.VideoCapture(url)
        if cap.isOpened():
            print(f"Successfully connected to {url}")
            break
        else:
            print(f"Failed to connect to {url}")
    
    if cap is None or not cap.isOpened():
        print("Error: Could not open stream at any URL.")
        return

    print("CCTV Vision Bridge Active. Overwriting buffer...")
    while True:
        ret, frame = cap.read()
        if ret:
            # Overwrite the latest frame buffer
            cv2.imwrite(BUFFER_FILE, frame)
            time.sleep(1) 
        else:
            print("Stream lost, attempting reconnect...")
            cap.release()
            time.sleep(5)
            # Re-try URLs
            for url in RTSP_URLS:
                cap = cv2.VideoCapture(url)
                if cap.isOpened():
                    break

if __name__ == "__main__":
    capture_stream()