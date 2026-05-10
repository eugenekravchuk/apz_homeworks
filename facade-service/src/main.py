from __future__ import annotations

import asyncio
import os
import random
import uuid
import pathlib
import socket
import sys
import time
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
CONSUL_URL = os.getenv("CONSUL_URL", "http://localhost:8500")
SERVICE_HOST = os.getenv("SERVICE_HOST", socket.gethostname())
SERVICE_ID = os.getenv("SERVICE_ID", f"facade-service-{SERVICE_HOST}-{FACADE_PORT}")
HAZELCAST_ADDR = "localhost:5701"
COUNTER_QUEUE_NAME = "counter-transactions"

app = FastAPI(title="facade-service")

http_client: httpx.AsyncClient | None = None
hz_client: hazelcast.HazelcastClient | None = None
hz_queue: Any = None


class MessageIn(BaseModel):
    msg: str


async def consul_get_kv(key: str) -> str:
    if http_client is None:
        raise RuntimeError("http client is not initialized")
    response = await http_client.get(f"{CONSUL_URL}/v1/kv/{key}?raw", timeout=5.0)
    response.raise_for_status()
    return response.text.strip()


async def load_runtime_config() -> None:
    global HAZELCAST_ADDR, COUNTER_QUEUE_NAME
    HAZELCAST_ADDR = await consul_get_kv("config/hazelcast/cluster_members")
    COUNTER_QUEUE_NAME = await consul_get_kv("config/message_queue/counter_queue_name")
    print(f"Loaded config from Consul: hazelcast={HAZELCAST_ADDR}, queue={COUNTER_QUEUE_NAME}")


async def register_service() -> None:
    if http_client is None:
        raise RuntimeError("http client is not initialized")
    payload = {
        "ID": SERVICE_ID,
        "Name": "facade-service",
        "Address": SERVICE_HOST,
        "Port": FACADE_PORT,
        "Check": {
            "HTTP": f"http://{SERVICE_HOST}:{FACADE_PORT}/health",
            "Interval": "5s",
            "Timeout": "2s",
            "DeregisterCriticalServiceAfter": "30s",
        },
    }
    response = await http_client.put(f"{CONSUL_URL}/v1/agent/service/register", json=payload, timeout=5.0)
    response.raise_for_status()
    print(f"Registered facade-service in Consul as {SERVICE_ID} at {SERVICE_HOST}:{FACADE_PORT}")


async def discover_service(service_name: str) -> list[str]:
    if http_client is None:
        raise RuntimeError("http client is not initialized")
    response = await http_client.get(f"{CONSUL_URL}/v1/health/service/{service_name}?passing=true", timeout=2.0)
    response.raise_for_status()
    instances = []
    for item in response.json():
        service = item.get("Service", {})
        address = service.get("Address")
        port = service.get("Port")
        if address and port:
            instances.append(f"{address}:{port}")
    return instances


async def call_logging_with_fallback(
    op: Callable[[logging_pb2_grpc.LoggingServiceStub], Awaitable[Any]],
) -> Any:
    addresses = await discover_service("logging-service")
    if not addresses:
        raise RuntimeError("no healthy logging-service instances found in Consul")
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
        raise RuntimeError("no healthy counter-service instances found in Consul")
    return f"http://{random.choice(addresses)}"


@app.on_event("startup")
async def startup() -> None:
    global http_client, hz_client, hz_queue
    http_client = httpx.AsyncClient()
    for attempt in range(1, 11):
        try:
            await load_runtime_config()
            await register_service()
            break
        except Exception as exc:
            if attempt == 10:
                raise
            print(f"facade-service waiting for Consul config ({attempt}/10): {exc}")
            await asyncio.sleep(2)
    loop = asyncio.get_event_loop()
    def init_hazelcast() -> tuple[hazelcast.HazelcastClient, Any]:
        client = hazelcast.HazelcastClient(
            cluster_members=[addr.strip() for addr in HAZELCAST_ADDR.split(",") if addr.strip()],
            cluster_name="dev",
            connection_timeout=10.0,
        )
        return client, client.get_queue(COUNTER_QUEUE_NAME).blocking()

    hz_client, hz_queue = await loop.run_in_executor(None, init_hazelcast)


