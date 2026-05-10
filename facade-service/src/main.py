from __future__ import annotations

import asyncio
import os
import uuid
import pathlib
import sys
from typing import Any, Awaitable, Callable

import grpc
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

sys.path.append(str(pathlib.Path(__file__).resolve().parent))

import logging_pb2
import logging_pb2_grpc

FACADE_PORT = int(os.getenv("FACADE_PORT", "3000"))
LOGGING_GRPC_ADDR = os.getenv("LOGGING_GRPC_ADDR", "localhost:50051")
MESSAGES_SERVICE_URL = os.getenv("MESSAGES_SERVICE_URL", "http://localhost:5000")

app = FastAPI(title="facade-service")

http_client: httpx.AsyncClient | None = None
grpc_channel: grpc.aio.Channel | None = None
grpc_stub: logging_pb2_grpc.LoggingServiceStub | None = None


class MessageIn(BaseModel):
    msg: str


async def send_with_retry(
    fn: Callable[[], Awaitable[Any]], retries: int = 3, delay_ms: int = 10000, attempt: int = 1
) -> Any:
    try:
        return await fn()
    except (grpc.aio.AioRpcError, httpx.HTTPError) as exc:
        if retries <= 0:
            print(f"Retry attempt {attempt} failed, no retries left: {exc}")
            raise exc
        print(f"Retry attempt {attempt} failed: {exc}. Retries left: {retries}; waiting {delay_ms} ms")
        await asyncio.sleep(delay_ms / 1000)
        return await send_with_retry(fn, retries - 1, delay_ms * 2, attempt + 1)


@app.on_event("startup")
async def startup() -> None:
    global http_client, grpc_channel, grpc_stub
    http_client = httpx.AsyncClient()
    grpc_channel = grpc.aio.insecure_channel(LOGGING_GRPC_ADDR)
    grpc_stub = logging_pb2_grpc.LoggingServiceStub(grpc_channel)


@app.on_event("shutdown")
async def shutdown() -> None:
    global http_client, grpc_channel, grpc_stub
    if http_client:
        await http_client.aclose()
        http_client = None
    if grpc_channel:
        await grpc_channel.close()
        grpc_channel = None
        grpc_stub = None


@app.post("/api/messages")
async def post_message(payload: MessageIn) -> dict[str, Any]:
    if not payload.msg:
        raise HTTPException(status_code=400, detail="msg is required")

    message_id = str(uuid.uuid4())

    if grpc_stub is None:
        raise HTTPException(status_code=500, detail="gRPC client not initialized")

    async def send_to_logging() -> Any:
        return await grpc_stub.AddLog(logging_pb2.LogRequest(id=message_id, message=payload.msg), timeout=2.0)

    try:
        await send_with_retry(send_to_logging)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"failed to reach logging-service via gRPC: {exc}") from exc

    return {"id": message_id, "message": payload.msg, "status": "forwarded to logging-service (gRPC)"}


@app.get("/api/messages", response_class=PlainTextResponse)
async def get_messages() -> PlainTextResponse:
    if grpc_stub is None or http_client is None:
        raise HTTPException(status_code=500, detail="clients not initialized")

    try:
        logs_resp = await grpc_stub.GetLogs(logging_pb2.GetLogsRequest(), timeout=2.0)
        msg_resp = await http_client.get(f"{MESSAGES_SERVICE_URL}/message", timeout=2.0)
        msg_resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"failed to gather responses: {exc}") from exc

    combined_logs = "\n".join(logs_resp.messages)
    combined = f"{combined_logs}\n{msg_resp.text}" if combined_logs else msg_resp.text
    return PlainTextResponse(content=combined)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=FACADE_PORT)
