import os
import openviking as ov

# Configuration
VIKING_URL = os.getenv("VIKING_URL", "http://localhost:1933")
VIKING_DATA_DIR = os.getenv("VIKING_DATA_DIR", "./viking_data")

class VikingBridge:
    def __init__(self, use_server=False):
        """
        Initialize the bridge to OpenViking.
        If use_server is True, connects to the OpenViking Server via HTTP.
        Otherwise, runs natively using the local data directory.
        """
        self.use_server = use_server
        if self.use_server:
            self.client = ov.SyncHTTPClient(url=VIKING_URL)
        else:
            os.makedirs(VIKING_DATA_DIR, exist_ok=True)
            self.client = ov.OpenViking(path=VIKING_DATA_DIR)
            self.client.initialize()

    def add_context(self, path_or_url: str):
        """Add a file, directory, or URL to the OpenViking context database."""
        res = self.client.add_resource(path=path_or_url)
        return res.get("root_uri")

    def read_context(self, uri: str):
        """Read the content of a specific resource URI."""
        return self.client.read(uri)

    def search_context(self, query: str, target_uri: str = None):
        """Perform semantic search for context matching the query."""
        results = self.client.find(query, target_uri=target_uri)
        return [{"uri": r.uri, "score": r.score} for r in getattr(results, "resources", [])]

    def get_abstract(self, uri: str):
        """Get an abstract of the resource."""
        return self.client.abstract(uri)

    def wait_for_processing(self):
        """Wait for OpenViking to finish semantic processing."""
        self.client.wait_processed()

    def close(self):
        """Close the OpenViking client."""
        self.client.close()

if __name__ == "__main__":
    # Quick test
    bridge = VikingBridge(use_server=False)
    print("VikingBridge initialized locally.")
    bridge.close()
