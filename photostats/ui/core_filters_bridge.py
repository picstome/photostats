"""Which attributes are charted and which become sidebar filter lists.

Kept out of the widgets so that the query worker and the UI agree on the set
without importing anything from either side.
"""

from __future__ import annotations

from ..core.filters import (
    FACET_APERTURE,
    FACET_CAMERA,
    FACET_FILE_TYPE,
    FACET_FOCAL,
    FACET_ISO,
    FACET_LENS,
    FACET_WHITE_BALANCE,
)

#: Facets drawn as cross-filterable bar charts, in reading order.
CHART_FACETS = (
    FACET_CAMERA,
    FACET_LENS,
    FACET_ISO,
    FACET_APERTURE,
    "shutter",
    FACET_FOCAL,
    "flash",
    FACET_WHITE_BALANCE,
)

#: Facet -> the database column whose distinct values feed its sidebar list.
#: Only facets that actually have a list widget belong here: each entry is a
#: query on every refresh, and resolution has no picker.
LIST_FACETS = {
    FACET_CAMERA: "camera",
    FACET_LENS: "lens",
    FACET_WHITE_BALANCE: "white_balance",
    FACET_FILE_TYPE: "file_type",
}
