# Lab 3 - Microservices with Hazelcast

Microservice application with `facade-service`, `logging-service`, `counter-service`, Hazelcast, and PostgreSQL.

## Run

```bash
docker compose up --build
```

The main API is available at:

```text
http://localhost:3000
```

## API

### Add message

```bash
curl -X POST http://localhost:3000/api/messages \
  -H "Content-Type: application/json" \
  -d "{\"msg\": \"msg1\"}"
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

## Stop

Stop containers:

```bash
docker compose down
```

Stop containers and remove persisted PostgreSQL data:

```bash
docker compose down -v
```
