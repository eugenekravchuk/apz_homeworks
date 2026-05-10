from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse

MESSAGES_PORT = int(os.getenv("MESSAGES_PORT", "5000"))
STATIC_MESSAGE = os.getenv("STATIC_MESSAGE", "not implemented yet")

app = FastAPI(title="messages-service")


@app.get("/message", response_class=PlainTextResponse)
async def get_message() -> PlainTextResponse:
    return PlainTextResponse(content=STATIC_MESSAGE)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=MESSAGES_PORT)
