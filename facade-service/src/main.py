from __future__ import annotations

import asyncio
import os
import random
import uuid
import pathlib
import sys
from typing import Any, Awaitable, Callable

import grpc
import hazelcast
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
CONFIG_SERVER_URL = os.getenv("CONFIG_SERVER_URL", "http://localhost:7000")
HAZELCAST_ADDR = os.getenv("HAZELCAST_ADDR", "localhost:5701")
COUNTER_QUEUE_NAME = os.getenv("COUNTER_QUEUE_NAME", "counter-transactions")

app = FastAPI(title="facade-service")

http_client: httpx.AsyncClient | None = None
hz_client: hazelcast.HazelcastClient | None = None
hz_queue: Any = None


class MessageIn(BaseModel):
    msg: str


async def discover_service(service_name: str) -> list[str]:
    if http_client is None:
        raise RuntimeError("http client is not initialized")
    response = await http_client.get(f"{CONFIG_SERVER_URL}/services/{service_name}", timeout=2.0)
    response.raise_for_status()
    data = response.json()
    return [addr for addr in data.get("instances", []) if addr]


async def call_logging_with_fallback(
    op: Callable[[logging_pb2_grpc.LoggingServiceStub], Awaitable[Any]],
) -> Any:
    addresses = await discover_service("logging-service")
    if not addresses:
        addresses = LOGGING_GRPC_ADDRS
    random.shuffle(addresses)
    last_exc: Exception | None = None
    for address in addresses:
        channel = grpc.aio.insecure_channel(address)
        stub = logging_pb2_grpc.LoggingServiceStub(channel)
        try:
            return await op(stub)
        except Exception as exc:  # noqa: BLE001
            print(f"logging-service instance {address} unavailable: {exc}; trying next")
            last_exc = exc
        finally:
            await channel.close()
    raise last_exc or RuntimeError("no logging-service instances available")


async def pick_counter_service_url() -> str:
    addresses = await discover_service("counter-service")
    if not addresses:
        return COUNTER_SERVICE_URL
    return random.choice(addresses)


@app.on_event("startup")
async def startup() -> None:
    global http_client, hz_client, hz_queue
    http_client = httpx.AsyncClient()
    loop = asyncio.get_event_loop()
    def init_hazelcast() -> tuple[hazelcast.HazelcastClient, Any]:
        client = hazelcast.HazelcastClient(
            cluster_members=[HAZELCAST_ADDR],
            cluster_name="dev",
            connection_timeout=10.0,
        )
        return client, client.get_queue(COUNTER_QUEUE_NAME).blocking()

    hz_client, hz_queue = await loop.run_in_executor(None, init_hazelcast)
    print(f"Configured fallback logging-service instances: {LOGGING_GRPC_ADDRS}")


@app.on_event("shutdown")
async def shutdown() -> None:
    global http_client, hz_client, hz_queue
    if http_client:
        await http_client.aclose()
        http_client = None
    if hz_client:
        hz_client.shutdown()
        hz_client = None
        hz_queue = None


@app.post("/api/messages")
async def post_message(payload: MessageIn) -> dict[str, Any]:
    if not payload.msg:
        raise HTTPException(status_code=400, detail="msg is required")

    if http_client is None or hz_queue is None:
        raise HTTPException(status_code=500, detail="clients not initialized")

    message_id = str(uuid.uuid4())

    try:
        await call_logging_with_fallback(
            lambda stub: stub.AddLog(
                logging_pb2.LogRequest(id=message_id, message=payload.msg), timeout=2.0
            )
        )
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, hz_queue.put, {"value": payload.msg})
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"message forwarding failed: {exc}") from exc

    return {"id": message_id, "message": payload.msg, "status": "forwarded to logging-service and queued for counter-service"}


@app.get("/api/messages", response_class=PlainTextResponse)
async def get_messages() -> PlainTextResponse:
    if http_client is None:
        raise HTTPException(status_code=500, detail="clients not initialized")

    logs_resp = await call_logging_with_fallback(
        lambda stub: stub.GetLogs(logging_pb2.GetLogsRequest(), timeout=2.0)
    )

    try:
        counter_service_url = await pick_counter_service_url()
        counter_resp = await http_client.get(f"{counter_service_url}/counter", timeout=2.0)
        counter_resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        print(f"counter-service unavailable while reading counters: {exc}")
        logs_only = "\n".join(list(logs_resp.messages))
        return PlainTextResponse(content=f"{logs_only}\nnull" if logs_only else "null")

    counter_data = counter_resp.json()
    counter_messages = [item["value"] for item in counter_data.get("messages", [])]
    combined = "\n".join(list(logs_resp.messages) + counter_messages)
    return PlainTextResponse(content=combined)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=FACADE_PORT)
