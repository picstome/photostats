"""Settings dialog: cache location, exiftool, appearance, indexing."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...core.exiftool import exiftool_version, find_exiftool, install_hint
from ...core.paths import CACHE_CUSTOM, CACHE_LOCAL, CACHE_NEXT_TO_PHOTOS
from ...i18n import languages, product_title, tr

#: Widths so the dialog reads as one aligned column of fields. Drop-downs
#: carry long values ("Next to the photos (portable)") so they need room;
#: number fields hold one to four digits and look broken when stretched.
FORM_FIELD_WIDTH = 250
FORM_NUMBER_WIDTH = 112

CACHE_LABELS = {
    CACHE_NEXT_TO_PHOTOS: tr("Next to the photos (portable)"),
    CACHE_LOCAL: tr("On this computer only"),
    CACHE_CUSTOM: "Choose a folder…",
}


class SettingsDialog(QDialog):
    """Edits an :class:`AppConfig`; nothing is written until OK."""

    def __init__(self, config, theme, parent=None) -> None:
        super().__init__(parent)
        self.config = config
        self.theme = theme
        self.setWindowTitle(product_title("Settings"))
        self.setMinimumWidth(520)
        self.setStyleSheet(f"QDialog {{ background: {theme.bg}; }}")

        layout = QVBoxLayout(self)
        layout.setSpacing(14)

        # -- appearance -----------------------------------------------------
        self.theme_box = QComboBox()
        self.theme_box.addItem(tr("Match the system"), "system")
        self.theme_box.addItem(tr("Dark"), "dark")
        self.theme_box.addItem(tr("Light"), "light")
        current = config.theme_name
        index = self.theme_box.findData(current)
        self.theme_box.setCurrentIndex(index if index >= 0 else 0)

        # -- cache ----------------------------------------------------------
        self.cache_box = QComboBox()
        for key, label in CACHE_LABELS.items():
            self.cache_box.addItem(tr(label), key)
        index = self.cache_box.findData(config.cache_mode)
        # The note and the custom row must exist before the signal is connected,
        # otherwise reacting to the initial index would touch missing widgets.
        self.cache_note = QLabel("")
        self.cache_note.setWordWrap(True)
        self.cache_note.setObjectName("hint")
        self.custom_row = QWidget()
        self.cache_box.setCurrentIndex(index if index >= 0 else 0)
        self.cache_box.currentIndexChanged.connect(self._on_cache_mode)
        custom_layout = QHBoxLayout(self.custom_row)
        custom_layout.setContentsMargins(0, 0, 0, 0)
        self.custom_path = QLabel(config.cache_custom_path or "—")
        self.custom_path.setObjectName("hint")
        self.custom_button = QPushButton(tr("Choose…"))
        self.custom_button.setObjectName("secondary")
        self.custom_button.clicked.connect(self._choose_custom)
        custom_layout.addWidget(self.custom_path, 1)
        custom_layout.addWidget(self.custom_button)
        self._on_cache_mode()

        # -- exiftool -------------------------------------------------------
        exiftool_row = QWidget()
        exiftool_layout = QHBoxLayout(exiftool_row)
        exiftool_layout.setContentsMargins(0, 0, 0, 0)
        detected = find_exiftool(config.exiftool_path or None)
        version = exiftool_version(detected) if detected else "not found"
        self.exiftool_label = QLabel(f"{detected or tr('Not found')} ({tr('version')} {version})")
        self.exiftool_label.setObjectName("hint")
        self.exiftool_label.setWordWrap(True)
        locate = QPushButton(tr("Locate…"))
        locate.setObjectName("secondary")
        locate.clicked.connect(self._locate_exiftool)
        auto = QPushButton(tr("Auto-detect"))
        auto.setObjectName("secondary")
        auto.clicked.connect(self._auto_exiftool)
        exiftool_layout.addWidget(self.exiftool_label, 1)
        exiftool_layout.addWidget(locate)
        exiftool_layout.addWidget(auto)
        if not detected:
            self.exiftool_label.setText(
                tr("exiftool was not found. Install it with:  {hint}", hint=install_hint())
            )

        # -- indexing -------------------------------------------------------
        self.workers = QSpinBox()
        self.workers.setRange(1, 16)
        self.workers.setValue(config.workers)
        self.workers.setToolTip(tr("How many exiftool processes to read files with"))
        self.batch = QSpinBox()
        self.batch.setRange(100, 4000)
        self.batch.setSingleStep(100)
        self.batch.setValue(config.batch_size)
        self.batch.setToolTip(tr("Files read per batch; larger is slightly faster"))

        self.include_no_date = QRadioButton(tr("Use the file date when a photo has no EXIF date"))
        self.include_no_date.setChecked(config.include_no_date)

        self.language_box = QComboBox()
        # Empty data means "follow the OS". Without this entry a fresh install
        # silently pinned the interface to the first language in the list
        # instead of matching the machine.
        self.language_box.addItem(tr("Match the system"), "")
        for code, name in languages().items():
            self.language_box.addItem(name, code)
        index = self.language_box.findData(config.language)
        self.language_box.setCurrentIndex(index if index >= 0 else 0)

        form = QFormLayout()
        form.setSpacing(10)
        form.setHorizontalSpacing(16)
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        # One width for every control. Letting each fill the dialog made a
        # four-character value ("Dark") sit in a 410px box next to a paragraph
        # of helper text, which reads as three different layouts.
        for box in (self.language_box, self.theme_box, self.cache_box):
            box.setFixedWidth(FORM_FIELD_WIDTH)
            box.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        for box in (self.workers, self.batch):
            box.setFixedWidth(FORM_NUMBER_WIDTH)
            box.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        form.addRow(tr("Language"), self.language_box)
        form.addRow(tr("Appearance"), self.theme_box)
        form.addRow(tr("Statistics cache"), self.cache_box)
        form.addRow("", self.custom_row)
        form.addRow("exiftool", exiftool_row)
        form.addRow(tr("Read files in parallel"), self.workers)
        form.addRow(tr("Batch size"), self.batch)
        form.addRow("", self.include_no_date)

        self.restore = QPushButton(tr("Restore defaults"))
        self.restore.setObjectName("linkButton")
        self.restore.setCursor(Qt.PointingHandCursor)
        self.restore.clicked.connect(self._restore_defaults)
        # Left-aligned with the fields above, not floating in the middle.
        form.addRow("", self.restore)
        layout.addLayout(form)

        # A sentence explaining the cache does not belong in the 250px field
        # column, where it wrapped to five short lines. Full width, under the
        # fields it describes.
        layout.addWidget(self.cache_note)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText(tr("Save"))
        buttons.button(QDialogButtonBox.Ok).setObjectName("primary")
        buttons.button(QDialogButtonBox.Cancel).setText(tr("Cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._update_cache_note()

    # -- helpers -----------------------------------------------------------
    def _on_cache_mode(self) -> None:
        self.custom_row.setVisible(self.cache_box.currentData() == CACHE_CUSTOM)
        self._update_cache_note()

    def _update_cache_note(self) -> None:
        mode = self.cache_box.currentData()
        if mode == CACHE_NEXT_TO_PHOTOS:
            self.cache_note.setText(
                tr("The database is written inside the photo folder and stores paths relative "
                   "to it, so the whole library can be copied to another computer and will "
                   "open straight away.")
            )
        elif mode == CACHE_LOCAL:
            self.cache_note.setText(
                tr("Kept outside the photo folder. Use this for read-only drives or network "
                   "shares, where a portable database would not work.")
            )
        else:
            self.cache_note.setText(tr("Store the database in the folder you choose."))

    def _restore_defaults(self) -> None:
        """Put every field back to its shipped value, without saving yet.

        The user can still cancel: the widgets change now, the stored settings
        only change when OK is pressed.
        """
        self.config.reset_defaults()
        self._refresh_fields()

    def _refresh_fields(self) -> None:
        """Mirror the configuration back onto the controls."""
        def select(box, value):
            index = box.findData(value)
            box.setCurrentIndex(index if index >= 0 else 0)

        select(self.theme_box, self.config.theme_name)
        select(self.cache_box, self.config.cache_mode)
        select(self.language_box, self.config.language)
        self.custom_path.setText(self.config.cache_custom_path or "—")
        self.workers.setValue(self.config.workers)
        self.batch.setValue(self.config.batch_size)
        self.include_no_date.setChecked(self.config.include_no_date)
        detected = find_exiftool(self.config.exiftool_path or None)
        if detected:
            self.exiftool_label.setText(
                f"{detected} ({tr('version')} {exiftool_version(detected)})"
            )
        else:
            self.exiftool_label.setText(
                tr("exiftool was not found. Install it with:  {hint}",
                   hint=install_hint())
            )
        self._on_cache_mode()

    def _choose_custom(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, tr("Choose a cache folder"))
        if folder:
            self.custom_path.setText(folder)

    def _locate_exiftool(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, tr("Locate exiftool"), "", "exiftool (exiftool exiftool.exe);;All files (*)"
        )
        if path:
            self.config.set_exiftool_path(path)
            self.exiftool_label.setText(
                f"{path} ({tr('version')} {exiftool_version(path)})"
            )

    def _auto_exiftool(self) -> None:
        found = find_exiftool()
        self.config.set_exiftool_path(found)
        self.exiftool_label.setText(
            f"{found} ({tr('version')} {exiftool_version(found)})" if found
            else tr("Not found in PATH")
        )

    # -- result ------------------------------------------------------------
    def apply_to_config(self) -> None:
        self.config.set_theme(self.theme_box.currentData())
        self.config.set_cache(self.cache_box.currentData(), self.custom_path.text())
        self.config.set_indexing(self.workers.value(), self.batch.value())
        self.config.set_include_no_date(self.include_no_date.isChecked())
        self.config.set_language(self.language_box.currentData())
        self.config.sync()

    def cache_path_preview(self) -> Path:
        return self.config.db_path(Path(self.custom_path.text() or "~").expanduser())
