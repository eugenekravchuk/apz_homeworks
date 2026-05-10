from __future__ import annotations

import asyncio
import os
import pathlib
import sys
from typing import Any

import grpc
from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

sys.path.append(str(pathlib.Path(__file__).resolve().parent))

import logging_pb2
import logging_pb2_grpc

LOGGING_PORT = int(os.getenv("LOGGING_PORT", "4000"))
LOGGING_GRPC_PORT = int(os.getenv("LOGGING_GRPC_PORT", "50051"))

app = FastAPI(title="logging-service")

messages: dict[str, str] = {}


class LogEntry(BaseModel):
    id: str
    message: str


class LoggingServicer(logging_pb2_grpc.LoggingServiceServicer):
    async def AddLog(self, request: logging_pb2.LogRequest, _context: grpc.aio.ServicerContext) -> logging_pb2.LogResponse:
        deduplicated = request.id in messages
        if not deduplicated:
            messages[request.id] = request.message
            print(f"Stored message {request.id}: {request.message}")
        else:
            print(f"Duplicate message {request.id} ignored")
        return logging_pb2.LogResponse(deduplicated=deduplicated)

    async def GetLogs(self, _request: logging_pb2.GetLogsRequest, _context: grpc.aio.ServicerContext) -> logging_pb2.GetLogsResponse:
        return logging_pb2.GetLogsResponse(messages=list(messages.values()))


async def start_grpc_server() -> grpc.aio.Server:
    server = grpc.aio.server()
    logging_pb2_grpc.add_LoggingServiceServicer_to_server(LoggingServicer(), server)
    server.add_insecure_port(f"0.0.0.0:{LOGGING_GRPC_PORT}")
    await server.start()
    return server


@app.on_event("startup")
async def startup() -> None:
    app.state.grpc_server = await start_grpc_server()
    print(f"gRPC server listening on {LOGGING_GRPC_PORT}")


@app.on_event("shutdown")
async def shutdown() -> None:
    grpc_server: grpc.aio.Server | None = getattr(app.state, "grpc_server", None)
    if grpc_server:
        await grpc_server.stop(0)


@app.post("/logs")
async def add_log(entry: LogEntry) -> dict[str, Any]:
    if not entry.id or not entry.message:
        raise HTTPException(status_code=400, detail="id and message are required")

    deduplicated = entry.id in messages

    if not deduplicated:
        messages[entry.id] = entry.message
        print(f"Stored message {entry.id}: {entry.message}")
    else:
        print(f"Duplicate message {entry.id} ignored")

    return {"status": "ok", "deduplicated": deduplicated}


@app.get("/logs", response_class=PlainTextResponse)
async def get_logs() -> PlainTextResponse:
    all_messages = "\n".join(messages.values())
    return PlainTextResponse(content=all_messages)


if __name__ == "__main__":
    import uvicorn

    loop = asyncio.get_event_loop()
    loop.create_task(start_grpc_server())
    uvicorn.run(app, host="0.0.0.0", port=LOGGING_PORT)
