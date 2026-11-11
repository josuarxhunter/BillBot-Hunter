from dataclasses import dataclass

from PyQt6.QtCore import QObject, pyqtSignal


@dataclass(frozen=True)
class FarmDecision:
    activity: str
    reason: str
    next_action: str
    area_id: int | None = None
    sub_area_id: int | None = None
    priority_resource_ids: tuple[int, ...] = ()
    travel_seconds: float | None = None
    travel_budget: int | None = None
    waypoint_map_id: int | None = None


class BotSignals(QObject):
    play_fighter = pyqtSignal(object, object)
    play_configurable_auto = pyqtSignal(object)
    play_dungeons = pyqtSignal(object)
    dungeon_status_changed = pyqtSignal(str)
    configurable_auto_decision = pyqtSignal(object)
    play_crafter = pyqtSignal(object)
    play_usable_behavior = pyqtSignal(str)
    play = pyqtSignal(bool)
    stop = pyqtSignal()
    disconnect_runtime = pyqtSignal()
    automation_status_changed = pyqtSignal(str)
