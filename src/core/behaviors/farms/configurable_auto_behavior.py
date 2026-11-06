import random
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from DBDofusUnity.dofus_unity_reader.data_center.area_info import AreaInfo
from DBDofusUnity.dofus_unity_reader.data_center.data_reader import DataReader
from src.core.behaviors.behavior import BehaviorState
from src.core.behaviors.farms.auto_bot_behavior import AREA_CHOICE_LOCK, AutoBotBehavior
from src.core.behaviors.farms.harvest.multi_farming_behavior import MultiFarmingBehavior
from src.core.behaviors.movements.auto_trip.auto_trip_behavior import AutoTripErrorCode
from src.core.config import ConfigurableAutoSettings, RouteFailureAction, get_time_beween_areas
from src.core.engine.weights.weight_areas import get_harvesting_area_weights
from src.core.signals.bot_signals import BotSignals, FarmDecision
from src.core.states.area_state import CURRENT_AREAS_PLAYING_INFOS_BY_SERVER_AND_CHARACTER

EMPTY_MAP_LIMIT = 5
ROUTE_RETRY_SECONDS = 60


class RouteFailure(StrEnum):
    NO_RESOURCES = "No resources gathered after five consecutive maps."
    NO_ROUTE = "No usable route to or within the selected zone."
    NO_ZONE = "No eligible zone remains."


@dataclass
class ConfigurableFarmingBehavior(MultiFarmingBehavior):
    _empty_maps: int = field(init=False, default=0)
    _last_checked_map: int | None = field(init=False, default=None)

    def run(
        self,
        area_id: int | None,
        sub_area_id: int | None,
        is_stopped_at_new_map_condition: Callable[[], bool] | None = None,
        target_resource_item_ids: set[int] | None = None,
    ) -> None:
        self._empty_maps = 0
        self._last_checked_map = None
        super().run(area_id, sub_area_id, is_stopped_at_new_map_condition, target_resource_item_ids)

    def fight_on_map(self) -> None:
        self.report_status("Fighting a group of monsters…")
        super().fight_on_map()

    def on_full_pods(self) -> None:
        self.report_status("Handling the full inventory…")
        super().on_full_pods()

    def on_collect_behavior_finished(self, error_code: str | None) -> None:
        map_id = self.game_state.map.map_id
        if self.collect_behavior.completed_collections:
            self._empty_maps = 0
        elif error_code is None and map_id != self._last_checked_map:
            self._empty_maps += 1
        self._last_checked_map = map_id

        if self._empty_maps >= EMPTY_MAP_LIMIT:
            return self.finish(RouteFailure.NO_RESOURCES)
        super().on_collect_behavior_finished(error_code)


