from datetime import datetime

from httpx import AsyncClient, Headers

from wolf_comm import constants
from wolf_comm.constants import SESSION_ID, TIMESTAMP
from wolf_comm.helpers import bearer_header


class CreateSessionFailed(Exception):
    """CreateSession2 answered without a BrowserSessionId (error response)."""

    def __init__(self, response):
        self.response = response
        if isinstance(response, dict):
            # error code/type/message only: MessageParams may carry values
            details = {k: response[k] for k in ('ErrorCode', 'ErrorType', 'Message') if k in response}
            super().__init__(f"CreateSession2 failed: {details or sorted(response)}")
        else:
            super().__init__(f"CreateSession2 failed: {type(response).__name__}")


# BrowserSessionId is a JSON number on the wire (verified against the
# openHAB wolfsmartset binding's CreateSession2DTO, which declares Integer),
# matching WolfClient.session_id: Optional[int].
async def create_session(client: AsyncClient, token: str) -> int:
    data = {
        TIMESTAMP: datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    resp = await client.post(
        constants.BASE_URL_PORTAL + "/api/portal/CreateSession2",
        headers=Headers({
            **bearer_header(token),
            **{"Content-Type": "application/json"}
            }
        ),
        json=data
    )

    body = resp.json()
    if not isinstance(body, dict) or 'BrowserSessionId' not in body:
        raise CreateSessionFailed(body)
    return body['BrowserSessionId']


async def update_session(client: AsyncClient, token: str, session_id: int):
    data = {
        SESSION_ID: session_id
    }
    await client.post(
        constants.BASE_URL_PORTAL + "/api/portal/UpdateSession",
        headers=Headers({
            **bearer_header(token),
            **{"Content-Type": "application/json"}
            }
        ),
        json=data)
