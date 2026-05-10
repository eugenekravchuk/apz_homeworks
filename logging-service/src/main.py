from __future__ import annotations

import asyncio
import os
import pathlib
import sys
from typing import Any

import grpc
import hazelcast
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

sys.path.append(str(pathlib.Path(__file__).resolve().parent))

import logging_pb2
import logging_pb2_grpc

LOGGING_PORT = int(os.getenv("LOGGING_PORT", "4000"))
LOGGING_GRPC_PORT = int(os.getenv("LOGGING_GRPC_PORT", "50051"))
HAZELCAST_ADDR = os.getenv("HAZELCAST_ADDR", "localhost:5701")
SERVICE_INSTANCE = os.getenv("SERVICE_INSTANCE", "logging-1")
CONFIG_SERVER_URL = os.getenv("CONFIG_SERVER_URL", "http://localhost:7000")
SERVICE_GRPC_ADDRESS = os.getenv("SERVICE_GRPC_ADDRESS", f"localhost:{LOGGING_GRPC_PORT}")

app = FastAPI(title="logging-service")

hz_client: hazelcast.HazelcastClient | None = None
hz_map: Any = None


async def register_service() -> None:
    async with httpx.AsyncClient() as client:
        for attempt in range(1, 11):
            try:
                response = await client.post(
                    f"{CONFIG_SERVER_URL}/register",
                    json={"name": "logging-service", "address": SERVICE_GRPC_ADDRESS},
                    timeout=2.0,
                )
                response.raise_for_status()
                print(f"[{SERVICE_INSTANCE}] registered at config-server as {SERVICE_GRPC_ADDRESS}")
                return
            except Exception as exc:
                print(f"[{SERVICE_INSTANCE}] registration retry {attempt}/10: {exc}")
                await asyncio.sleep(2)


class LogEntry(BaseModel):
    id: str
    message: str


class LoggingServicer(logging_pb2_grpc.LoggingServiceServicer):
    async def AddLog(self, request: logging_pb2.LogRequest, _context: grpc.aio.ServicerContext) -> logging_pb2.LogResponse:
        loop = asyncio.get_event_loop()
        existing = await loop.run_in_executor(None, hz_map.get, request.id)
        deduplicated = existing is not None
        if not deduplicated:
            await loop.run_in_executor(None, hz_map.put, request.id, request.message)
            print(f"[{SERVICE_INSTANCE}] Stored message {request.id}: {request.message}")
        else:
            print(f"[{SERVICE_INSTANCE}] Duplicate message {request.id} ignored")
        return logging_pb2.LogResponse(deduplicated=deduplicated)

    async def GetLogs(self, _request: logging_pb2.GetLogsRequest, _context: grpc.aio.ServicerContext) -> logging_pb2.GetLogsResponse:
        loop = asyncio.get_event_loop()
        all_values = await loop.run_in_executor(None, lambda: list(hz_map.values()))
        print(f"[{SERVICE_INSTANCE}] GetLogs returning {len(all_values)} messages")
        return logging_pb2.GetLogsResponse(messages=all_values)


async def start_grpc_server() -> grpc.aio.Server:
    server = grpc.aio.server()
    logging_pb2_grpc.add_LoggingServiceServicer_to_server(LoggingServicer(), server)
    server.add_insecure_port(f"0.0.0.0:{LOGGING_GRPC_PORT}")
    await server.start()
    return server


@app.on_event("startup")
async def startup() -> None:
    global hz_client, hz_map
    print(f"[{SERVICE_INSTANCE}] Connecting to Hazelcast at {HAZELCAST_ADDR}...")
    try:
        loop = asyncio.get_event_loop()
        def _init_hz():
            client = hazelcast.HazelcastClient(
                cluster_members=[HAZELCAST_ADDR],
                cluster_name="dev",
                connection_timeout=10.0,
            )
            return client, client.get_map("messages").blocking()
        hz_client, hz_map = await loop.run_in_executor(None, _init_hz)
        print(f"[{SERVICE_INSTANCE}] Connected to Hazelcast at {HAZELCAST_ADDR}")
    except Exception as exc:
        print(f"[{SERVICE_INSTANCE}] ERROR connecting to Hazelcast: {exc}")
        raise
    app.state.grpc_server = await start_grpc_server()
    print(f"[{SERVICE_INSTANCE}] gRPC server listening on {LOGGING_GRPC_PORT}")
    await register_service()


@app.on_event("shutdown")
async def shutdown() -> None:
    grpc_server: grpc.aio.Server | None = getattr(app.state, "grpc_server", None)
    if grpc_server:
        await grpc_server.stop(0)
    if hz_client:
        hz_client.shutdown()


@app.post("/logs")
async def add_log(entry: LogEntry) -> dict[str, Any]:
    if not entry.id or not entry.message:
        raise HTTPException(status_code=400, detail="id and message are required")

    loop = asyncio.get_event_loop()
    existing = await loop.run_in_executor(None, hz_map.get, entry.id)
    deduplicated = existing is not None

    if not deduplicated:
        await loop.run_in_executor(None, hz_map.put, entry.id, entry.message)
        print(f"[{SERVICE_INSTANCE}] Stored message {entry.id}: {entry.message}")
    else:
        print(f"[{SERVICE_INSTANCE}] Duplicate message {entry.id} ignored")

    return {"status": "ok", "deduplicated": deduplicated}


@app.get("/logs", response_class=PlainTextResponse)
async def get_logs() -> PlainTextResponse:
    loop = asyncio.get_event_loop()
    all_values = await loop.run_in_executor(None, lambda: list(hz_map.values()))
    return PlainTextResponse(content="\n".join(all_values))


if __name__ == "__main__":
    import uvicorn

    loop = asyncio.get_event_loop()
    loop.create_task(start_grpc_server())
    uvicorn.run(app, host="0.0.0.0", port=LOGGING_PORT)
