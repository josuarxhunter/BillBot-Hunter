from typing import cast

from PyQt6.QtCore import Qt, pyqtSlot
from PyQt6.QtWidgets import QFormLayout, QVBoxLayout, QWidget, QListWidgetItem, QStackedWidget
from qfluentwidgets import BodyLabel, ComboBox, PushButton, LineEdit, SegmentedWidget, ListWidget
from qfluentwidgets.components.widgets.spin_box import SpinBox, DoubleSpinBox
from qfluentwidgets.components.widgets.check_box import CheckBox
from pydantic import ValidationError

from DBDofusUnity.dofus_unity_reader.data_center.data_reader import DataReader
from src.controller.settings import SettingsService
from src.core.config import ConfigurableAutoSettings, RouteFailureAction, HarvestGoal
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

        preferences = SettingsService().configurable_auto(account_id)
        self.goal = ComboBox(self)
        for goal, label in (
            (HarvestGoal.BALANCED, "Balanced"),
            (HarvestGoal.PROFIT, "Kamas"),
            (HarvestGoal.EXPERIENCE, "Profession progression"),
            (HarvestGoal.TARGETS, "Selected resources"),
        ):
            self.goal.addItem(tr(label), userData=goal)
        self.goal.setCurrentIndex(self.goal.findData(preferences.goal))
        form.addRow(BodyLabel(tr("Harvesting goal"), self), self.goal)
        note = BodyLabel(
            tr("Travel times and resource values are estimates. Changes apply on the next start."), self
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        self.section_nav = SegmentedWidget(self)
        layout.addWidget(self.section_nav)
        self.sections = QStackedWidget(self)
        layout.addWidget(self.sections)
        self.number_inputs: dict[str, SpinBox | DoubleSpinBox] = {}
        self.check_inputs: dict[str, CheckBox] = {}
        groups: dict[str, tuple[tuple[str, str], ...]] = {
            "Zones and productivity": (
                ("rotation_minutes", "Reevaluate zone every (minutes)"),
                ("minimum_stay_minutes", "Minimum stay (minutes)"),
                ("minimum_improvement_percent", "Minimum improvement to move (%)"),
                ("candidate_quality_percent", "Minimum candidate quality (%)"),
                ("empty_map_limit", "Consecutive empty maps before failure"),
                ("productivity_window_minutes", "Productivity window (minutes)"),
                ("minimum_collections_per_minute", "Minimum collections per minute"),
                ("retry_seconds", "Retry delay (seconds)"),
                ("zone_cooldown_minutes", "Failed zone cooldown (minutes)"),
            ),
            "Transport": (
                ("reserve_kamas", "Protected kamas reserve"),
                ("maximum_zaap_cost", "Maximum cost per zaap"),
                ("seconds_per_map", "Estimated seconds per map"),
                ("teleport_seconds", "Estimated teleport seconds"),
                ("travel_value_per_minute", "Value of travel time (kamas/minute)"),
                ("discover_zaaps", "Discover new zaaps on the way"),
            ),
            "Combat": (
                ("occasional_combat", "Occasional combat while harvesting"),
                ("combat_interval_minutes", "Combat interval (minutes)"),
                ("recovery_combat", "Fight to recover kamas for bank access"),
                ("recovery_combat_minutes", "Maximum recovery combat time (minutes)"),
            ),
        }
        schema = ConfigurableAutoSettings.model_json_schema()["properties"]
        for title, fields in groups.items():
            section = QWidget(self)
            section_form = QFormLayout(section)
            for name, label in fields:
                value = getattr(preferences, name)
                if isinstance(value, bool):
                    check = CheckBox(tr(label), section)
                    check.setChecked(value)
                    self.check_inputs[name] = check
                    section_form.addRow(check)
                else:
                    control = DoubleSpinBox(section) if schema[name]["type"] == "number" else SpinBox(section)
                    control.setRange(schema[name]["minimum"], schema[name]["maximum"])
                    control.setValue(value)
                    self.number_inputs[name] = control
                    section_form.addRow(BodyLabel(tr(label), section), control)
            self._add_section(section, title)

        resource_section = QWidget(self)
        resource_form = QFormLayout(resource_section)
        resource_note = BodyLabel(
            tr(
                "Resource targets apply only to the Selected resources goal. Progression and prices are estimates."
            ),
            self,
        )
        resource_note.setWordWrap(True)
        resource_form.addRow(resource_note)
        price_age = SpinBox(resource_section)
        price_age.setRange(1, 8760)
        price_age.setValue(preferences.price_half_life_hours)
        self.number_inputs["price_half_life_hours"] = price_age
        resource_form.addRow(BodyLabel(tr("Price confidence halves after (hours)"), self), price_age)
        self.search = LineEdit(resource_section)
        self.search.setPlaceholderText(tr("Search resources"))
        self.resources = ListWidget(resource_section)
        self.resources.setMinimumHeight(160)
        reader = DataReader()
        resource_ids = reader.gathered_item_ids & reader.item_by_id.keys()
        for gid in sorted(resource_ids, key=lambda gid: names.get(reader.item_by_id[gid].nameId, "")):
            item = reader.item_by_id[gid]
            row = QListWidgetItem(names.get(item.nameId, str(gid)), self.resources)
            row.setData(Qt.ItemDataRole.UserRole, gid)
            row.setFlags(row.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            row.setCheckState(
                Qt.CheckState.Checked if gid in preferences.target_resource_ids else Qt.CheckState.Unchecked
            )
        self.search.textChanged.connect(self._filter_resources)
        resource_form.addRow(self.search)
        resource_form.addRow(self.resources)
        self.quantity = SpinBox(resource_section)
        self.quantity.setRange(0, 1_000_000)
        self.quantity.setValue(preferences.target_quantity)
        resource_form.addRow(
            BodyLabel(tr("Target per resource, bank + inventory (0: unlimited)"), self), self.quantity
        )
        self._add_section(resource_section, "Target resources")
        self.section_nav.setCurrentItem("Zones and productivity")

        self.save_button = PushButton(tr("Save account preferences"), self)
        self.save_button.clicked.connect(self.save)
        layout.addWidget(self.save_button)
        self.feedback = BodyLabel("", self)
        self.feedback.setWordWrap(True)
        layout.addWidget(self.feedback)

        self.status_widget = QWidget(parent)
        status_layout = QVBoxLayout(self.status_widget)
        self.phase = BodyLabel("", self)
        self.phase.setWordWrap(True)
        self.phase.hide()
        status_layout.addWidget(self.phase)

        self.summary = BodyLabel(tr("Decisions appear here when the activity starts."), self)
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        self.summary.setWordWrap(True)
        status_layout.addWidget(self.summary)

        self.area.setCurrentIndex(max(0, self.area.findData(preferences.area_id)))
        self._update_subareas()
        self.subarea.setCurrentIndex(max(0, self.subarea.findData(preferences.sub_area_id)))
        self.failure.setCurrentIndex(self.failure.findData(preferences.on_route_failure))

        signals.configurable_auto_decision.connect(self.show_decision)
        signals.automation_status_changed.connect(self.show_phase)

    def _add_section(self, section: QWidget, title: str) -> None:
        self.sections.addWidget(section)
        self.section_nav.addItem(title, tr(title), onClick=lambda: self.sections.setCurrentWidget(section))

    @pyqtSlot(str)
    def _filter_resources(self, text: str) -> None:
        for index in range(self.resources.count()):
            row = self.resources.item(index)
            if row is not None:
                row.setHidden(text.casefold() not in row.text().casefold())

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
        self.sections.setEnabled(not running)
        self.goal.setEnabled(not running)

    @pyqtSlot()
    def save(self) -> ConfigurableAutoSettings | None:
        try:
            preferences = ConfigurableAutoSettings.model_validate(
                {
                    "area_id": self.area.currentData(),
                    "sub_area_id": self.subarea.currentData(),
                    "on_route_failure": self.failure.currentData(),
                    "goal": self.goal.currentData(),
                    "target_resource_ids": tuple(
                        row.data(Qt.ItemDataRole.UserRole)
                        for index in range(self.resources.count())
                        if (row := self.resources.item(index)) is not None
                        and row.checkState() == Qt.CheckState.Checked
                    ),
                    "target_quantity": self.quantity.value(),
                    **{name: control.value() for name, control in self.number_inputs.items()},
                    **{name: control.isChecked() for name, control in self.check_inputs.items()},
                }
            )
            service = SettingsService()
            if service.configurable_auto(self.account_id) != preferences:
                service.update_configurable_auto(self.account_id, preferences)
        except (RuntimeSetupError, OSError) as error:
            self.feedback.setText(tr(error_message(error)))
            return None
        except ValidationError as error:
            self.feedback.setText(
                "\n".join(tr(entry["msg"].removeprefix("Value error, ")) for entry in error.errors())
            )
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
        text = tr(
            "Activity: {activity}\nZone: {zone}\nReason: {reason}\nNext: {next_action}",
            activity=tr(decision.activity),
            zone=zone,
            reason=tr(decision.reason),
            next_action=tr(decision.next_action),
        )
        if decision.priority_resource_ids:
            resources = ", ".join(
                names.get(reader.item_by_id[gid].nameId, str(gid))
                for gid in decision.priority_resource_ids
                if gid in reader.item_by_id
            )
            text += "\n" + tr("Priority resources: {resources}", resources=resources)
        if decision.travel_seconds is not None:
            waypoint = (
                reader.map_info_by_map_id.get(decision.waypoint_map_id)
                if decision.waypoint_map_id is not None
                else None
            )
            transport = (
                tr("Walking")
                if waypoint is None
                else tr("Zaap at [{x}, {y}]", x=waypoint.posX, y=waypoint.posY)
            )
            text += "\n" + tr(
                "Travel: {transport}; estimated {seconds:.0f}s; budget up to {cost} kamas.",
                transport=transport,
                seconds=decision.travel_seconds,
                cost=decision.travel_budget,
            )
        self.summary.setText(text)

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
