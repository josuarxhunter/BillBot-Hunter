from typing import Literal, cast

from ankama_launcher_emulator.controller.mail_account import MailAccountController
from ankama_launcher_emulator.interfaces.mail_account import (
    ImapAccountConfig,
    MailAccountConfig,
    MailAccountEntry,
    ManualAccountConfig,
    SmailProAccountConfig,
)
from qfluentwidgets import BodyLabel

from src.gui.pages.settings.settings_panel import SettingsPanel
from src.gui.i18n import tr


class MailSettingsPanel(SettingsPanel):
    def __init__(self) -> None:
        super().__init__(
            tr(
                "Add an available mailbox for automation. "
                "In manual mode, a dialog will request the confirmation code."
            )
        )
        self.entries: dict[str, MailAccountEntry] = {}
        self.selected_email: str | None = None
        self.selection = self.overview([tr("Email address"), tr("Provider"), tr("Status")], tr("New mailbox…"))
        self.email = self.line(tr("Adresse email"))
        self.provider = self.combo(tr("Type"), ["imap", "manual", "smailpro"])
        self.host = self.line(tr("IMAP server"))
        self.port = self.line(tr("Port IMAP"))
        self.username = self.line(tr("IMAP username"))
        self.password = self.line(tr("IMAP password"))
        self.api_key = self.line(tr("SmailPro key"))
        self.kind = self.combo(tr("Type SmailPro"), ["gmail", "outlook"])
        self.timestamp = self.line(tr("SmailPro creation timestamp"))
        self.state = BodyLabel("", self)
        self.form.addRow(BodyLabel(tr("Status"), self), self.state)
        self.selection.selected.connect(self.select)
        self.provider.currentIndexChanged.connect(self._provider_changed)

    def _provider_changed(self) -> None:
        for widget in (self.host, self.port, self.username, self.password):
            widget.setEnabled(self.provider.currentText() == "imap")
        for widget in (self.api_key, self.kind, self.timestamp):
            widget.setEnabled(self.provider.currentText() == "smailpro")

    def reload(self) -> None:
        def render(entries: dict[str, MailAccountEntry]) -> None:
            self.entries = entries
            self.selection.set_rows([
                (email, (email, entry.config.provider if entry.config else "—",
                         tr("Quarantined") if entry.bad_state else tr("Already used") if entry.is_used else tr("Available")))
                for email, entry in sorted(entries.items())
            ])
            self.select()

        self.perform(MailAccountController().get_all_entries, render)

    def select(self) -> None:
        email = self.selection.selected_key
        self.selected_email = email
        entry = (
            self.entries[email]
            if email
            else MailAccountEntry(config=ImapAccountConfig(host="", username="", password=""))
        )
        config = entry.config
        self.email.setText(email or "")
        self.email.setReadOnly(email is not None)
        self.provider.setCurrentText(config.provider if config else "manual")
        self.host.setText(config.host if isinstance(config, ImapAccountConfig) else "")
        self.port.setText(str(config.port) if isinstance(config, ImapAccountConfig) else "993")
        self.username.setText(config.username if isinstance(config, ImapAccountConfig) else "")
        self.password.setText(config.password if isinstance(config, ImapAccountConfig) else "")
        self.api_key.setText(config.api_key if isinstance(config, SmailProAccountConfig) else "")
        self.kind.setCurrentText(config.kind if isinstance(config, SmailProAccountConfig) else "gmail")
        self.timestamp.setText(str(config.timestamp) if isinstance(config, SmailProAccountConfig) else "")
        self.state.setText(
            tr("Quarantined") if entry.bad_state else tr("Already used") if entry.is_used else tr("Available")
        )
        self._provider_changed()

    def save(self) -> None:
        email = self.email.text().strip()
        config: MailAccountConfig
        try:
            match self.provider.currentText():
                case "imap":
                    config = ImapAccountConfig(
                        host=self.host.text().strip(),
                        port=int(self.port.text()),
                        username=self.username.text().strip(),
                        password=self.password.text(),
                    )
                case "smailpro":
                    config = SmailProAccountConfig(
                        api_key=self.api_key.text().strip(),
                        email=email,
                        kind=cast(Literal["gmail", "outlook"], self.kind.currentText()),
                        timestamp=int(self.timestamp.text()),
                    )
                case _:
                    config = ManualAccountConfig()
        except ValueError:
            self.invalid()
            return
        create = self.selected_email is None
        self.perform(
            lambda: MailAccountController().save_config(email, config, create=create), lambda _: self.reload()
        )
