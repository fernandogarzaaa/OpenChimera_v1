import cv2
import mediapipe as mp
import time
import os
from audio_out import push_audio_to_cctv

# Sentinel Configuration
IMAGE_PATH = r"D:\openclaw\temp\cctv_latest.jpg"
SOUND_PATH = r"D:\openclaw\cctv_vision\ding.wav"

# Initialize MediaPipe Hands
mp_hands = mp.solutions.hands
hands = mp_hands.Hands(min_detection_confidence=0.7, min_tracking_confidence=0.7)

def detect_gesture(frame):
    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    results = hands.process(rgb_frame)
    
    if results.multi_hand_landmarks:
        for hand_landmarks in results.multi_hand_landmarks:
            if hand_landmarks.landmark[mp_hands.HandLandmark.WRIST].y > hand_landmarks.landmark[mp_hands.HandLandmark.INDEX_FINGER_TIP].y:
                return True
    return False

def sentinel_loop():
    print("Vision Sentinel Active. Monitoring gesture...")
    last_ping = 0
    while True:
        if os.path.exists(IMAGE_PATH):
            frame = cv2.imread(IMAGE_PATH)
            if frame is not None:
                if detect_gesture(frame):
                    if time.time() - last_ping > 30:
                        print("Gesture Detected: Hand Raised.")
                        # Push audio ping to camera
                        if os.path.exists(SOUND_PATH):
                            push_audio_to_cctv(SOUND_PATH, "192.168.68.114", "L220341D")
                        last_ping = time.time()
        time.sleep(1)

if __name__ == "__main__":
    sentinel_loop()