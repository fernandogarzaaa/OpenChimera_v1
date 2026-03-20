import hashlib
import time
import os
from core.bus import EventBus

class FIMDaemon:
    def __init__(self, bus: EventBus, files_to_watch: list):
        self.bus = bus
        self.files_to_watch = files_to_watch
        self.hashes = {f: self._hash_file(f) for f in files_to_watch if os.path.exists(f)}

    def _hash_file(self, filepath):
        if not os.path.exists(filepath): return None
        try:
            with open(filepath, 'rb') as f:
                return hashlib.sha256(f.read()).hexdigest()
        except:
            return None

    def run(self):
        while True:
            for f in self.files_to_watch:
                current_hash = self._hash_file(f)
                if current_hash != self.hashes.get(f):
                    self.bus.publish("security_alert", {"file": f, "status": "unauthorized_change"})
                    self.hashes[f] = current_hash
            time.sleep(30)
