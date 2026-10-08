"""The warehouse's idea of "now".

Seeded data is generated relative to a point in time (``seed-db --as-of``). Set
``WAREHOUSE_AS_OF`` to the same value so the tools see the data as "current";
otherwise the real clock is used.
"""

import os
from datetime import datetime


def wall_now() -> datetime:
    """The real time, for the agent log: when a call actually happened.

    ``now()`` can be pinned to the seeded day, which is right for the warehouse's data
    but would stamp every log row with the same moment.
    """
    return datetime.now().replace(microsecond=0)


def now() -> datetime:
    value = os.environ.get("WAREHOUSE_AS_OF")
    if value:
        return datetime.fromisoformat(value)
    return datetime.now().replace(second=0, microsecond=0)
