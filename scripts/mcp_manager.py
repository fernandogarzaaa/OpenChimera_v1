import asyncio
import json
import logging
import sys
from typing import Dict, Any, Optional

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("mcp_manager")

class MCPServerProcess:
    def __init__(self, name: str, command: list[str]):
        self.name = name
        self.command = command
        self.process: Optional[asyncio.subprocess.Process] = None
        self._request_id = 0
        self.pending_requests: Dict[int, asyncio.Future] = {}
        self._reader_task: Optional[asyncio.Task] = None

    async def start(self):
        logger.info(f"Starting MCP server '{self.name}': {' '.join(self.command)}")
        self.process = await asyncio.create_subprocess_exec(
            *self.command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        self._reader_task = asyncio.create_task(self._read_stdout())
        asyncio.create_task(self._read_stderr())
        
        # Send initialize request
        init_res = await self.request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "openclaw-mcp-manager", "version": "1.0.0"}
        })
        await self.notify("notifications/initialized", {})
        logger.info(f"Server '{self.name}' initialized: {init_res}")

    async def stop(self):
        if self.process and self.process.returncode is None:
            logger.info(f"Stopping MCP server '{self.name}'")
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self.process.kill()
            if self._reader_task:
                self._reader_task.cancel()

    async def _read_stdout(self):
        while self.process and self.process.stdout and not self.process.stdout.at_eof():
            try:
                line = await self.process.stdout.readline()
                if not line:
                    break
                
                try:
                    data = json.loads(line.decode('utf-8').strip())
                    if "id" in data and data["id"] in self.pending_requests:
                        future = self.pending_requests.pop(data["id"])
                        if not future.done():
                            if "error" in data:
                                future.set_exception(Exception(data["error"]))
                            else:
                                future.set_result(data.get("result"))
                    elif "method" in data:
                        logger.debug(f"Received notification/request from {self.name}: {data}")
                except json.JSONDecodeError:
                    logger.warning(f"Invalid JSON from {self.name} stdout: {line}")
            except Exception as e:
                logger.error(f"Error reading stdout from {self.name}: {e}")
                break

    async def _read_stderr(self):
        while self.process and self.process.stderr and not self.process.stderr.at_eof():
            line = await self.process.stderr.readline()
            if line:
                logger.info(f"[{self.name} STDERR] {line.decode('utf-8').strip()}")

    async def request(self, method: str, params: Optional[Dict[str, Any]] = None) -> Any:
        if not self.process or self.process.returncode is not None:
            raise RuntimeError(f"Server '{self.name}' is not running")

        self._request_id += 1
        req_id = self._request_id
        
        message = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method
        }
        if params is not None:
            message["params"] = params

        future = asyncio.get_running_loop().create_future()
        self.pending_requests[req_id] = future
        
        msg_bytes = json.dumps(message).encode('utf-8') + b'\n'
        self.process.stdin.write(msg_bytes)
        await self.process.stdin.drain()
        
        return await future

    async def notify(self, method: str, params: Optional[Dict[str, Any]] = None):
        if not self.process or self.process.returncode is not None:
            return
            
        message = {
            "jsonrpc": "2.0",
            "method": method
        }
        if params is not None:
            message["params"] = params
            
        msg_bytes = json.dumps(message).encode('utf-8') + b'\n'
        self.process.stdin.write(msg_bytes)
        await self.process.stdin.drain()

class MCPManager:
    def __init__(self):
        self.servers: Dict[str, MCPServerProcess] = {}

    def register_server(self, name: str, command: list[str]):
        """Register a new local MCP server."""
        if name in self.servers:
            logger.warning(f"Server '{name}' is already registered. Replacing.")
        self.servers[name] = MCPServerProcess(name, command)
        logger.info(f"Registered server: {name} -> {command}")

    async def start_server(self, name: str):
        if name not in self.servers:
            raise ValueError(f"Unknown server: {name}")
        await self.servers[name].start()

    async def stop_server(self, name: str):
        if name in self.servers:
            await self.servers[name].stop()

    async def stop_all(self):
        for server in self.servers.values():
            await server.stop()

    async def list_tools(self, server_name: str) -> Dict[str, Any]:
        if server_name not in self.servers:
            raise ValueError(f"Unknown server: {server_name}")
        return await self.servers[server_name].request("tools/list")

    async def call_tool(self, server_name: str, tool_name: str, arguments: Dict[str, Any]) -> Any:
        if server_name not in self.servers:
            raise ValueError(f"Unknown server: {server_name}")
        return await self.servers[server_name].request("tools/call", {
            "name": tool_name,
            "arguments": arguments
        })

    async def list_prompts(self, server_name: str) -> Dict[str, Any]:
        if server_name not in self.servers:
            raise ValueError(f"Unknown server: {server_name}")
        return await self.servers[server_name].request("prompts/list")

    async def get_prompt(self, server_name: str, prompt_name: str, arguments: Dict[str, str]) -> Any:
        if server_name not in self.servers:
            raise ValueError(f"Unknown server: {server_name}")
        return await self.servers[server_name].request("prompts/get", {
            "name": prompt_name,
            "arguments": arguments
        })

# Example usage / CLI entrypoint
async def main():
    manager = MCPManager()
    
    # Example: register a local node-based MCP server
    # manager.register_server("sqlite", ["node", "path/to/sqlite/build/index.js"])
    
    import argparse
    parser = argparse.ArgumentParser(description="OpenClaw MCP Manager")
    parser.add_argument("--register", nargs='+', help="Register a server: <name> <cmd> [args...]", action='append')
    args = parser.parse_args()
    
    if args.register:
        for reg in args.register:
            name = reg[0]
            cmd = reg[1:]
            manager.register_server(name, cmd)
            try:
                await manager.start_server(name)
                tools = await manager.list_tools(name)
                logger.info(f"Tools for {name}: {json.dumps(tools, indent=2)}")
            except Exception as e:
                logger.error(f"Failed to start/query {name}: {e}")
                
        # Keep alive
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            await manager.stop_all()
    else:
        logger.info("No servers registered. Use --register to add servers.")
        print("MCP Manager ready. Import MCPManager to use programmatically.")

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(main())
