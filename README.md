# APZ HW2 - Hazelcast (Python)

Minimal setup to run Hazelcast (3 members) + Management Center in Docker and interact with it using Python client demos.

## Requirements

- Docker Desktop
- Python 3.10+

## Start services

```bash
docker compose up -d
```

- Management Center: `http://localhost:8080`

## Python environment

```bash
python -m venv .venv
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Git Bash:

```bash
source ./.venv/Scripts/activate
pip install -r requirements.txt
```

Connection env vars:

- `HZ_CLUSTER_NAME` (default `apz-hz`)
- `HZ_MEMBERS` (default `127.0.0.1:5701`)

## Demos

Insert 1000 values into a distributed map:

```bash
export HZ_MEMBERS="127.0.0.1:5701"
python ./map_demo.py --map demo-map --n 1000
```

Increment demo (nolock/pessimistic/optimistic):

```bash
python ./increment_demo.py --mode nolock
python ./increment_demo.py --mode pessimistic
python ./increment_demo.py --mode optimistic
```

Bounded queue demo:

```bash
python ./queue_demo.py --mode run --write-mode put

```
