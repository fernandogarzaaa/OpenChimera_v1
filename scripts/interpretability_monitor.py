import asyncio
import json
import sys
import aiohttp
from typing import Dict, Any

# Simple MCP Server for Interpretability Monitor
# Exposes feature activations via MCP resources

class InterpretabilityMonitorServer:
    def __init__(self):
        self.activations = []
        self.running = True

    async def handle_request(self, request: Dict[str, Any]):
        method = request.get("method")
        msg_id = request.get("id")

        if method == "initialize":
            await self.send_response(msg_id, {
                "protocolVersion": "2024-11-05",
                "capabilities": {"resources": {}}
            })
        elif method == "notifications/initialized":
            pass # Acknowledge
        elif method == "resources/list":
            await self.send_response(msg_id, {
                "resources": [{
                    "uri": "interpretability://activations",
                    "name": "Feature Activations",
                    "mimeType": "application/json"
                }]
            })
        elif method == "resources/read":
            params = request.get("params", {})
            uri = params.get("uri")
            if uri == "interpretability://activations":
                await self.send_response(msg_id, {
                    "contents": [{
                        "uri": uri,
                        "mimeType": "application/json",
                        "text": json.dumps(self.activations)
                    }]
                })
        elif method == "shutdown":
            self.running = False

    async def send_response(self, msg_id: Any, result: Any):
        response = {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": result
        }
        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()

    async def fetch_activations(self):
        async with aiohttp.ClientSession() as session:
            while self.running:
                try:
                    # Polling CHIMERA endpoint at 7870
                    async with session.get("http://localhost:7870/activations", timeout=2) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            self.activations = data
                except Exception as e:
                    # Fail silently or log to stderr
                    pass
                await asyncio.sleep(0.5)

    async def run(self):
        # Start fetcher task
        asyncio.create_task(self.fetch_activations())
        
        # Read from stdin
        loop = asyncio.get_event_loop()
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)
        
        while self.running:
            line = await reader.readline()
            if not line:
                break
            try:
                request = json.loads(line.decode('utf-8'))
                await self.handle_request(request)
            except Exception:
                continue

if __name__ == "__main__":
    server = InterpretabilityMonitorServer()
    asyncio.run(server.run())
