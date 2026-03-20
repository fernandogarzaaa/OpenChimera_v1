import subprocess
import os

# FFmpeg Command for ONVIF/RTSP Backchannel
# This assumes your camera supports backchannel on port 554
# Note: You may need to install ffmpeg on your path.
def push_audio_to_cctv(audio_path, ip_address, password):
    print(f"Pushing {audio_path} to camera {ip_address}...")
    # This is a simplified command; actual RTSP backchannel requires precise SDP negotiation
    cmd = [
        "ffmpeg", "-i", audio_path,
        "-f", "rtsp", 
        f"rtsp://admin:{password}@{ip_address}:554/backchannel"
    ]
    try:
        subprocess.run(cmd, check=True)
        print("Audio pushed successfully.")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    # Test this with an actual wave file once your keys are ready
    pass