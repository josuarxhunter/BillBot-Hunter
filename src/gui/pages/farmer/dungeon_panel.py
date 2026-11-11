from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFormLayout, QHBoxLayout, QListWidgetItem, QVBoxLayout, QWidget
from pydantic import ValidationError
from qfluentwidgets import BodyLabel, ComboBox, ListWidget, PushButton
from qfluentwidgets.components.widgets.check_box import CheckBox

from src.controller.settings import SettingsService
from src.core.config import DungeonSettings
from src.core.engine.dungeons.dungeon_info import ALL_DUNGEONS
from src.gui.game_names import game_names
from src.gui.i18n import tr
from src.utils.runtime_support import RuntimeSetupError, error_message


class DungeonPanel(QWidget):
    def __init__(self, account_id: int, parent: QWidget) -> None:
        super().__init__(parent)
        self.account_id = account_id
        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)
        self.dungeon = ComboBox(self)
        self.dungeon.addItem(tr("Choose automatically"), userData=None)
        names = game_names()
        self._names_by_id = {
            info.dungeon.id: tr(
                "{name} (level {level})",
                name=names.get(info.dungeon.nameId, info.name),
                level=info.dungeon.optimalPlayerLevel,
            )
            for info in ALL_DUNGEONS
        }
        self._blocked_by_id = {
            info.dungeon.id: info.blocked_reason for info in ALL_DUNGEONS if info.blocked_reason is not None
        }
        self._access_notes = {
            info.dungeon.id: info.access_note for info in ALL_DUNGEONS if info.access_note is not None
        }
        for dungeon_id, name in self._names_by_id.items():
            label = (
                tr("{name} — requires two characters", name=name)
                if dungeon_id in self._blocked_by_id
                else name
            )
            self.dungeon.addItem(label, userData=dungeon_id)
        form.addRow(BodyLabel(tr("Dungeon"), self), self.dungeon)
        self.follow_sequence = CheckBox(tr("Follow a dungeon sequence"), self)
        layout.addWidget(self.follow_sequence)
        note = BodyLabel(
            tr(
                "When enabled, run the list once in order instead of the selected dungeon. Stop if a dungeon fails or neither a key nor keyring access is available."
            ),
            self,
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        self.sequence = ListWidget(self)
        self.sequence.setMinimumHeight(150)
        layout.addWidget(self.sequence)
        buttons = QHBoxLayout()
        layout.addLayout(buttons)
        self.sequence_buttons: list[PushButton] = []
        for label, callback in (
            ("Add selected dungeon", self.add_selected),
            ("Remove", self.remove_selected),
            ("Move up", self.move_up),
            ("Move down", self.move_down),
        ):
            button = PushButton(tr(label), self)
            button.clicked.connect(callback)
            buttons.addWidget(button)
            self.sequence_buttons.append(button)
        self.save_button = PushButton(tr("Save preferences"), self)
        self.save_button.clicked.connect(self.save)
        layout.addWidget(self.save_button)
        self.feedback = BodyLabel("", self)
        self.feedback.setWordWrap(True)
        layout.addWidget(self.feedback)
        self.result = BodyLabel("", self)
        self.result.setTextFormat(Qt.TextFormat.PlainText)
        self.result.setWordWrap(True)
        layout.addWidget(self.result)
        self.dungeon.currentIndexChanged.connect(self.show_selected_requirement)
        layout.addStretch()

        preferences = SettingsService().dungeons(account_id)
        index = self.dungeon.findData(preferences.dungeon_id)
        if index < 0:
            self.dungeon.addItem(
                tr("Unsupported dungeon ({id})", id=preferences.dungeon_id), userData=preferences.dungeon_id
            )
            index = self.dungeon.count() - 1
        self.dungeon.setCurrentIndex(index)
        for dungeon_id in preferences.sequence:
            self._append_dungeon(dungeon_id)
        self.follow_sequence.setChecked(preferences.follow_sequence)
        self.follow_sequence.toggled.connect(self._update_sequence_controls)
        self._update_sequence_controls()
        self.show_selected_requirement()

    def show_result(self, status: str) -> None:
        self.result.setText(tr(status))

    def show_selected_requirement(self) -> None:
        dungeon_id = self.dungeon.currentData()
        reason = self._blocked_by_id.get(dungeon_id) or self._access_notes.get(dungeon_id)
        self.feedback.setText(tr(reason) if reason is not None else "")

    def _append_dungeon(self, dungeon_id: int) -> None:
        row = QListWidgetItem(
            self._names_by_id.get(dungeon_id, tr("Unsupported dungeon ({id})", id=dungeon_id))
        )
        row.setData(Qt.ItemDataRole.UserRole, dungeon_id)
        self.sequence.addItem(row)

    def _update_sequence_controls(self) -> None:
        enabled = self.follow_sequence.isChecked() and self.follow_sequence.isEnabled()
        self.sequence.setEnabled(enabled)
        for button in self.sequence_buttons:
            button.setEnabled(enabled)

    def add_selected(self) -> None:
        dungeon_id = self.dungeon.currentData()
        if dungeon_id is None:
            self.feedback.setText(tr("Select a dungeon before adding it to the sequence."))
            return
        if dungeon_id in self._blocked_by_id:
            self.show_selected_requirement()
            return
        self._append_dungeon(dungeon_id)
        self.sequence.setCurrentRow(self.sequence.count() - 1)

    def remove_selected(self) -> None:
        row = self.sequence.currentRow()
        if row >= 0:
            self.sequence.takeItem(row)

    def move_up(self) -> None:
        self._move_selected(-1)

    def move_down(self) -> None:
        self._move_selected(1)

    def _move_selected(self, offset: int) -> None:
        row = self.sequence.currentRow()
        target = row + offset
        if row >= 0 and 0 <= target < self.sequence.count():
            item = self.sequence.takeItem(row)
            if item is not None:
                self.sequence.insertItem(target, item)
                self.sequence.setCurrentRow(target)

    def set_running(self, running: bool) -> None:
        self.dungeon.setEnabled(not running)
        self.follow_sequence.setEnabled(not running)
        self.save_button.setEnabled(not running)
        self._update_sequence_controls()

    def save(self) -> DungeonSettings | None:
        try:
            preferences = DungeonSettings.model_validate(
                {
                    "dungeon_id": self.dungeon.currentData(),
                    "follow_sequence": self.follow_sequence.isChecked(),
                    "sequence": tuple(
                        item.data(Qt.ItemDataRole.UserRole)
                        for index in range(self.sequence.count())
                        if (item := self.sequence.item(index)) is not None
                    ),
                }
            )
            chosen = preferences.sequence if preferences.follow_sequence else (preferences.dungeon_id,)
            if any(dungeon_id is not None and dungeon_id not in self._names_by_id for dungeon_id in chosen):
                self.feedback.setText(tr("The selected dungeon is not supported."))
                return None
            for dungeon_id in chosen:
                if dungeon_id is None:
                    continue
                reason = self._blocked_by_id.get(dungeon_id)
                if reason is not None:
                    self.feedback.setText(tr(reason))
                    return None
            SettingsService().update_dungeons(self.account_id, preferences)
        except ValidationError as error:
            self.feedback.setText(
                "\n".join(tr(entry["msg"].removeprefix("Value error, ")) for entry in error.errors())
            )
            return None
        except (RuntimeSetupError, OSError) as error:
            self.feedback.setText(tr(error_message(error)))
            return None
        self.feedback.setText(tr("Preferences saved for this account."))
        return preferences
