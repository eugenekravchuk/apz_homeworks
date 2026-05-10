import os
from typing import List, Optional

import hazelcast


def get_members() -> List[str]:
    members = os.getenv("HZ_MEMBERS", "127.0.0.1:5701").strip()
    return [m.strip() for m in members.split(",") if m.strip()]


def new_client(cluster_name: Optional[str] = None):
    cluster_name = cluster_name or os.getenv("HZ_CLUSTER_NAME", "apz-hz")
    return hazelcast.HazelcastClient(
        cluster_name=cluster_name,
        cluster_members=get_members(),
        smart_routing=False,
    )
