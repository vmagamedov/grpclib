import sys

from types import TracebackType
from typing import ContextManager, Optional, Type


PY37 = sys.version_info >= (3, 7)


if not PY37:
    class nullcontext(ContextManager[None]):  # pragma: nocover
        def __enter__(self) -> None:
            pass

        def __exit__(
            self,
            exc_type: Optional[Type[BaseException]],
            exc_val: Optional[BaseException],
            exc_tb: Optional[TracebackType],
        ) -> Optional[bool]:
            pass
else:
    from contextlib import nullcontext as _nullcontext

    nullcontext = _nullcontext  # type: ignore
