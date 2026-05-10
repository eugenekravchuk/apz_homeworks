# Task_3-Microservices_with_Hazelcast

Extends Task 1: logging-service now uses a **Hazelcast Distributed IMap** for shared storage across 3 instances. counter-service (formerly messages-service) uses **PostgreSQL**. facade-service randomly picks a logging-service instance and falls back to the next one if unavailable.

## Architecture
- **facade-service** (port 3000) — HTTP entry point; randomly selects one of 3 logging-service instances per request, falls back on failure
- **logging-service** ×3 (ports 4001/4002/4003 HTTP, 50051/50052/50053 gRPC) — each connects to its own Hazelcast node but shares the same distributed `messages` IMap
- **Hazelcast cluster** ×3 nodes (ports 5701/5702/5703) — data is replicated/partitioned across all nodes
- **counter-service** (port 5000) — static message endpoint + PostgreSQL-backed counter storage
- **PostgreSQL** (port 5432)

## Quick start (Docker)

```bash
docker compose up --build
```

## API
### POST — store a message
```bash
curl -X POST http://localhost:3000/api/messages \
  -H "Content-Type: application/json" \
  -d "{\"msg\": \"msg1\"}"
```

### GET — read all messages
```bash
curl http://localhost:3000/api/messages
```

### POST 10 messages at once (bash)
```bash
for i in $(seq 1 10); do
  curl -s -X POST http://localhost:3000/api/messages \
    -H "Content-Type: application/json" \
    -d "{\"msg\": \"msg$i\"}" | python -m json.tool
done
```

## Fault-tolerance testing
```bash
# Stop one logging instance
docker compose stop logging-1

# POST/GET still works via logging-2 or logging-3
curl -X POST http://localhost:3000/api/messages -H "Content-Type: application/json" -d "{\"msg\":\"test\"}"

# Stop a Hazelcast node — data is preserved on remaining nodes
docker compose stop hazelcast-1
curl http://localhost:3000/api/messages
```

## Environment variables
| Variable | Default | Service |
|---|---|---|
| `FACADE_PORT` | 3000 | facade |
| `LOGGING_GRPC_ADDRS` | `localhost:50051` | facade (comma-separated) |
| `COUNTER_SERVICE_URL` | `http://localhost:5000` | facade |
| `LOGGING_PORT` | 4000 | logging |
| `LOGGING_GRPC_PORT` | 50051 | logging |
| `HAZELCAST_ADDR` | `localhost:5701` | logging |
| `SERVICE_INSTANCE` | `logging-1` | logging (for log labels) |
| `COUNTER_PORT` | 5000 | counter |
| `DATABASE_URL` | `postgresql://counter:counter@localhost:5432/counter` | counter |
| `STATIC_MESSAGE` | `not implemented yet` | counter |

## Notes
- Hazelcast IMap named `messages` is shared across all logging-service instances — shutting down any instance does not lose data.
- PostgreSQL data is persisted in a Docker volume (`postgres-data`).
