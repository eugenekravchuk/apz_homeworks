from __future__ import annotations

import asyncio
import os
import random
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
LOGGING_GRPC_ADDRS = [
    addr.strip()
    for addr in os.getenv("LOGGING_GRPC_ADDRS", "localhost:50051").split(",")
    if addr.strip()
]
COUNTER_SERVICE_URL = os.getenv("COUNTER_SERVICE_URL", "http://localhost:5000")

app = FastAPI(title="facade-service")

http_client: httpx.AsyncClient | None = None
grpc_channels: list[grpc.aio.Channel] = []
grpc_stubs: list[logging_pb2_grpc.LoggingServiceStub] = []


class MessageIn(BaseModel):
    msg: str


def _pick_stub_order() -> list[logging_pb2_grpc.LoggingServiceStub]:
    stubs = list(grpc_stubs)
    random.shuffle(stubs)
    return stubs


async def call_logging_with_fallback(
    op: Callable[[logging_pb2_grpc.LoggingServiceStub], Awaitable[Any]],
) -> Any:
    stubs = _pick_stub_order()
    last_exc: Exception | None = None
    for stub in stubs:
        try:
            return await op(stub)
        except Exception as exc:  # noqa: BLE001
            print(f"logging-service instance unavailable: {exc}; trying next")
            last_exc = exc
    raise last_exc or RuntimeError("no logging-service instances available")


@app.on_event("startup")
async def startup() -> None:
    global http_client, grpc_channels, grpc_stubs
    http_client = httpx.AsyncClient()
    grpc_channels = [grpc.aio.insecure_channel(addr) for addr in LOGGING_GRPC_ADDRS]
    grpc_stubs = [logging_pb2_grpc.LoggingServiceStub(ch) for ch in grpc_channels]
    print(f"Configured logging-service instances: {LOGGING_GRPC_ADDRS}")


@app.on_event("shutdown")
async def shutdown() -> None:
    global http_client, grpc_channels, grpc_stubs
    if http_client:
        await http_client.aclose()
        http_client = None
    for ch in grpc_channels:
        await ch.close()
    grpc_channels = []
    grpc_stubs = []


@app.post("/api/messages")
async def post_message(payload: MessageIn) -> dict[str, Any]:
    if not payload.msg:
        raise HTTPException(status_code=400, detail="msg is required")

    if not grpc_stubs:
        raise HTTPException(status_code=500, detail="gRPC clients not initialized")

    message_id = str(uuid.uuid4())

    try:
        await call_logging_with_fallback(
            lambda stub: stub.AddLog(
                logging_pb2.LogRequest(id=message_id, message=payload.msg), timeout=2.0
            )
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"all logging-service instances failed: {exc}") from exc

    return {"id": message_id, "message": payload.msg, "status": "forwarded to logging-service (gRPC)"}


@app.get("/api/messages", response_class=PlainTextResponse)
async def get_messages() -> PlainTextResponse:
    if not grpc_stubs or http_client is None:
        raise HTTPException(status_code=500, detail="clients not initialized")

    try:
        logs_resp = await call_logging_with_fallback(
            lambda stub: stub.GetLogs(logging_pb2.GetLogsRequest(), timeout=2.0)
        )
        counter_resp = await http_client.get(f"{COUNTER_SERVICE_URL}/message", timeout=2.0)
        counter_resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"failed to gather responses: {exc}") from exc

    combined_logs = "\n".join(logs_resp.messages)
    combined = f"{combined_logs}\n{counter_resp.text}" if combined_logs else counter_resp.text
    return PlainTextResponse(content=combined)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=FACADE_PORT)
