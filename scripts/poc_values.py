"""Proof of concept: measure the calls the Home Assistant integration makes.

Runs, one request at a time with pauses and stops at the first problem:

  A. GetSystemStateList with several systems in ONE request (batch sizes)
  B. for a few systems: fetch_parameters (incl. the localization file),
     then fetch_value for ALL parameters, then for a SUBSET only

Usage (credentials from the environment only):

    $env:WOLF_USER = "..."
    $env:WOLF_PASSWORD = Read-Host "Passwort"
    $env:PYTHONPATH = "."
    .\\venv\\Scripts\\python scripts/poc_values.py [--systems 3] [--pause 5]
                                                  [--batch-sizes 1,2,5,10] [--subset 20]

Output: counts, durations and error codes only. No names, values, addresses
or credentials are printed.
"""
import argparse
import asyncio
import os
import sys
import time

from wolf_comm import WolfClient

PAGE_SIZE = 10


class Stop(Exception):
    """Raised to end the run at the first problem."""


def error_fields(data) -> dict:
    if isinstance(data, dict):
        return {k: data[k] for k in ("ErrorCode", "ErrorType", "Message") if k in data}
    return {}


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


async def timed(label: str, call):
    started = time.monotonic()
    try:
        result = await call()
    except Exception as err:
        # FetchFailed messages only carry error code/message/field names;
        # for anything else print the type only.
        detail = str(err) if type(err).__name__ in ("FetchFailed", "ParameterReadError") else ""
        print(f"  {label}: {time.monotonic() - started:.1f}s FAILED {type(err).__name__} {detail}")
        raise Stop from err
    print(f"  {label}: {time.monotonic() - started:.1f}s", end="")
    return result


async def state_batches(client, request, systems, sizes, pause):
    print("A. GetSystemStateList, several systems per request")
    for size in sizes:
        chosen = systems[:size]
        entries = []
        for item in chosen:
            entry = {"SystemId": item["Id"], "GatewayId": item["GatewayId"]}
            if item.get("SystemShareId") is not None:
                entry["SystemShareId"] = item["SystemShareId"]
            entries.append(entry)
        response = await timed(
            f"batch of {size}",
            lambda: request("post", "api/portal/GetSystemStateList", json={"SystemList": entries}),
        )
        if isinstance(response, list):
            online = sum(
                1 for r in response
                if isinstance(r, dict) and r.get("GatewayState", {}).get("IsOnline")
            )
            print(f" -> {len(response)} entries for {size} requested, {online} online")
        else:
            print(f" -> unexpected {type(response).__name__} {error_fields(response)}")
            raise Stop
        await asyncio.sleep(pause)


async def values(client, systems, count, subset, pause):
    print("B. parameters and values per system")
    done = 0
    for item in systems:
        if done >= count:
            return
        gateway, system_id = item["GatewayId"], item["Id"]
        print(f" system Id={system_id}")
        try:
            params = await timed("fetch_parameters", lambda: client.fetch_parameters(gateway, system_id))
        except Stop as stop:
            # a system with an invalid configuration is skipped; any other
            # problem (e.g. 'Portal-Server reagiert nicht') ends the run
            if "Ungültige Konfiguration" not in str(stop.__cause__):
                raise
            await asyncio.sleep(pause)
            continue
        bundles = len({p.bundle_id for p in params})
        print(f" -> {len(params)} parameters in {bundles} bundles")
        await asyncio.sleep(pause)

        result = await timed("fetch_value (all)", lambda: client.fetch_value(gateway, system_id, params))
        print(f" -> {len(result)} values")
        await asyncio.sleep(pause)

        small = params[:subset]
        result = await timed(f"fetch_value (first {len(small)})", lambda: client.fetch_value(gateway, system_id, small))
        print(f" -> {len(result)} values")
        await asyncio.sleep(pause)
        done += 1


async def main(args) -> int:
    user = os.environ.get("WOLF_USER")
    password = os.environ.get("WOLF_PASSWORD")
    if not user or not password:
        print("Set WOLF_USER and WOLF_PASSWORD in the environment.", file=sys.stderr)
        return 2

    client = WolfClient(user, password)
    request = client._WolfClient__request
    try:
        systems = await list_systems(request)
        print(f"{len(systems)} systems")
        sizes = [int(x) for x in args.batch_sizes.split(",") if x]
        await state_batches(client, request, systems, sizes, args.pause)
        await values(client, systems, args.systems, args.subset, args.pause)
        print("Done.")
    except Stop:
        print("Stopped at the first problem.")
    finally:
        await client.client.aclose()
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--systems", type=int, default=3)
    parser.add_argument("--pause", type=float, default=5.0)
    parser.add_argument("--batch-sizes", default="1,2,5,10")
    parser.add_argument("--subset", type=int, default=20)
    sys.exit(asyncio.run(main(parser.parse_args())))
