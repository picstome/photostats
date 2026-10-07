"""Statistics derived from the current filter — the "insights" panel.

Plain sentences a photographer can read at a glance: which body dominates, how
often the flash fires, whether these shots are mostly wide open.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .filters import FACET_APERTURE, FACET_CAMERA, FACET_ISO, FACET_LENS, Filter
from .queries import FacetResult, PhotoStore


@dataclass
class Insight:
    """One short fact about the current selection.

    The sentence is stored as a catalogue key plus its values rather than as
    finished English, so it can be written in whichever language is active when
    it is drawn. ``text`` stays available for the CLI, exports and tests.
    """

    key: str = ""
    emphasis: str = ""
    args: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        # An already-formed string is allowed through, so callers that have a
        # literal sentence do not have to invent a key for it.
        if not self.args and self.key:
            self.args = {"value": self.key}

    @property
    def text(self) -> str:
        from ..i18n import tr

        return tr(self.key, **self.args)

    def __str__(self) -> str:
        return self.text


class Insights:
    """Generates the short summary shown above the results table.

    Takes the facets the charts already computed rather than re-querying them:
    on a large library those nine extra GROUP BYs were the largest single cost
    of a refresh.
    """

    def __init__(
        self,
        store: PhotoStore,
        filters: Filter = Filter(),
        facets: dict[str, FacetResult] | None = None,
    ) -> None:
        self.store = store
        self.filters = filters
        self.facets = facets or {}

    def _facet(self, name: str) -> list:
        """A facet's buckets, re-querying only if the caller did not supply it.

        Returns nothing for a facet the user has already narrowed. Its buckets
        are cross-filtered — computed with that filter omitted so the chart can
        show the alternatives — so their counts describe the library, not the
        selection, and dividing them by ``totals.matched`` reported shares like
        4058%. There is no true sentence to write about a facet whose own
        filter the selection is already speaking for, so the insight is skipped
        rather than told with the wrong denominator.
        """
        if self.filters.facet_active(name):
            return []
        result = self.facets.get(name)
        return result.buckets if result is not None else self.store.facet(name, self.filters).buckets

    def build(self) -> list[Insight]:
        totals = self.store.totals(self.filters)
        if not totals.matched:
            return []

        out: list[Insight] = []
        percent = totals.matched

        camera = self._facet(FACET_CAMERA)
        if camera:
            top = camera[0]
            share = top.count / percent * 100
            if share >= 25:
                runners_up = [b for b in camera[1:] if b.count / percent >= 0.05]
                out.append(Insight(
                    "insight.camera_dominates",
                    f"{share:.0f}%",
                    {
                        "share": f"{share:.0f}%",
                        "label": top.label,
                        "others": _runner_ups(runners_up, percent),
                    },
                ))

        lens = self._facet(FACET_LENS)
        if lens and lens[0].count / percent >= 0.2:
            share = lens[0].count / percent * 100
            out.append(Insight(
                "insight.use_lens", f"{share:.0f}%",
                {"share": f"{share:.0f}%", "label": lens[0].label},
            ))

        if not self.filters.date_from and not self.filters.date_to:
            busiest = self._busiest_month()
            if busiest:
                out.append(busiest)

        out.extend(self._exposure_notes(percent))
        flash_note = self._flash_note(percent)
        if flash_note:
            out.append(flash_note)

        if totals.without_date and self.filters.include_no_date:
            out.append(Insight(
                "insight.no_exif_date", "",
                {"count": f"{totals.without_date:,}"},
            ))

        focal = self._facet("focal")
        if len(focal) >= 2:
            widest, longest = focal[0], focal[-1]
            out.append(Insight(
                "insight.focal_range", f"{widest.label}–{longest.label}",
                {"wide": widest.label, "long": longest.label},
            ))
        return out

    # -- pieces ------------------------------------------------------------
    def _busiest_month(self) -> Insight | None:
        months = self._facet("month")
        years = self._facet("year")
        if not months or len(months) < 2:
            return None
        from .queries import month_label

        top = months[0]
        # Only worth saying when it actually stands out over an even spread.
        if top.share < 0.3:
            return None
        average = top.count / max(len(years), 1)
        return Insight(
            "insight.busiest_month", f"{top.count:,}",
            {"month": month_label(int(top.key)), "average": f"{average:,.0f}"},
        )

    def _exposure_notes(self, percent: int) -> list[Insight]:
        out: list[Insight] = []
        iso = self._facet(FACET_ISO)
        if iso:
            top = iso[0]
            share = top.count / percent * 100
            if share >= 15:
                out.append(Insight(
                    "insight.common_iso", f"{top.label} · {share:.0f}%",
                    {"label": top.label, "share": f"{share:.0f}%"},
                ))
            high = sum(b.count for b in iso if b.key and b.key >= 3200)
            if high / percent >= 0.15:
                out.append(Insight(
                    "insight.high_iso", f"{high / percent * 100:.0f}%",
                    {"share": f"{high / percent * 100:.0f}%"},
                ))

        aperture = self._facet(FACET_APERTURE)
        if aperture:
            top = aperture[0]
            share = top.count / percent * 100
            if share >= 15:
                out.append(Insight(
                    "insight.common_aperture", f"{top.label} · {share:.0f}%",
                    {"label": top.label, "share": f"{share:.0f}%"},
                ))

        shutter = self._facet("shutter")
        if shutter:
            slow = [b for b in shutter if b.key and b.key >= 1 / 30]
            share = sum(b.count for b in slow) / percent * 100
            if share >= 25:
                out.append(Insight(
                    "insight.slow_shutter", f"{share:.0f}%",
                    {"share": f"{share:.0f}%"},
                ))
        return out

    def _flash_note(self, percent: int) -> Insight | None:
        buckets = self._facet("flash")
        if not buckets:
            return None
        fired = next((b for b in buckets if b.key == 1), None)
        if fired and fired.count / percent >= 0.1:
            return Insight(
                "insight.used_flash",
                f"{fired.count / percent * 100:.0f}% · {fired.count:,}",
                {"share": f"{fired.count / percent * 100:.0f}%",
                 "count": f"{fired.count:,}"},
            )
        if not fired and percent >= 10:
            return Insight("insight.no_flash")
        return None


def facet_summary_line(result, top: int = 3) -> str:
    """'NIKON Z8 61% · Canon R6 24% · Sony 9%' — used by the CLI and exports."""
    parts = [f"{b.label} {b.share * 100:.0f}%" for b in result.buckets[:top] if b.share > 0]
    return " · ".join(parts)


def _runner_ups(runners_up, percent: int) -> str:
    """'Canon R6 14% · Sony 9%' — the runners-up worth mentioning."""
    return " · ".join(
        f"{b.label} {b.count / percent * 100:.0f}%" for b in runners_up[:2]
    )