@dataclass
class ConfigurableAutoBehavior(AutoBotBehavior):
    bot_signals: BotSignals
    _preferences: ConfigurableAutoSettings = field(init=False, default_factory=ConfigurableAutoSettings)
    _failed_zones: set[tuple[int, int | None]] = field(
        init=False, default_factory=set[tuple[int, int | None]]
    )
    _selected_zone: AreaInfo | None = field(init=False, default=None)
    _registered_zone: tuple[tuple[int, int], AreaInfo] | None = field(init=False, default=None)

    def run(
        self,
        area_id: int | None = None,
        sub_area_id: int | None = None,
        *,
        preferences: ConfigurableAutoSettings | None = None,
    ) -> None:
        self._preferences = preferences or ConfigurableAutoSettings(area_id=area_id, sub_area_id=sub_area_id)
        self._failed_zones.clear()
        self._previous_area_info_played.clear()
        self._selected_zone = None
        self._publish("Preparing", "Configurable mode started.", "Check equipment and choose a zone.")
        super().run(self._preferences.area_id, self._preferences.sub_area_id)

    def _release_zone(self) -> None:
        with AREA_CHOICE_LOCK:
            if self._registered_zone is not None:
                key, zone = self._registered_zone
                if CURRENT_AREAS_PLAYING_INFOS_BY_SERVER_AND_CHARACTER.get(key) is zone:
                    del CURRENT_AREAS_PLAYING_INFOS_BY_SERVER_AND_CHARACTER[key]
                self._registered_zone = None

    def clear_behavior(self) -> None:
        self._release_zone()
        super().clear_behavior()

    def _publish(self, activity: str, reason: str, next_action: str) -> None:
        zone = self._selected_zone
        self.logger.info(
            "%s: %s Zone=%s/%s. Next: %s",
            activity,
            reason,
            zone.area_id if zone else None,
            zone.sub_area_id if zone else None,
            next_action,
        )
        self.bot_signals.configurable_auto_decision.emit(
            FarmDecision(
                activity,
                reason,
                next_action,
                zone.area_id if zone else None,
                zone.sub_area_id if zone else None,
            )
        )

    def _select_zone(self) -> tuple[AreaInfo | None, str]:
        area_id = self._preferences.area_id
        sub_area_id = self._preferences.sub_area_id
        if area_id is not None and not self._failed_zones:
            return AreaInfo(area_id=area_id, sub_area_id=sub_area_id), "Zone set in account preferences."

        candidates = {
            zone: weight
            for zone, weight in get_harvesting_area_weights(
                self.get_harvester_area_context(), self._previous_area_info_played
            ).items()
            if (zone.area_id, zone.sub_area_id) not in self._failed_zones
            and (zone.area_id, None) not in self._failed_zones
            and (
                zone.sub_area_id is not None
                or not any(failed_area == zone.area_id for failed_area, _ in self._failed_zones)
            )
        }
        if not candidates:
            return None, RouteFailure.NO_ZONE
        reason = (
            "Alternative zone after a route failure."
            if self._failed_zones
            else "Selected using the character's harvesting criteria."
        )
        return random.choices(list(candidates), weights=list(candidates.values()), k=1)[0], reason

    def _zone_has_maps(self, zone: AreaInfo) -> bool:
        reader = DataReader()
        if zone.area_id not in reader.area_by_id:
            return False
        if zone.sub_area_id is None and zone.area_id not in reader.sub_areas_by_area_id:
            return False
        if zone.sub_area_id is not None:
            subarea = reader.sub_area_by_id.get(zone.sub_area_id)
            if subarea is None or subarea.areaId != zone.area_id:
                return False
        return bool(
            self.multi_farming_behavior.random_farm_behavior.get_map_ids(zone.area_id, zone.sub_area_id)
        )

    def _start_harvesting_zone(self, zone: AreaInfo, reason: str) -> None:
        if not self._zone_has_maps(zone):
            return self._on_route_failure(RouteFailure.NO_ROUTE)
        self._publish("Harvesting", reason, "Follow the route and reevaluate the zone.")
        rotate_at = datetime.now() + get_time_beween_areas()
        self.multi_farming_behavior.start(
            area_id=zone.area_id,
            sub_area_id=zone.sub_area_id,
            is_stopped_at_new_map_condition=lambda: datetime.now() >= rotate_at,
            callback=self.on_multi_farming_behavior_finished,
            parent=self,
        )

    def _set_zone(self, zone: AreaInfo | None) -> None:
        self._selected_zone = zone
        if zone is not None:
            player = self.game_state.player
            key = player.server_id, player.character_id
            self._registered_zone = key, zone
            CURRENT_AREAS_PLAYING_INFOS_BY_SERVER_AND_CHARACTER[key] = zone
            self._previous_area_info_played.append(zone)

    def play_multi_farming(self) -> None:
        with AREA_CHOICE_LOCK:
            self._release_zone()
            zone, reason = self._select_zone()
            self._set_zone(zone)
        if zone is None:
            return self._on_route_failure(RouteFailure.NO_ZONE)
        self._start_harvesting_zone(zone, reason)

    def _retry_zone(self, zone: AreaInfo) -> None:
        with AREA_CHOICE_LOCK:
            self._set_zone(zone)
        self._start_harvesting_zone(zone, "Retrying the same zone after waiting.")

    def _on_route_failure(self, reason: RouteFailure) -> None:
        self._release_zone()
        zone = self._selected_zone
        action = self._preferences.on_route_failure
        if action is RouteFailureAction.WAIT and zone is not None:
            self._publish("Waiting", reason, "Retry the same zone in one minute.")
            return self.run_timer(ROUTE_RETRY_SECONDS, lambda: self._retry_zone(zone))
        if action is RouteFailureAction.WAIT and reason is RouteFailure.NO_ZONE:
            self._publish("Waiting", reason, "Look for a zone again in one minute.")
            return self.run_timer(ROUTE_RETRY_SECONDS, self.play_multi_farming)
        if action is RouteFailureAction.CHANGE_AREA and zone is not None:
            self._failed_zones.add((zone.area_id, zone.sub_area_id))
            self._publish("Changing zone", reason, "Look for another eligible zone.")
            return self.run_timer(0, self.play_multi_farming)
        self.finish(reason)

    def on_multi_farming_behavior_finished(self, error_code: str | None) -> None:
        if error_code == RouteFailure.NO_RESOURCES:
            return self._on_route_failure(RouteFailure.NO_RESOURCES)
        if error_code == AutoTripErrorCode.PATH_NOT_FOUND:
            return self._on_route_failure(RouteFailure.NO_ROUTE)
        super().on_multi_farming_behavior_finished(error_code)

    def play_fighter(self) -> None:
        if not self.game_state.settings.do_fighter:
            return self.finish("Combat is disabled and the inventory cannot be unloaded.")
        if self._selected_zone is None:
            with AREA_CHOICE_LOCK:
                zone, _ = self._select_zone()
                self._set_zone(zone)
        if self._selected_zone is None:
            return self._on_route_failure(RouteFailure.NO_ZONE)
        if not self._zone_has_maps(self._selected_zone):
            return self._on_route_failure(RouteFailure.NO_ROUTE)
        self._publish(
            "Combat", "The inventory cannot be unloaded right now.", "Recheck whether harvesting can resume."
        )
        super().play_fighter()

    def _get_fighter_area_info(self) -> AreaInfo:
        assert self._selected_zone is not None
        return self._selected_zone

    def on_fighter_behavior_finished(self, error_code: str | None) -> None:
        if error_code == AutoTripErrorCode.PATH_NOT_FOUND:
            return self._on_route_failure(RouteFailure.NO_ROUTE)
        super().on_fighter_behavior_finished(error_code)

    def finish(self, error_code: str | None = None, *args: object, **kwargs: object) -> None:
        if self.state is BehaviorState.RUNNING:
            self._publish("Stopped", error_code or "The activity finished.", "Press Play to start again.")
        super().finish(error_code, *args, **kwargs)
