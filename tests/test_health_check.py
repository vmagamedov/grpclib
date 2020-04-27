from unittest.mock import Mock, patch

import pytest

from grpclib.health.check import ServiceCheck


@pytest.mark.asyncio
async def test_zero_monotonic_time():

    async def check():
        return True

    def fake_monotonic():
        return 0.0

    check_mock = Mock(side_effect=check)
    service_check = ServiceCheck(check_mock, check_ttl=1, check_timeout=0.001)

    with patch('{}.time'.format(ServiceCheck.__module__)) as time:
        time.monotonic.side_effect = fake_monotonic
        assert time.monotonic.call_count == 0
        # first check
        await service_check.__check__()
        assert time.monotonic.call_count == 1
        check_mock.assert_called_once()
        assert service_check.__status__() is True
        # second check
        await service_check.__check__()  # should be cached
        assert time.monotonic.call_count == 2
        check_mock.assert_called_once()
        assert service_check.__status__() is True
