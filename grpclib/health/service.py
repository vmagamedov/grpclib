import asyncio

from ..const import Status
from ..utils import _service_name

from .v1.health_pb2 import HealthCheckResponse
from .v1.health_grpc import HealthBase


def _status(checks):
    if all(check.__status__() for check in checks):
        return HealthCheckResponse.ServingStatus.SERVING
    else:
        return HealthCheckResponse.ServingStatus.NOT_SERVING


class Health(HealthBase):
    """
    Health({
        auth_service: [redis_check],
        billing_service: [master_db_check],
    })
    """
    def __init__(self, checks):
        self._checks = {_service_name(s): list(check_list)
                        for s, check_list in checks.items()}

    async def Check(self, stream):
        request = await stream.recv_message()
        checks = self._checks.get(request.service)
        if checks is None:
            await stream.send_trailing_metadata(status=Status.NOT_FOUND)
        elif len(checks) == 0:
            await stream.send_message(HealthCheckResponse(
                status=HealthCheckResponse.ServingStatus.SERVING,
            ))
        else:
            for check in checks:
                check.__check__()
            await stream.send_message(HealthCheckResponse(
                status=_status(checks),
            ))

    async def Watch(self, stream):
        request = await stream.recv_message()
        checks = self._checks.get(request.service)
        if checks is None:
            await stream.send_message(HealthCheckResponse(
                status=HealthCheckResponse.ServingStatus.SERVICE_UNKNOWN,
            ))
            while True:
                await asyncio.sleep(3600)
        elif len(checks) == 0:
            await stream.send_message(HealthCheckResponse(
                status=HealthCheckResponse.ServingStatus.SERVING,
            ))
            while True:
                await asyncio.sleep(3600)
        else:
            events = []
            for check in checks:
                events.append(await check.__subscribe__())
            try:
                await stream.send_message(HealthCheckResponse(
                    status=_status(checks),
                ))
                while True:
                    await asyncio.wait(
                        {e.wait() for e in events},
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    for event in events:
                        event.clear()
                    await stream.send_message(HealthCheckResponse(
                        status=_status(checks),
                    ))
            finally:
                for check, event in zip(checks, events):
                    await check.__unsubscribe__(event)
