import sys


PY37 = sys.version_info >= (3, 7)


if PY37:
    from contextlib import nullcontext

    nullcontext = nullcontext
else:
    class nullcontext():  # pragma: no cover
        def __enter__(self):
            pass

        def __exit__(self, *excinfo):
            pass
