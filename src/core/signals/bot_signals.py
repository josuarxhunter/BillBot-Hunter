from dataclasses import dataclass

from PyQt6.QtCore import QObject, pyqtSignal


@dataclass(frozen=True)
class FarmDecision:
    activity: str
    reason: str
    next_action: str
    area_id: int | None = None
    sub_area_id: int | None = None


class BotSignals(QObject):
    play_harvester = pyqtSignal(object, object)
    play_fighter = pyqtSignal(object, object)
    play_auto_bot = pyqtSignal()
    play_configurable_auto = pyqtSignal(object)
    configurable_auto_decision = pyqtSignal(object)
    play_crafter = pyqtSignal(object)
    play_usable_behavior = pyqtSignal(str)
    play = pyqtSignal(bool)
    stop = pyqtSignal()
    disconnect_runtime = pyqtSignal()
    automation_status_changed = pyqtSignal(str)
