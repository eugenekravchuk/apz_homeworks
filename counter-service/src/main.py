from __future__ import annotations

import os
import asyncio
from contextlib import asynccontextmanager
from typing import Any

import asyncpg
from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse

COUNTER_PORT = int(os.getenv("COUNTER_PORT", "5000"))
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://counter:counter@localhost:5432/counter",
)
STATIC_MESSAGE = os.getenv("STATIC_MESSAGE", "not implemented yet")

db_pool: asyncpg.Pool | None = None


@asynccontextmanager
async def lifespan(application: FastAPI):
    global db_pool
    for attempt in range(1, 11):
        try:
            db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
            break
        except OSError as exc:
            if attempt == 10:
                raise
            print(f"counter-service waiting for PostgreSQL ({attempt}/10): {exc}")
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
    print(f"counter-service connected to PostgreSQL, static message: {STATIC_MESSAGE}")
    yield
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
