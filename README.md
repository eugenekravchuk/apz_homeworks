# APZ Microservices

Microservice application with `facade-service`, `logging-service`, `counter-service`, Consul, Hazelcast, and PostgreSQL.

## Run

```bash
docker compose up --build
```

The main API is available at:

```text
http://localhost:3000
```

Consul UI is available at:

```text
http://localhost:8500
```

## Check services

```bash
curl http://localhost:8500/v1/catalog/services
```

Expected services include `consul`, `facade-service`, `logging-service`, and `counter-service`.

## API

### Add message

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

### Get messages

```bash
curl http://localhost:3000/api/messages
```

### Get counter data directly

```bash
curl http://localhost:5000/counter
```

## Useful logs

```bash
docker compose logs facade-service --tail=100
docker compose logs logging-1 logging-2 logging-3 --tail=100
docker compose logs counter-service --tail=100
```

Performance logs:

```bash
docker compose logs facade-service --tail=100 | grep "PERF"
docker compose logs logging-1 logging-2 logging-3 --tail=100 | grep "PERF"
docker compose logs counter-service --tail=100 | grep "PERF"
```

## Stop

Stop containers:

```bash
docker compose down
```

Stop containers and remove persisted PostgreSQL data:

```bash
docker compose down -v
```
