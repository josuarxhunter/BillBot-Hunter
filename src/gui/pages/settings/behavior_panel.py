from qfluentwidgets import BodyLabel
from qfluentwidgets.components.widgets.check_box import CheckBox

from src.controller.settings import SettingsService
from src.core.config import BehaviorSettings, GlobalSettings
from src.gui.pages.settings.settings_panel import SettingsPanel
from utils.language import GameLanguage
from src.gui.i18n import tr

BEHAVIOR_LABELS = {
    "do_fighter": "Automatic combat",
    "do_sale_hotel": "Marketplace sales",
    "do_craft": "Automatic crafting",
    "do_use_guild_chest": "Use guild chest",
    "do_dungeon": "Donjons",
    "do_idle": "Breaks during sessions",
    "enable_auto_equipment_market_purchases": "Allow equipment purchases",
    "enable_auto_ogrine_subscriptions": "Allow Ogrine subscriptions",
    "enable_auto_paysafecard_subscriptions": "Allow Paysafecard subscriptions",
}


class BehaviorSettingsPanel(SettingsPanel):
    def __init__(self) -> None:
        super().__init__(
            tr(
                "Behaviors apply the next time the bot starts manually or on schedule. "
                "Account automation applies to the next operation; the current one finishes normally."
            )
        )
        self.language = self.combo(tr("Language"), [tr("Current (bot interface / French game)"), "Español"])
        language_note = BodyLabel(
            tr("Restart BillBot to apply the interface language. Dofus uses it the next time it launches."),
            self,
        )
        language_note.setWordWrap(True)
        self.form.addRow(language_note)
        self.checks: dict[str, CheckBox] = {}
        for name, label in BEHAVIOR_LABELS.items():
            check = CheckBox(tr(label), self)
            self.form.addRow(check)
            self.checks[name] = check
        self.automation = CheckBox(tr("Automatically create and authenticate accounts"), self)
        self.form.addRow(self.automation)

    def reload(self) -> None:
        def render(settings: GlobalSettings) -> None:
            self.language.setCurrentIndex(1 if settings.language == "es" else 0)
            for name, check in self.checks.items():
                check.setChecked(getattr(settings.behaviors, name))
            self.automation.setChecked(settings.enable_account_automation)

        self.perform(SettingsService().get, render)

    def save(self) -> None:
        behaviors = BehaviorSettings.model_validate(
            {name: check.isChecked() for name, check in self.checks.items()}
        )
        automation = self.automation.isChecked()
        language: GameLanguage = "es" if self.language.currentIndex() == 1 else "fr"

        self.perform(
            lambda: SettingsService().update_behaviors(behaviors, automation, language=language),
            lambda _: self.reload(),
        )
