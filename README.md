# Task_1-Microservices_Basics

Three small FastAPI services: facade-service (client entry), logging-service (stores messages in-memory with deduplication), messages-service (static placeholder response). Facade ↔ logging now talk over gRPC; facade ↔ messages remains HTTP.

## Default ports
- facade-service: 3000
- logging-service: 4000
- messages-service: 5000

Override with environment variables: `FACADE_PORT`, `LOGGING_GRPC_ADDR` (default `localhost:50051`), `MESSAGES_SERVICE_URL`, `LOGGING_PORT`, `LOGGING_GRPC_PORT` (default `50051`), `MESSAGES_PORT`, `STATIC_MESSAGE`.

## Setup
Recommended: Python 3.12 (grpcio wheels available). Example to create venv and install deps:

```bash
# from repo root
py -3.12 -m venv .venv312
.\.venv312\Scripts\activate
pip install -r logging-service/requirements.txt -r messages-service/requirements.txt -r facade-service/requirements.txt
```

## Run
Use separate terminals (or background processes):

```bash
cd logging-service && uvicorn src.main:app --host 0.0.0.0 --port 4000  # starts HTTP + gRPC (50051)
cd messages-service && uvicorn src.main:app --host 0.0.0.0 --port 5000
cd facade-service && uvicorn src.main:app --host 0.0.0.0 --port 3000
```

## API
### POST flow (store message)
- Endpoint: `POST http://localhost:3000/api/messages`
- Body: `{ "msg": "hello" }`
- Behavior: facade-service generates UUID, forwards `{id,message}` to logging-service via gRPC with retry (3 attempts, exponential backoff). logging-service stores first occurrence and ignores duplicates.

Example:
```bash
curl -X POST http://localhost:3000/api/messages -H "Content-Type: application/json" -d "{\"msg\":\"hi there\"}"
```

### GET flow (collect messages)
- Endpoint: `GET http://localhost:3000/api/messages`
- Behavior: facade-service fetches all stored messages from logging-service via gRPC and static text from messages-service via HTTP, concatenates responses.

Example:
```bash
curl http://localhost:3000/api/messages
```

## Retry + dedup hints
- To observe retry, stop logging-service while sending a POST, then start it again quickly; facade-service will reattempt up to 3 times.
- logging-service deduplicates by UUID so repeated POSTs for the same id are ignored (see logs on its console).

## Notes
- In-memory storage: restart logging-service clears stored messages.