@app.on_event("shutdown")
async def shutdown() -> None:
    global http_client, hz_client, hz_queue
    if http_client:
        try:
            await http_client.put(f"{CONSUL_URL}/v1/agent/service/deregister/{SERVICE_ID}", timeout=2.0)
        except Exception as exc:
            print(f"failed to deregister facade-service from Consul: {exc}")
        await http_client.aclose()
        http_client = None
    if hz_client:
        hz_client.shutdown()
        hz_client = None
        hz_queue = None


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/messages")
async def post_message(payload: MessageIn) -> dict[str, Any]:
    if not payload.msg:
        raise HTTPException(status_code=400, detail="msg is required")

    if http_client is None or hz_queue is None:
        raise HTTPException(status_code=500, detail="clients not initialized")

    message_id = str(uuid.uuid4())
    total_started = time.perf_counter()
    logging_ms = 0.0
    counter_queue_ms = 0.0

    try:
        logging_started = time.perf_counter()
        await call_logging_with_fallback(
            lambda stub: stub.AddLog(
                logging_pb2.LogRequest(id=message_id, message=payload.msg), timeout=2.0
            )
        )
        logging_ms = (time.perf_counter() - logging_started) * 1000
        loop = asyncio.get_event_loop()
        counter_queue_started = time.perf_counter()
        await loop.run_in_executor(None, hz_queue.put, {"value": payload.msg})
        counter_queue_ms = (time.perf_counter() - counter_queue_started) * 1000
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"message forwarding failed: {exc}") from exc

    total_ms = (time.perf_counter() - total_started) * 1000
    print(
        f"PERF POST message_id={message_id} total_ms={total_ms:.2f} "
        f"logging_ms={logging_ms:.2f} counter_queue_ms={counter_queue_ms:.2f}",
        flush=True,
    )
    return {"id": message_id, "message": payload.msg, "status": "forwarded to logging-service and queued for counter-service"}


@app.get("/api/messages", response_class=PlainTextResponse)
async def get_messages() -> PlainTextResponse:
    if http_client is None:
        raise HTTPException(status_code=500, detail="clients not initialized")

    total_started = time.perf_counter()
    logging_started = time.perf_counter()
    logs_resp = await call_logging_with_fallback(
        lambda stub: stub.GetLogs(logging_pb2.GetLogsRequest(), timeout=2.0)
    )
    logging_ms = (time.perf_counter() - logging_started) * 1000

    try:
        counter_started = time.perf_counter()
        counter_service_url = await pick_counter_service_url()
        counter_resp = await http_client.get(f"{counter_service_url}/counter", timeout=2.0)
        counter_resp.raise_for_status()
        counter_ms = (time.perf_counter() - counter_started) * 1000
    except Exception as exc:  # noqa: BLE001
        print(f"counter-service unavailable while reading counters: {exc}")
        logs_only = "\n".join(list(logs_resp.messages))
        total_ms = (time.perf_counter() - total_started) * 1000
        print(
            f"PERF GET total_ms={total_ms:.2f} logging_ms={logging_ms:.2f} counter_ms=unavailable",
            flush=True,
        )
        return PlainTextResponse(content=f"{logs_only}\nnull" if logs_only else "null")

    counter_data = counter_resp.json()
    counter_messages = [item["value"] for item in counter_data.get("messages", [])]
    combined = "\n".join(list(logs_resp.messages) + counter_messages)
    total_ms = (time.perf_counter() - total_started) * 1000
    print(
        f"PERF GET total_ms={total_ms:.2f} logging_ms={logging_ms:.2f} counter_ms={counter_ms:.2f}",
        flush=True,
    )
    return PlainTextResponse(content=combined)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=FACADE_PORT)
