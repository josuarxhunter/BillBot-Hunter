from typing import cast

from PyQt6.QtCore import Qt, pyqtSlot
from PyQt6.QtWidgets import QFormLayout, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, ComboBox, PushButton

from DBDofusUnity.dofus_unity_reader.data_center.data_reader import DataReader
from src.controller.settings import SettingsService
from src.core.config import ConfigurableAutoSettings, RouteFailureAction
from src.core.signals.bot_signals import BotSignals, FarmDecision
from src.gui.game_names import game_names
from src.gui.i18n import tr
from src.utils.runtime_support import RuntimeSetupError, error_message


class ConfigurableAutoPanel(QWidget):
    def __init__(self, account_id: int, signals: BotSignals, parent: QWidget) -> None:
        super().__init__(parent)
        self.account_id = account_id
        self._decision: FarmDecision | None = None
        self._running = False
        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)
        self.area = ComboBox(self)
        self.subarea = ComboBox(self)
        self.failure = ComboBox(self)
        form.addRow(BodyLabel(tr("Area"), self), self.area)
        form.addRow(BodyLabel(tr("Subarea"), self), self.subarea)
        form.addRow(BodyLabel(tr("If the route fails or resources run out"), self), self.failure)

        self.area.addItem(tr("Choose automatically"))
        names = game_names()
        for area in sorted(DataReader().area_by_id.values(), key=lambda area: names.get(area.nameId, "")):
            self.area.addItem(names.get(area.nameId, str(area.id)), userData=area.id)
        self.area.currentIndexChanged.connect(self._update_subareas)

        self.failure.addItem(tr("Stop"), userData=RouteFailureAction.STOP)
        self.failure.addItem(tr("Wait and retry"), userData=RouteFailureAction.WAIT)
        self.failure.addItem(tr("Look for another zone"), userData=RouteFailureAction.CHANGE_AREA)

        self.save_button = PushButton(tr("Save account preferences"), self)
        self.save_button.clicked.connect(self.save)
        form.addRow(self.save_button)
        self.feedback = BodyLabel("", self)
        self.feedback.setWordWrap(True)
        form.addRow(self.feedback)

        self.phase = BodyLabel("", self)
        self.phase.setWordWrap(True)
        self.phase.hide()
        layout.addWidget(self.phase)

        self.summary = BodyLabel(tr("Decisions appear here when the activity starts."), self)
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

        preferences = SettingsService().configurable_auto(account_id)
        self.area.setCurrentIndex(max(0, self.area.findData(preferences.area_id)))
        self._update_subareas()
        self.subarea.setCurrentIndex(max(0, self.subarea.findData(preferences.sub_area_id)))
        self.failure.setCurrentIndex(self.failure.findData(preferences.on_route_failure))

        signals.configurable_auto_decision.connect(self.show_decision)
        signals.automation_status_changed.connect(self.show_phase)

    @pyqtSlot()
    def _update_subareas(self) -> None:
        area_id = cast(int | None, self.area.currentData())
        self.subarea.clear()
        self.subarea.addItem(tr("Any subarea"))
        self.subarea.setEnabled(area_id is not None)
        if area_id is None:
            return
        reader = DataReader()
        names = game_names()
        subareas = (
            reader.sub_area_by_id[subarea_id]
            for subarea_id in reader.sub_areas_by_area_id.get(area_id, set())
        )
        for subarea in sorted(subareas, key=lambda subarea: names.get(subarea.nameId, "")):
            self.subarea.addItem(names.get(subarea.nameId, str(subarea.id)), userData=subarea.id)

    def set_running(self, running: bool) -> None:
        self._running = running
        self.show_phase("")
        self.area.setEnabled(not running)
        self.subarea.setEnabled(not running and self.area.currentData() is not None)
        self.failure.setEnabled(not running)
        self.save_button.setEnabled(not running)

    @pyqtSlot()
    def save(self) -> ConfigurableAutoSettings | None:
        preferences = ConfigurableAutoSettings(
            area_id=self.area.currentData(),
            sub_area_id=self.subarea.currentData(),
            on_route_failure=self.failure.currentData(),
        )
        try:
            service = SettingsService()
            if service.configurable_auto(self.account_id) != preferences:
                service.update_configurable_auto(self.account_id, preferences)
        except (RuntimeSetupError, OSError) as error:
            self.feedback.setText(tr(error_message(error)))
            return None
        self.feedback.setText(tr("Preferences saved for this account."))
        return preferences

    @pyqtSlot(str)
    def show_phase(self, status: str) -> None:
        self.phase.setText(tr(status))
        self.phase.setVisible(
            self._running
            and bool(status)
            and self._decision is not None
            and self._decision.activity in ("Harvesting", "Combat")
        )

    @pyqtSlot(object)
    def show_decision(self, decision: FarmDecision) -> None:
        self._decision = decision
        self.show_phase("")
        reader = DataReader()
        names = game_names()
        area = reader.area_by_id.get(decision.area_id) if decision.area_id is not None else None
        subarea = (
            reader.sub_area_by_id.get(decision.sub_area_id) if decision.sub_area_id is not None else None
        )
        zone = names.get(area.nameId, str(area.id)) if area is not None else tr("No zone selected")
        if subarea is not None:
            zone += " / " + names.get(subarea.nameId, str(subarea.id))
        self.summary.setText(
            tr(
                "Activity: {activity}\nZone: {zone}\nReason: {reason}\nNext: {next_action}",
                activity=tr(decision.activity),
                zone=zone,
                reason=tr(decision.reason),
                next_action=tr(decision.next_action),
            )
        )

    def show_stopped(self) -> None:
        decision = self._decision
        if decision is None or decision.activity != "Stopped":
            self.show_decision(
                FarmDecision(
                    "Stopped",
                    "The activity was stopped.",
                    "Press Play to start again.",
                    decision.area_id if decision else None,
                    decision.sub_area_id if decision else None,
                )
            )
