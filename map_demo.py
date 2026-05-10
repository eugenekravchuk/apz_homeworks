import argparse

from client_common import new_client


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--map", default="demo-map")
    parser.add_argument("--n", type=int, default=1000)
    args = parser.parse_args()

    client = new_client()
    try:
        m = client.get_map(args.map).blocking()
        m.clear()

        # Keys: 0..n (inclusive) to match assignment wording "0 to 1000"
        for k in range(0, args.n + 1):
            m.put(str(k), f"value-{k}")

        size = m.size()
        print(f"Map '{args.map}' size after insert: {size}")
        print("Now open Management Center -> Data Structures -> Maps -> demo-map")
        print("and also Cluster -> Members/Partitions to see partition distribution.")
        return 0
    finally:
        client.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
