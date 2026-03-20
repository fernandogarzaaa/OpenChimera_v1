# OpenViking Integration for CHIMERA

This document explains how to set up and run the OpenViking context database locally for the CHIMERA architecture.

OpenViking can be run in two modes: **Native (Python Library)** or **Docker (Server)**. The Python bridge at `utils/viking_bridge.py` supports both.

## Prerequisites
- Install the `openviking` python package (if running natively or for the client).
  ```bash
  pip install openviking
  ```

## Mode 1: Docker (Standalone Server)
Running OpenViking as a standalone server is recommended for a multi-agent CHIMERA setup so multiple Python servers can connect to the same context DB.

### 1. Start the Docker Container
Create a `docker-compose.yml` or run directly using the official image:
```bash
docker run -d --name openviking -p 1933:1933 \
  -v ./viking_data:/var/lib/openviking/data \
  -v ./ov.conf:/app/ov.conf \
  --restart unless-stopped \
  ghcr.io/volcengine/openviking:main
```
Wait for the server to be healthy (`http://127.0.0.1:1933/health`).

### 2. Configure the Python Bridge
To connect the CHIMERA python bridge to the server, use:
```python
from utils.viking_bridge import VikingBridge

# Pass use_server=True to connect via HTTP to localhost:1933
bridge = VikingBridge(use_server=True)
bridge.add_context("https://github.com/your-repo")
results = bridge.search_context("chimera architecture")
```

## Mode 2: Native (Embedded Library)
If you prefer not to use Docker, OpenViking can run directly within the Python process. It will store its data in a local directory (e.g., `./viking_data`).

### 1. Initialize the Bridge
```python
from utils.viking_bridge import VikingBridge

# Pass use_server=False (default) to run natively
bridge = VikingBridge(use_server=False)
```

## Features Supported by the Bridge
- `add_context(path_or_url)`: Index files, directories, or web URLs into the database.
- `search_context(query)`: Semantic search over the indexed codebase/context.
- `read_context(uri)`: Fetch exact content using a URI.
- `get_abstract(uri)`: Generate an abstract overview of the resource.
