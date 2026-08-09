"""Uvicorn server bootstrap."""

import uvicorn

from openchimera.api.routes import app


def start_server(host: str, port: int, reload: bool = False) -> None:
    uvicorn.run(
        "openchimera.api.routes:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )
