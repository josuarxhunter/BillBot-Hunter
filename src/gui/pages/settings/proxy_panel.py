from ankama_launcher_emulator.controller.proxy import ProxyController
from ankama_launcher_emulator.interfaces.schedule_profile import PersistedProxy, ProxyConfig
from PyQt6.QtCore import pyqtSignal
from qfluentwidgets import BodyLabel

from src.controller.settings_deletion import delete_proxy
from src.gui.pages.settings.settings_panel import SettingsPanel
from src.gui.i18n import tr


class ProxySettingsPanel(SettingsPanel):
    changed = pyqtSignal()

    def __init__(self) -> None:
        super().__init__(
            tr("Proxies are assigned to schedule profiles. Active connections keep their proxy until they reconnect.")
        )
        self.entries: dict[str, PersistedProxy] = {}
        self.selection = self.overview([tr("Identifier"), tr("Host"), tr("HTTP port"), tr("SOCKS port"), tr("Status")], tr("New proxy…"))
        self.identifier = self.line(tr("Identifier"))
        self.host = self.line(tr("Host"))
        self.http_port = self.line(tr("Port HTTP"))
        self.socks_port = self.line(tr("Port SOCKS"))
        self.username = self.line(tr("Username"))
        self.password = self.line(tr("Password"))
        self.state = BodyLabel("", self)
        self.form.addRow(BodyLabel(tr("Status"), self), self.state)
        self.selection.selected.connect(self.select)
        self.bind_deletion(self.selection, delete_proxy, self.changed.emit)

    def reload(self) -> None:
        def render(entries: dict[str, PersistedProxy]) -> None:
            self.entries = entries
            self.selection.set_rows([
                (identifier, (identifier, proxy.host, str(proxy.http_port), str(proxy.socks_port),
                              tr("Rejected") if proxy.rejected else tr("Available")))
                for identifier, proxy in sorted(entries.items())
            ])
            self.select()

        self.perform(ProxyController().get_all, render)

    def select(self) -> None:
        identifier = self.selection.selected_key or ""
        proxy = self.entries.get(identifier)
        self.identifier.setText(identifier)
        self.identifier.setReadOnly(proxy is not None)
        self.host.setText(proxy.host if proxy else "")
        self.http_port.setText(str(proxy.http_port) if proxy else "")
        self.socks_port.setText(str(proxy.socks_port) if proxy else "")
        self.username.setText(proxy.username if proxy else "")
        self.password.setText(proxy.password if proxy else "")
        self.state.setText(tr("Rejected") if proxy and proxy.rejected else tr("Available"))

    def save(self) -> None:
        try:
            config = ProxyConfig(
                host=self.host.text().strip(),
                http_port=int(self.http_port.text()),
                socks_port=int(self.socks_port.text()),
                username=self.username.text(),
                password=self.password.text(),
            )
        except ValueError:
            self.invalid()
            return
        identifier = self.identifier.text().strip()
        create = self.selection.selected_key is None

        def done(_: None) -> None:
            self.changed.emit()
            self.reload()

        self.perform(lambda: ProxyController().save_config(identifier, config, create=create), done)
