"""Compare GetSystemList with GetSystemListByUserPaged.

Usage (credentials come from the environment, never from arguments):

    set WOLF_USER=...        (PowerShell: $env:WOLF_USER = "...")
    set WOLF_PASSWORD=...
    python scripts/compare_system_lists.py

Prints only counts and numeric ids (Id, GatewayId is NOT printed). No names,
addresses, phone numbers or credentials are written to the output.
"""
import asyncio
import os
import sys

from wolf_comm import WolfClient

PAGED_PATH = "api/portal/GetSystemListByUserPaged"
# page sizes probed on page 0 only, to find out which sizes the server honours
PROBE_PAGE_SIZES = (10, 25, 50, 100, 500)
# page size used for the full walk over all pages
WALK_PAGE_SIZE = 10
MAX_PAGES = 1000  # safety stop


async def request(client: WolfClient, path: str, **kwargs):
    # __request is private (name-mangled); the script reuses it to get the
    # library's token/session/retry handling.
    return await client._WolfClient__request("get", path, **kwargs)


async def main() -> int:
    user = os.environ.get("WOLF_USER")
    password = os.environ.get("WOLF_PASSWORD")
    if not user or not password:
        print("Set WOLF_USER and WOLF_PASSWORD in the environment.", file=sys.stderr)
        return 2

    client = WolfClient(user, password)
    try:
        # 1. old endpoint
        old = await request(client, "api/portal/GetSystemList")
        old_ids = [s["Id"] for s in old]
        print(f"GetSystemList: {len(old_ids)} entries")
        print(f"  ids: {old_ids}")

        # 2. probe page sizes on page 0
        print("GetSystemListByUserPaged, page 0 with different pageSize:")
        for size in PROBE_PAGE_SIZES:
            try:
                page = await request(
                    client, PAGED_PATH, params={"pageIndex": 0, "pageSize": size}
                )
                print(
                    f"  pageSize={size}: {len(page['Items'])} items, "
                    f"TotalCount={page['TotalCount']}"
                )
            except Exception as err:  # report the type only, nothing from the body
                print(f"  pageSize={size}: failed ({type(err).__name__})")

        # 3. walk all pages until TotalCount is reached
        paged_ids = []
        total = None
        for page_index in range(MAX_PAGES):
            page = await request(
                client,
                PAGED_PATH,
                params={"pageIndex": page_index, "pageSize": WALK_PAGE_SIZE},
            )
            items = page["Items"]
            total = page["TotalCount"]
            paged_ids.extend(item["Id"] for item in items)
            if not items or len(paged_ids) >= total:
                break
        print(
            f"GetSystemListByUserPaged (pageSize={WALK_PAGE_SIZE}, all pages): "
            f"{len(paged_ids)} entries, TotalCount={total}"
        )
        print(f"  ids: {paged_ids}")

        # 4. comparison
        old_set, paged_set = set(old_ids), set(paged_ids)
        print("Comparison:")
        print(f"  duplicates in paged result: {len(paged_ids) - len(paged_set)}")
        print(f"  only in GetSystemList: {sorted(old_set - paged_set)}")
        print(f"  only in paged: {len(paged_set - old_set)} entries")
        print(f"  hypothesis (old list truncated): {len(old_set) < len(paged_set)}")
    finally:
        await client.client.aclose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
