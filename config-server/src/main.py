from __future__ import annotations

import os
from collections import defaultdict

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

CONFIG_PORT = int(os.getenv("CONFIG_PORT", "7000"))

app = FastAPI(title="config-server")
registry: dict[str, set[str]] = defaultdict(set)


class ServiceRegistration(BaseModel):
    name: str
    address: str


@app.post("/register")
async def register_service(payload: ServiceRegistration) -> dict[str, object]:
    if not payload.name or not payload.address:
        raise HTTPException(status_code=400, detail="name and address are required")
    registry[payload.name].add(payload.address)
    print(f"Registered {payload.name}: {payload.address}")
    return {"status": "registered", "name": payload.name, "instances": sorted(registry[payload.name])}


@app.get("/services/{service_name}")
async def get_service(service_name: str) -> dict[str, object]:
    return {"name": service_name, "instances": sorted(registry.get(service_name, set()))}


@app.get("/services")
async def get_services() -> dict[str, list[str]]:
    return {name: sorted(addresses) for name, addresses in registry.items()}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=CONFIG_PORT)
