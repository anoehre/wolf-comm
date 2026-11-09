"""Slowly request GetGuiDescriptionForGateway for ALL systems of an account.

Goal: find out whether failures ("Der Portal-Server reagiert nicht",
ErrorCode 10) belong to the account/time (everything fails in bursts) or to
single systems (the same ids fail again and again).

Usage (credentials from the environment only):

    $env:WOLF_USER = "..."
    $env:WOLF_PASSWORD = Read-Host "Passwort"
    $env:PYTHONPATH = "."
    .\\venv\\Scripts\\python scripts/scan_parameters.py [--pause 5] [--limit 0]
                                                       [--max-consecutive-errors 5]

- one request at a time, `--pause` seconds between requests (default 5)
- stops early after N errors in a row (default 5) so the portal is not hammered
- after the first pass it waits 60 s and retries the failed ids once
- `--limit N` scans only the first N systems (0 = all)

Output: one line per request with Id, result and duration, and a summary.
No names, addresses or credentials are printed.
"""
import argparse
import asyncio
import os
import sys
import time

from wolf_comm import WolfClient

PAGE_SIZE = 10  # the portal caps GetSystemListByUserPaged at 10 per page
RETRY_WAIT_SECONDS = 60


def describe(desc) -> str:
    if isinstance(desc, dict) and "MenuItems" in desc:
        return "OK"
    if isinstance(desc, dict):
        err = {k: desc[k] for k in ("ErrorCode", "ErrorType", "Message") if k in desc}
        return f"ERROR {err}"
    return f"UNEXPECTED {type(desc).__name__}"


async def probe(request, item) -> tuple[bool, str, float]:
    started = time.monotonic()
    try:
        desc = await request(
            "get",
            "api/portal/GetGuiDescriptionForGateway",
            params={"GatewayId": item["GatewayId"], "SystemId": item["Id"]},
        )
        text = describe(desc)
    except Exception as err:  # type only: the body is never printed
        text = f"EXCEPTION {type(err).__name__}"
    return text == "OK", text, time.monotonic() - started


async def list_systems(request) -> list[dict]:
    systems, page_index = [], 0
    while True:
        page = await request(
            "get",
            "api/portal/GetSystemListByUserPaged",
            params={"pageIndex": page_index, "pageSize": PAGE_SIZE},
        )
        systems.extend(page["Items"])
        if not page["Items"] or len(systems) >= page["TotalCount"]:
            return systems
        page_index += 1
        await asyncio.sleep(1)


async def main(args) -> int:
    user = os.environ.get("WOLF_USER")
    password = os.environ.get("WOLF_PASSWORD")
    if not user or not password:
        print("Set WOLF_USER and WOLF_PASSWORD in the environment.", file=sys.stderr)
        return 2

    client = WolfClient(user, password)
    request = client._WolfClient__request
    failed: list[dict] = []
    ok_count = 0
    try:
        systems = await list_systems(request)
        if args.limit:
            systems = systems[: args.limit]
        print(f"{len(systems)} systems, pause {args.pause} s between requests")

        consecutive = 0
        for index, item in enumerate(systems, 1):
            ok, text, seconds = await probe(request, item)
            print(f"[{index}/{len(systems)}] Id={item['Id']} {seconds:.1f}s {text}")
            if ok:
                ok_count += 1
                consecutive = 0
            else:
                failed.append(item)
                consecutive += 1
                if consecutive >= args.max_consecutive_errors:
                    print(f"Stopping: {consecutive} errors in a row.")
                    break
            await asyncio.sleep(args.pause)

        recovered = 0
        if failed and consecutive < args.max_consecutive_errors:
            print(f"Retrying {len(failed)} failed systems after {RETRY_WAIT_SECONDS} s ...")
            await asyncio.sleep(RETRY_WAIT_SECONDS)
            still_failed = []
            for item in failed:
                ok, text, seconds = await probe(request, item)
                print(f"retry Id={item['Id']} {seconds:.1f}s {text}")
                if ok:
                    recovered += 1
                else:
                    still_failed.append(item)
                await asyncio.sleep(args.pause)
            failed = still_failed

        print("Summary:")
        print(f"  OK in first pass: {ok_count}")
        print(f"  recovered on retry: {recovered}")
        print(f"  failed (ids): {[item['Id'] for item in failed]}")
    finally:
        await client.client.aclose()
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--pause", type=float, default=5.0)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--max-consecutive-errors", type=int, default=5)
    sys.exit(asyncio.run(main(parser.parse_args())))
