# Lab 5 — Microservices with Consul Service Discovery and Config Server

The project implements a microservice system with Consul used as Service Registry, Service Discovery, and Config Server.

## Architecture

- **facade-service** (`localhost:3000`) — public HTTP API. POST writes to `logging-service` discovered through Consul and puts a transaction into Hazelcast Queue for `counter-service`; GET reads logs and counters.
- **Consul** (`localhost:8500`) — service registry, health checks, UI, and KV config.
- **logging-service ×3** (`localhost:4001..4003`, gRPC `50051..50053`) — stores messages in Hazelcast `messages` IMap and registers gRPC endpoints in Consul.
- **counter-service** (`localhost:5000`) — consumes transactions from Hazelcast Queue `counter-transactions`, stores them in PostgreSQL, and exposes `/counter`.
- **Hazelcast cluster ×3** (`localhost:5701..5703`) — distributed IMap for logs and Queue for async counter updates.
- **PostgreSQL** (`localhost:5432`) — persistent storage for `counter-service`.

## Quick start

```bash
docker compose up --build
```

Check registered services:

```bash
curl http://localhost:8500/v1/catalog/services
curl "http://localhost:8500/v1/health/service/logging-service?passing=true"
curl "http://localhost:8500/v1/health/service/counter-service?passing=true"
curl "http://localhost:8500/v1/health/service/facade-service?passing=true"
```

Open Consul UI:

```text
http://localhost:8500
```

Check Consul KV config:

```bash
curl http://localhost:8500/v1/kv/config/hazelcast/cluster_members?raw
curl http://localhost:8500/v1/kv/config/message_queue/counter_queue_name?raw
```

## API

### POST transaction through facade-service

```bash
curl -X POST http://localhost:3000/api/messages \
  -H "Content-Type: application/json" \
  -d "{\"msg\":\"msg1\"}"
```

Expected response:

```json
{
  "id": "...",
  "message": "msg1",
  "status": "forwarded to logging-service and queued for counter-service"
}
```

### POST 10 transactions

```bash
for i in $(seq 1 10); do
  curl -s -X POST http://localhost:3000/api/messages \
    -H "Content-Type: application/json" \
    -d "{\"msg\":\"msg$i\"}"
  echo
done
```

### GET combined data through facade-service

```bash
curl http://localhost:3000/api/messages
```

The response contains messages from `logging-service` and values stored by `counter-service`. If `counter-service` is unavailable, the response ends with `null`.

### GET counter-service data directly

```bash
curl http://localhost:5000/counter
```

Expected shape:

```json
{
  "messages": [
    {
      "id": 1,
      "value": "msg1"
    }
  ]
}
```

## Useful report commands

Show that different `logging-service` instances receive requests:

```bash
docker compose logs logging-1 logging-2 logging-3 --since=10m | grep "Stored message"
```

Show `counter-service` consuming queued transactions:

```bash
docker compose logs counter-service --since=10m | grep "consumed transaction"
```

Show service registrations in Consul:

```bash
curl http://localhost:8500/v1/catalog/services
```

Clean all containers and persisted PostgreSQL data:

```bash
docker compose down -v
```

## Fault-tolerance scenario

Stop one `logging-service` instance:

```bash
docker compose stop logging-1
```

Consul UI should show the instance changing status after the health check fails. Calls continue through other healthy instances because `facade-service` queries `/v1/health/service/logging-service?passing=true`.

```bash
curl -X POST http://localhost:3000/api/messages \
  -H "Content-Type: application/json" \
  -d "{\"msg\":\"after-one-logging-stopped\"}"
```

Start the instance again:

```bash
docker compose start logging-1
```

## Environment variables

| Variable | Default | Service |
|---|---|---|
| `FACADE_PORT` | `3000` | facade-service |
| `CONSUL_URL` | `http://localhost:8500` | facade/logging/counter |
| `SERVICE_HOST` | container hostname | facade/logging/counter Consul address |
| `SERVICE_ID` | generated from service/host/port | facade/logging/counter Consul ID |
| `LOGGING_PORT` | `4000` | logging-service |
| `LOGGING_GRPC_PORT` | `50051` | logging-service |
| `SERVICE_INSTANCE` | generated from host | logging-service logs |
| `COUNTER_PORT` | `5000` | counter-service |
| `DATABASE_URL` | `postgresql://counter:counter@localhost:5432/counter` | counter-service |

Hazelcast and queue settings are read from Consul KV:

| Key | Value |
|---|---|
| `config/hazelcast/cluster_members` | `hazelcast-1:5701,hazelcast-2:5701,hazelcast-3:5701` |
| `config/message_queue/counter_queue_name` | `counter-transactions` |

## Git branch

The required branch for this lab is:

```bash
git checkout -b micro_consul
```

## Performance testing table template

| Test scenario | Task 1 (in-mem) | Task 3 (DB) | Task 5 (final) |
|---|---:|---:|---:|
| 10 accounts — Total time |  |  |  |
| 10 accounts — logging-service contribution |  |  |  |
| 10 accounts — counter-service contribution |  |  |  |
| 1 account — Total time |  |  |  |
| 1 account — logging-service contribution |  |  |  |
| 1 account — counter-service contribution |  |  |  |
