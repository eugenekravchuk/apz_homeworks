# Task_3-Microservices_with_Hazelcast

## Architecture
- **facade-service** (port 3000) — HTTP entry point; randomly selects one of 3 logging-service instances per request, falls back on failure, and forwards messages to counter-service
- **logging-service** ×3 (ports 4001/4002/4003 HTTP, 50051/50052/50053 gRPC) — each connects to its own Hazelcast node but shares the same distributed `messages` IMap
- **Hazelcast cluster** ×3 nodes (ports 5701/5702/5703) — data is replicated/partitioned across all nodes
- **counter-service** (port 5000) — PostgreSQL-backed message/counter storage; exposes `/counter`
- **PostgreSQL** (port 5432)

## Quick start (Docker)

```bash
docker compose up --build
```

## API
### POST — store a message through facade
```bash
curl -X POST http://localhost:3000/api/messages \
  -H "Content-Type: application/json" \
  -d "{\"msg\": \"msg1\"}"
```

The request is written to both:
- Hazelcast via logging-service
- PostgreSQL via counter-service

### GET — read combined messages through facade
```bash
curl http://localhost:3000/api/messages
```

The response combines data from Hazelcast and PostgreSQL. Therefore, the same submitted message can appear twice: once from logging-service and once from counter-service.

### GET — read PostgreSQL-backed counter-service data directly
```bash
curl http://localhost:5000/counter
```

Expected response shape:
```json
{"messages":[{"id":1,"value":"msg1"}]}
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
curl http://localhost:3000/api/messages
curl http://localhost:5000/counter

# Stop a Hazelcast node — data remains available through the remaining Hazelcast nodes and PostgreSQL counter-service
docker compose stop hazelcast-1
curl http://localhost:3000/api/messages
curl http://localhost:5000/counter
```

## Useful report commands
```bash
# Show which logging-service instance received each message
docker compose logs logging-1 logging-2 logging-3 --since=5m | grep "Stored\|GetLogs"

# Clean all containers and PostgreSQL volume
docker compose down -v

# Performance test in Git Bash
time for i in $(seq 1 100); do
  curl -s -X POST http://localhost:3000/api/messages \
    -H "Content-Type: application/json" \
    -d "{\"msg\": \"perf$i\"}" > /dev/null
done
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
| `STATIC_MESSAGE` | unused compatibility fallback | counter |

## Notes
- Hazelcast IMap named `messages` is shared across all logging-service instances — shutting down any instance does not lose data.
- PostgreSQL data is persisted in a Docker volume (`postgres-data`).
- counter-service no longer returns `not implemented yet`; `/message` and `/counter` are backed by PostgreSQL.
