"""Every value of one facet, for the ones a chart cannot show.

A chart card draws its five largest bars. A camera, a lens or an ISO that sits
below them can be seen in the footer's "N more" but not chosen, and on a library
with dozens of bodies the interesting values are exactly the ones that fall off
the end. This is the full list for one facet: the same searchable, counted list
the sidebar uses, with the height a dialog can afford instead of a panel's.
"""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout

from ...i18n import tr
from ..components.check_list import CheckList

#: Taller than the sidebar's list. The sidebar caps at six rows to keep the
#: panel small; a dialog exists precisely to show the whole tail, so it gets
#: room to do that.
DIALOG_LIST_HEIGHT = 380


class FacetDialog(QDialog):
    """Pick any value of a facet, not only the largest few."""

    def __init__(self, theme, title: str, values, selected, placeholder: str,
                 parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(440)
        self.setStyleSheet(f"QDialog {{ background: {theme.bg}; }}")

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        heading = QLabel(title)
        heading.setStyleSheet("font-weight: 600; font-size: 14px;")
        layout.addWidget(heading)

        self.checklist = CheckList(theme, placeholder)
        self.checklist.list.setMaximumHeight(DIALOG_LIST_HEIGHT)
        self.checklist.set_values(values, selected)
        layout.addWidget(self.checklist)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText(tr("Apply"))
        buttons.button(QDialogButtonBox.Ok).setObjectName("primary")
        buttons.button(QDialogButtonBox.Cancel).setText(tr("Cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected(self) -> set[str]:
        return set(self.checklist.selected_values())
