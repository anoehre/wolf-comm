"""Probe GetGuiDescriptionForGateway for a few systems, one request at a time.

Usage (credentials from the environment only):

    $env:WOLF_USER = "..."; $env:WOLF_PASSWORD = "..."
    python scripts/probe_parameters.py [count]      # default 5 systems

Prints, per system, only: Id, IsForeignSystem, whether the answer has
MenuItems, and for error answers ErrorCode/ErrorType/Message. No names,
addresses or credentials are printed.
"""
import asyncio
import os
import sys

from wolf_comm import WolfClient

PAUSE_SECONDS = 3  # be gentle with the portal


async def main(count: int) -> int:
    user = os.environ.get("WOLF_USER")
    password = os.environ.get("WOLF_PASSWORD")
    if not user or not password:
        print("Set WOLF_USER and WOLF_PASSWORD in the environment.", file=sys.stderr)
        return 2

    client = WolfClient(user, password)
    request = client._WolfClient__request
    try:
        page = await request("get", "api/portal/GetSystemListByUserPaged",
                             params={"pageIndex": 0, "pageSize": 10})
        for item in page["Items"][:count]:
            sys_id, gateway_id = item["Id"], item["GatewayId"]
            foreign = item.get("IsForeignSystem")
            params = {"GatewayId": gateway_id, "SystemId": sys_id}
            variants = [("plain", params)]
            if item.get("SystemShareId") is not None:
                variants.append(("with SystemShareId", {**params, "SystemShareId": item["SystemShareId"]}))
            for label, query in variants:
                desc = await request("get", "api/portal/GetGuiDescriptionForGateway", params=query)
                if isinstance(desc, dict) and "MenuItems" in desc:
                    result = "OK (has MenuItems)"
                elif isinstance(desc, dict):
                    err = {k: desc[k] for k in ("ErrorCode", "ErrorType", "Message") if k in desc}
                    result = f"no MenuItems, keys={sorted(desc)}, {err}"
                else:
                    result = f"unexpected {type(desc).__name__}"
                print(f"Id={sys_id} foreign={foreign} {label}: {result}")
                await asyncio.sleep(PAUSE_SECONDS)
    finally:
        await client.client.aclose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 5)))
