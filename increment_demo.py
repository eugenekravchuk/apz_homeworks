import argparse
import multiprocessing as mp
import time
from typing import Literal

from client_common import new_client

Mode = Literal["nolock", "pessimistic", "optimistic"]


def _worker(mode: Mode, map_name: str, key: str, iterations: int) -> None:
    client = new_client()
    try:
        m = client.get_map(map_name).blocking()
        m.put_if_absent(key, 0)

        if mode == "nolock":
            for _ in range(iterations):
                v = m.get(key)
                m.put(key, int(v) + 1)
            return

        if mode == "pessimistic":
            for _ in range(iterations):
                m.lock(key)
                try:
                    v = m.get(key)
                    m.put(key, int(v) + 1)
                finally:
                    m.unlock(key)
            return

        # optimistic
        for _ in range(iterations):
            while True:
                v = m.get(key)
                new_v = int(v) + 1
                # Compare-and-set loop
                if m.replace_if_same(key, v, new_v):
                    break
    finally:
        client.shutdown()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["nolock", "pessimistic", "optimistic"], required=True)
    parser.add_argument("--map", default="demo-map")
    parser.add_argument("--key", default="key")
    parser.add_argument("--clients", type=int, default=3)
    parser.add_argument("--iterations", type=int, default=10_000)
    args = parser.parse_args()

    # Reset key
    admin = new_client()
    try:
        m = admin.get_map(args.map).blocking()
        m.put(args.key, 0)
    finally:
        admin.shutdown()

    ctx = mp.get_context("spawn")
    procs = [
        ctx.Process(target=_worker, args=(args.mode, args.map, args.key, args.iterations))
        for _ in range(args.clients)
    ]

    t0 = time.perf_counter()
    for p in procs:
        p.start()
    for p in procs:
        p.join()
    dt = time.perf_counter() - t0

    client = new_client()
    try:
        m = client.get_map(args.map).blocking()
        final_value = m.get(args.key)
    finally:
        client.shutdown()

    expected = args.clients * args.iterations
    print(f"Mode: {args.mode}")
    print(f"Expected final value: {expected}")
    print(f"Actual final value:   {final_value}")
    print(f"Wall time (s):        {dt:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
