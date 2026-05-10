# Lab 4 — Microservices with Messaging Queue

The project implements asynchronous communication between `facade-service` and `counter-service` through a Hazelcast Distributed Queue. It also adds `config-server`, where services register themselves on startup and from which `facade-service` discovers service instances before making requests.

## Architecture

- **facade-service** (`localhost:3000`) — public HTTP API. POST writes to `logging-service` and puts a transaction into Hazelcast Queue for `counter-service`; GET reads logs and counters.
- **config-server** (`localhost:7000`) — in-memory service registry with `/register`, `/services`, and `/services/{name}`.
- **logging-service ×3** (`localhost:4001..4003`, gRPC `50051..50053`) — stores messages in Hazelcast `messages` IMap and registers gRPC addresses in `config-server`.
- **counter-service** (`localhost:5000`) — consumes transactions from Hazelcast Queue `counter-transactions`, stores them in PostgreSQL, and exposes `/counter`.
- **Hazelcast cluster ×3** (`localhost:5701..5703`) — distributed IMap for logs and Queue for async counter updates.
- **PostgreSQL** (`localhost:5432`) — persistent storage for `counter-service`.

## Quick start

```bash
docker compose up --build
```

Check registered services:

```bash
curl http://localhost:7000/services
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

Show service registrations:

```bash
docker compose logs config-server --since=10m
```

Clean all containers and persisted PostgreSQL data:

```bash
docker compose down -v
```

## Fault-tolerance scenario

Pause `counter-service`:

```bash
docker pause hw3_version2-counter-service-1
```

POST requests still succeed because `facade-service` puts transactions into Hazelcast Queue:

```bash
curl -X POST http://localhost:3000/api/messages \
  -H "Content-Type: application/json" \
  -d "{\"msg\":\"queued-while-counter-paused\"}"
```

GET through `facade-service` returns logs and `null` for unavailable counter data:

```bash
curl http://localhost:3000/api/messages
```

Resume `counter-service`:

```bash
docker unpause hw3_version2-counter-service-1
```

After a short delay, `counter-service` consumes accumulated queue messages:

```bash
docker compose logs counter-service --since=5m | grep "consumed transaction"
curl http://localhost:3000/api/messages
```

## Environment variables

| Variable | Default | Service |
|---|---|---|
| `CONFIG_PORT` | `7000` | config-server |
| `FACADE_PORT` | `3000` | facade-service |
| `CONFIG_SERVER_URL` | `http://localhost:7000` | facade/logging/counter |
| `LOGGING_GRPC_ADDRS` | `localhost:50051` | facade fallback |
| `COUNTER_SERVICE_URL` | `http://localhost:5000` | facade fallback |
| `HAZELCAST_ADDR` | `localhost:5701` | facade/logging/counter |
| `COUNTER_QUEUE_NAME` | `counter-transactions` | facade/counter |
| `LOGGING_PORT` | `4000` | logging-service |
| `LOGGING_GRPC_PORT` | `50051` | logging-service |
| `SERVICE_INSTANCE` | `logging-1` | logging-service |
| `SERVICE_GRPC_ADDRESS` | `localhost:50051` | logging-service registry address |
| `COUNTER_PORT` | `5000` | counter-service |
| `SERVICE_ADDRESS` | `localhost:5000` | counter-service registry address |
| `DATABASE_URL` | `postgresql://counter:counter@localhost:5432/counter` | counter-service |
