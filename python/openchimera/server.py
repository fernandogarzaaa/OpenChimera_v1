"""Uvicorn server bootstrap."""

import uvicorn


def start_server(host: str, port: int, reload: bool = False) -> None:
    uvicorn.run(
        "openchimera.api.routes:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
        access_log=True,
    )
