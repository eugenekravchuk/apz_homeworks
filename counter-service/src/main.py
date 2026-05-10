from __future__ import annotations

import os
import asyncio
from contextlib import asynccontextmanager
from typing import Any

import asyncpg
import hazelcast
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse

COUNTER_PORT = int(os.getenv("COUNTER_PORT", "5000"))
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://counter:counter@localhost:5432/counter",
)
STATIC_MESSAGE = os.getenv("STATIC_MESSAGE", "not implemented yet")
CONFIG_SERVER_URL = os.getenv("CONFIG_SERVER_URL", "http://localhost:7000")
SERVICE_ADDRESS = os.getenv("SERVICE_ADDRESS", f"localhost:{COUNTER_PORT}")
HAZELCAST_ADDR = os.getenv("HAZELCAST_ADDR", "localhost:5701")
COUNTER_QUEUE_NAME = os.getenv("COUNTER_QUEUE_NAME", "counter-transactions")

db_pool: asyncpg.Pool | None = None
hz_client: hazelcast.HazelcastClient | None = None
hz_queue: Any = None
consumer_task: asyncio.Task[None] | None = None


async def register_service() -> None:
    async with httpx.AsyncClient() as client:
        for attempt in range(1, 11):
            try:
                response = await client.post(
                    f"{CONFIG_SERVER_URL}/register",
                    json={"name": "counter-service", "address": f"http://{SERVICE_ADDRESS}"},
                    timeout=2.0,
                )
                response.raise_for_status()
                print(f"counter-service registered at config-server as http://{SERVICE_ADDRESS}", flush=True)
                return
            except Exception as exc:
                print(f"counter-service registration retry {attempt}/10: {exc}", flush=True)
                await asyncio.sleep(2)


async def consume_counter_queue() -> None:
    if hz_queue is None or db_pool is None:
        return
    loop = asyncio.get_event_loop()
    while True:
        try:
            item = await loop.run_in_executor(None, hz_queue.take)
            value = item.get("value") if isinstance(item, dict) else str(item)
            if not value:
                continue
            async with db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "INSERT INTO counter_messages (value) VALUES ($1) RETURNING id", value
                )
            print(f"counter-service consumed transaction {row['id']}: {value}", flush=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"counter-service queue consumer error: {exc}", flush=True)
            await asyncio.sleep(2)


@asynccontextmanager
async def lifespan(application: FastAPI):
    global db_pool, hz_client, hz_queue, consumer_task
    for attempt in range(1, 11):
        try:
            db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
            break
        except OSError as exc:
            if attempt == 10:
                raise
            print(f"counter-service waiting for PostgreSQL ({attempt}/10): {exc}", flush=True)
            await asyncio.sleep(2)
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS counter_messages (
                id SERIAL PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
    print(f"counter-service connected to PostgreSQL, static message: {STATIC_MESSAGE}", flush=True)
    loop = asyncio.get_event_loop()
    def init_hazelcast() -> tuple[hazelcast.HazelcastClient, Any]:
        client = hazelcast.HazelcastClient(
            cluster_members=[HAZELCAST_ADDR],
            cluster_name="dev",
            connection_timeout=10.0,
        )
        return client, client.get_queue(COUNTER_QUEUE_NAME).blocking()

    hz_client, hz_queue = await loop.run_in_executor(None, init_hazelcast)
    await register_service()
    consumer_task = asyncio.create_task(consume_counter_queue())
    yield
    if consumer_task:
        consumer_task.cancel()
        try:
            await consumer_task
        except asyncio.CancelledError:
            pass
    if hz_client:
        hz_client.shutdown()
    if db_pool:
        await db_pool.close()


app = FastAPI(title="counter-service", lifespan=lifespan)


@app.get("/message", response_class=PlainTextResponse)
async def get_message() -> PlainTextResponse:
    if db_pool is None:
        raise HTTPException(status_code=500, detail="database not initialized")
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT value FROM counter_messages ORDER BY id")
    return PlainTextResponse(content="\n".join(r["value"] for r in rows))


@app.post("/counter")
async def add_counter(payload: dict[str, Any]) -> dict[str, Any]:
    value = payload.get("value")
    if not value:
        raise HTTPException(status_code=400, detail="value is required")
    if db_pool is None:
        raise HTTPException(status_code=500, detail="database not initialized")
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "INSERT INTO counter_messages (value) VALUES ($1) RETURNING id", value
        )
    return {"id": row["id"], "value": value, "status": "stored"}


@app.get("/counter")
async def get_counters() -> dict[str, Any]:
    if db_pool is None:
        raise HTTPException(status_code=500, detail="database not initialized")
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT id, value FROM counter_messages ORDER BY id")
    return {"messages": [{"id": r["id"], "value": r["value"]} for r in rows]}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=COUNTER_PORT)
