import argparse
import multiprocessing as mp
import time

from client_common import new_client


def producer(queue_name: str, n: int, write_mode: str) -> None:
    client = new_client()
    try:
        q = client.get_queue(queue_name).blocking()
        for i in range(1, n + 1):
            if write_mode == "put":
                q.put(i)  # blocks when queue is full
                print(f"PRODUCER put {i}")
            else:
                ok = q.offer(i)
                print(f"PRODUCER offer {i} -> {ok}")
                if not ok:
                    time.sleep(0.2)
        print("PRODUCER done")
    finally:
        client.shutdown()


def consumer(queue_name: str, name: str, max_messages: int) -> None:
    client = new_client()
    try:
        q = client.get_queue(queue_name).blocking()
        for _ in range(max_messages):
            v = q.take()  # blocks until item appears
            print(f"{name} took {v}")
    finally:
        client.shutdown()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue", default="bounded-queue")
    parser.add_argument("--mode", choices=["run", "fill_no_consumers"], required=True)
    parser.add_argument("--n", type=int, default=100)
    parser.add_argument("--write-mode", choices=["put", "offer"], default="put")
    args = parser.parse_args()

    # Clear queue first
    admin = new_client()
    try:
        q = admin.get_queue(args.queue).blocking()
        q.clear()
    finally:
        admin.shutdown()

    ctx = mp.get_context("spawn")

    if args.mode == "fill_no_consumers":
        p = ctx.Process(target=producer, args=(args.queue, args.n, args.write_mode))
        p.start()
        p.join()
        return 0

    # run mode: 1 producer, 2 consumers
    # Consumers should receive items immediately as they become available.
    c1 = ctx.Process(target=consumer, args=(args.queue, "CONSUMER-1", args.n // 2))
    c2 = ctx.Process(target=consumer, args=(args.queue, "CONSUMER-2", args.n - (args.n // 2)))
    p = ctx.Process(target=producer, args=(args.queue, args.n, args.write_mode))

    c1.start()
    c2.start()
    p.start()

    p.join()
    c1.join()
    c2.join()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
