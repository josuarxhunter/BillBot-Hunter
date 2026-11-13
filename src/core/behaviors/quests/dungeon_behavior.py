from dataclasses import dataclass, field
from enum import StrEnum
from functools import partial
from collections.abc import Callable
from time import monotonic

from DBDofusUnity.datas.protos.non_obf.game.gamemap_pb2 import (
    MapComplementaryInformationEvent,
    MapObstacle,
    MapObstacleUpdateEvent,
)
from DBDofusUnity.dofus_unity_reader.grid.map_point import MapPoint
from src.core.behaviors.movements.map_move_behavior import MapMoveError
from src.core.behaviors.behavior import Behavior
from src.controller.settings import SettingsService
from src.core.config import DungeonSettings
from src.core.behaviors.farms.fight.attacker_behavior import AttackerBehavior
from src.core.behaviors.movements.auto_trip.auto_trip_smart_behavior import (
    AutoTripSmartBehavior,
)
from src.core.behaviors.movements.auto_trip.auto_trip_behavior import AutoTripErrorCode
from src.core.behaviors.npcs.npc_dialog_behavior import NpcDialogBehavior
from src.core.behaviors.quests.dungeon_traversal_behavior import DungeonTraversalBehavior
from src.core.engine.dungeons.dungeon_access import (
    DungeonAccess,
    get_dungeon_access,
)
from src.core.engine.dungeons.dungeon_info import ALL_DUNGEONS, DungeonInfo, PLAYABLE_DUNGEONS, get_dungeon_info_for_map_id


class DungeonError(StrEnum):
    UNSUPPORTED_DUNGEON = "The selected dungeon is not supported."
    NO_KEY_ACCESS = "No key or keyring access is available for the selected dungeon."
    UNEXPECTED_MAP = "The dungeon ended on an unexpected map."
    PARTY_REQUIRED = "This dungeon requires two coordinated characters and is not automated yet."
    NO_PROGRESS = "The dungeon stopped making progress."
    ENTRANCE_UNREACHABLE = "The dungeon entrance is unreachable. Check its access requirements or start beside the entrance NPC."
    ACCESS_UNAVAILABLE = "The dungeon transport is unavailable. Check island opening, access quests and travel fare."


@dataclass
class DungeonBehavior(Behavior):
    account_id: int
    npc_dialog_behavior: NpcDialogBehavior
    attacker_behavior: AttackerBehavior
    auto_trip_smart_behavior: AutoTripSmartBehavior
    traversal_behavior: DungeonTraversalBehavior

    _activity_performed: bool = field(init=False, default=False)
    _pending_dungeons: list[DungeonInfo] = field(init=False, default_factory=list[DungeonInfo])
    _current_dungeon: DungeonInfo | None = field(init=False, default=None)
    _sequence_ids: tuple[int, ...] | None = field(init=False, default=None)
    _exit_dialog_finished: bool = field(init=False, default=False)
    _exit_map_received: bool = field(init=False, default=False)
    _entry_dialog_finished: bool = field(init=False, default=False)
    _entry_map_received: bool = field(init=False, default=False)
    _room_map_id: int | None = field(init=False, default=None)
    _room_started_at: float = field(init=False, default=0)
    _traversal_failures: int = field(init=False, default=0)
    _access_attempted: bool = field(init=False, default=False)
    _access_dialog_finished: bool = field(init=False, default=False)
    _access_map_received: bool = field(init=False, default=False)

    @property
    def activity_performed(self) -> bool:
        return self._activity_performed

    def run(
        self,
        dungeon_info: DungeonInfo | None = None,
        *,
        preferences: DungeonSettings | None = None,
    ) -> None:
        previous_dungeon = self._current_dungeon
        previous_pending = self._pending_dungeons.copy()
        previous_sequence = self._sequence_ids
        self._sequence_ids = None
        self._activity_performed = False
        self._pending_dungeons = []
        self._current_dungeon = None
        self._room_map_id = None
        self._traversal_failures = 0
        if dungeon_info is not None:
            if dungeon_info.blocked_reason is not None:
                return self.finish(DungeonError.PARTY_REQUIRED)
            return self.start_dungeon(dungeon_info)

        preferences = preferences if preferences is not None else SettingsService().dungeons(self.account_id)
        by_id = {info.dungeon.id: info for info in ALL_DUNGEONS}
        current_dungeon = get_dungeon_info_for_map_id(self.game_state.map.map_id)
        if preferences.follow_sequence:
            dungeon_ids = preferences.sequence
            self._sequence_ids = dungeon_ids
        elif preferences.dungeon_id is not None:
            dungeon_ids = (preferences.dungeon_id,)
        elif current_dungeon is not None:
            dungeon_ids = (current_dungeon.dungeon.id,)
        else:
            dungeon_info = next(
                (
                    _dungeon_info
                    for _dungeon_info in PLAYABLE_DUNGEONS
                    if get_dungeon_access(
                        _dungeon_info,
                        self.game_state.inventory.objects_by_uid,
                        self.logger,
                    )
                    is not None
                ),
                None,
            )
            if dungeon_info is None:
                return self.finish()
            dungeon_ids = (dungeon_info.dungeon.id,)

        if any(dungeon_id not in by_id for dungeon_id in dungeon_ids):
            return self.finish(DungeonError.UNSUPPORTED_DUNGEON)
        if any(by_id[dungeon_id].blocked_reason is not None for dungeon_id in dungeon_ids):
            return self.finish(DungeonError.PARTY_REQUIRED)
        self._pending_dungeons = [by_id[dungeon_id] for dungeon_id in dungeon_ids]
        if current_dungeon is not None:
            if current_dungeon.blocked_reason is not None:
                return self.finish(DungeonError.PARTY_REQUIRED)
            if (
                preferences.follow_sequence
                and previous_sequence == dungeon_ids
                and previous_dungeon is current_dungeon
            ):
                self._pending_dungeons = previous_pending
            elif current_dungeon.dungeon.id in dungeon_ids:
                self._pending_dungeons = self._pending_dungeons[dungeon_ids.index(current_dungeon.dungeon.id) + 1:]
            self.logger.info("Resuming %s from map %s", current_dungeon.name, self.game_state.map.map_id)
            return self.start_dungeon(current_dungeon)
        self.start_next_dungeon()

    def start_next_dungeon(self) -> None:
        if not self._pending_dungeons:
            return self.finish()
        dungeon_info = self._pending_dungeons.pop(0)
        already_inside = self.game_state.map.map_id in dungeon_info.interior_map_ids
        if (
            not already_inside
            and get_dungeon_access(dungeon_info, self.game_state.inventory.objects_by_uid, self.logger)
            is None
        ):
            return self.finish(DungeonError.NO_KEY_ACCESS)
        self.start_dungeon(dungeon_info)

    def start_dungeon(self, dungeon_info: DungeonInfo) -> None:
        self._current_dungeon = dungeon_info
        self._access_attempted = False
        self._room_map_id = None
        self._traversal_failures = 0
        self.logger.info("Starting dungeon %s; %s remaining", dungeon_info.name, len(self._pending_dungeons))
        if self.game_state.map.map_id in dungeon_info.interior_map_ids:
            return self.on_new_map(dungeon_info)
        if dungeon_info.entrance_plate is not None and self.game_state.map.map_id != dungeon_info.dungeon.entranceMapId:
            return self.auto_trip_smart_behavior.start(
                map_ids={dungeon_info.entrance_plate.map_id},
                callback=partial(self.on_plate_map_arrived, dungeon_info=dungeon_info), parent=self,
            )

        self.auto_trip_smart_behavior.start(
            map_ids={dungeon_info.entrance_npc_info.npc_map_id},
            callback=partial(
                self.on_auto_trip_smart_behavior_to_entrance_finished,
                dungeon_info=dungeon_info,
            ),
            parent=self,
        )

    def move_to_plate_cell(self, cell_id: int, callback: Callable[[str | None], None]) -> None:
        target = MapPoint.from_cell_id(cell_id)
        path = self.traversal_behavior.path_finding.find_path(
            self.game_state.get_map_movement_context(), self.game_state.map.map_point, {target},
        )
        if path.end != target:
            return self.finish(DungeonError.ENTRANCE_UNREACHABLE)
        self.traversal_behavior.map_move_behavior.start(move_path=path, callback=callback, parent=self)

    def on_plate_map_arrived(self, error_code: str | None, dungeon_info: DungeonInfo) -> None:
        if error_code is not None:
            return self.finish(error_code)
        plate = dungeon_info.entrance_plate
        assert plate is not None
        if self.game_state.map.map_id != plate.map_id:
            return self.finish(DungeonError.UNEXPECTED_MAP)
        if self.game_state.map.map_point.cell_id == plate.cell_id:
            return self.move_to_plate_cell(
                plate.reset_cell_id, partial(self.on_plate_reset, dungeon_info=dungeon_info),
            )
        self.on_plate_reset(None, dungeon_info)

    def on_plate_reset(self, error_code: str | None, dungeon_info: DungeonInfo) -> None:
        if error_code is not None:
            return self.finish(error_code)
        assert dungeon_info.entrance_plate is not None
        self.move_to_plate_cell(
            dungeon_info.entrance_plate.cell_id, partial(self.on_plate_reached, dungeon_info=dungeon_info),
        )

    def on_plate_reached(self, error_code: str | None, dungeon_info: DungeonInfo) -> None:
        if error_code is not None:
            return self.finish(error_code)
        plate = dungeon_info.entrance_plate
        assert plate is not None
        if self.game_state.map.map_point.cell_id != plate.cell_id:
            return self.finish(MapMoveError.CANCELED_MOVEMENT)
        self.event_manager.on(
            MapObstacleUpdateEvent, partial(self.on_plate_obstacles_updated, dungeon_info=dungeon_info),
            originator=self, timeout=5, on_timeout=lambda: self.finish(DungeonError.ACCESS_UNAVAILABLE),
        )
        self.on_plate_obstacles_updated(MapObstacleUpdateEvent(), dungeon_info)

    def on_plate_obstacles_updated(self, msg: MapObstacleUpdateEvent, dungeon_info: DungeonInfo) -> None:
        del msg
        plate = dungeon_info.entrance_plate
        assert plate is not None
        obstacle = self.game_state.entity.obstacle_on_cell_id.get(plate.passage_cell_id)
        if obstacle is None or obstacle.state != MapObstacle.OBSTACLE_OPENED:
            return
        self.event_manager.clear_listener_by_origin_and_type(MapObstacleUpdateEvent, self)
        self.event_manager.on(
            MapComplementaryInformationEvent, partial(self.on_crypt_loaded, dungeon_info=dungeon_info),
            originator=self, once=True, timeout=15, on_timeout=lambda: self.finish(DungeonError.NO_PROGRESS),
        )
        self.move_to_plate_cell(plate.passage_cell_id, self.on_crypt_movement_finished)

    def on_crypt_movement_finished(self, error_code: str | None) -> None:
        if error_code is not None:
            self.finish(error_code)

    def on_crypt_loaded(self, msg: MapComplementaryInformationEvent, dungeon_info: DungeonInfo) -> None:
        if msg.map_id != dungeon_info.dungeon.entranceMapId:
            return self.finish(DungeonError.UNEXPECTED_MAP)
        self.traversal_behavior.map_move_behavior.stop()
        self.on_auto_trip_smart_behavior_to_entrance_finished(None, dungeon_info)

    def on_auto_trip_smart_behavior_to_entrance_finished(
        self, error_code: str | None, dungeon_info: DungeonInfo
    ) -> None:
        if error_code is not None:
            if error_code == AutoTripErrorCode.PATH_NOT_FOUND:
                if dungeon_info.access_npc_info is not None and not self._access_attempted:
                    self._access_attempted = True
                    return self.travel_to_access_npc(dungeon_info)
                self.logger.warning("Cannot reach %s: %s", dungeon_info.name, dungeon_info.access_note)
                return self.finish(DungeonError.ENTRANCE_UNREACHABLE)
            return self.finish(error_code)

        access = get_dungeon_access(dungeon_info, self.game_state.inventory.objects_by_uid, self.logger)
        if access is None:
            return self.finish(DungeonError.NO_KEY_ACCESS)
        self.logger.info("Entering %s using %s", dungeon_info.name, access)
        self._entry_dialog_finished = False
        self._entry_map_received = False
        self.event_manager.on(
            MapComplementaryInformationEvent,
            lambda msg: self.on_entrance_map_loaded(msg, dungeon_info),
            originator=self,
            once=True,
            timeout=60,
            on_timeout=lambda: self.finish(DungeonError.NO_PROGRESS),
        )
        self.npc_dialog_behavior.start(
            npc_dialog_info=dungeon_info.entrance_npc_info,
            turn_variants=[
                dungeon_info.keyring_entrance_turns
                if access is DungeonAccess.KEYRING
                else dungeon_info.key_entrance_turns
            ],
            callback=partial(self.on_npc_dialog_behavior_finished, dungeon_info=dungeon_info),
            parent=self,
        )

    def travel_to_access_npc(self, dungeon_info: DungeonInfo) -> None:
        assert dungeon_info.access_npc_info is not None
        if self.game_state.inventory.kamas < dungeon_info.access_cost:
            return self.finish(DungeonError.ACCESS_UNAVAILABLE)
        self.auto_trip_smart_behavior.start(
            map_ids={dungeon_info.access_npc_info.npc_map_id},
            callback=partial(self.on_access_trip_finished, dungeon_info=dungeon_info),
            parent=self,
        )

    def on_access_trip_finished(self, error_code: str | None, dungeon_info: DungeonInfo) -> None:
        if error_code is not None:
            return self.finish(error_code)
        assert dungeon_info.access_npc_info is not None
        if self.game_state.map.map_id != dungeon_info.access_npc_info.npc_map_id:
            return self.finish(DungeonError.UNEXPECTED_MAP)
        if self.game_state.inventory.kamas < dungeon_info.access_cost:
            return self.finish(DungeonError.ACCESS_UNAVAILABLE)
        # Seasonal NPCs can be absent even though their map is reachable.
        try:
            self.game_state.entity.resolve_npc_id(dungeon_info.access_npc_info)
        except ValueError:
            return self.finish(DungeonError.ACCESS_UNAVAILABLE)
        self._access_dialog_finished = False
        self._access_map_received = False
        self.event_manager.on(
            MapComplementaryInformationEvent,
            partial(self.on_access_map_loaded, dungeon_info=dungeon_info),
            originator=self, once=True, timeout=60,
            on_timeout=lambda: self.finish(DungeonError.ACCESS_UNAVAILABLE),
        )
        self.npc_dialog_behavior.start(
            npc_dialog_info=dungeon_info.access_npc_info,
            turn_variants=[dungeon_info.access_turns],
            callback=partial(self.on_access_dialog_finished, dungeon_info=dungeon_info),
            parent=self,
        )

    def on_access_dialog_finished(self, error_code: str | None, dungeon_info: DungeonInfo) -> None:
        if error_code is not None:
            return self.finish(error_code)
        self._access_dialog_finished = True
        self.continue_after_access(dungeon_info)

    def on_access_map_loaded(self, msg: MapComplementaryInformationEvent, dungeon_info: DungeonInfo) -> None:
        assert dungeon_info.access_npc_info is not None
        if msg.map_id == dungeon_info.access_npc_info.npc_map_id:
            return self.finish(DungeonError.ACCESS_UNAVAILABLE)
        self._access_map_received = True
        self.continue_after_access(dungeon_info)

    def continue_after_access(self, dungeon_info: DungeonInfo) -> None:
        if self._access_dialog_finished and self._access_map_received:
            self.auto_trip_smart_behavior.start(
                map_ids={dungeon_info.entrance_npc_info.npc_map_id},
                callback=partial(self.on_auto_trip_smart_behavior_to_entrance_finished, dungeon_info=dungeon_info),
                parent=self,
            )

    def on_npc_dialog_behavior_finished(self, error_code: str | None, dungeon_info: DungeonInfo) -> None:
        if error_code is not None:
            return self.finish(error_code)
        self._entry_dialog_finished = True
        if self._entry_map_received:
            self.on_new_map(dungeon_info)

    def on_entrance_map_loaded(
        self, msg: MapComplementaryInformationEvent, dungeon_info: DungeonInfo
    ) -> None:
        if msg.map_id not in dungeon_info.interior_map_ids:
            return self.finish(DungeonError.UNEXPECTED_MAP)
        self._entry_map_received = True
        if self._entry_dialog_finished:
            self.on_new_map(dungeon_info)

    def on_new_map(self, dungeon_info: DungeonInfo) -> None:
        map_id = self.game_state.map.map_id
        if map_id in dungeon_info.exit_map_ids:
            return self.exit_dungeon(dungeon_info)
        if map_id not in dungeon_info.interior_map_ids:
            return self.finish(DungeonError.UNEXPECTED_MAP)
        if map_id in dungeon_info.room_transitions:
            return self.traverse_room(dungeon_info, dungeon_info.room_transitions[map_id])
        if map_id != self._room_map_id:
            self._room_map_id = map_id
            self._room_started_at = monotonic()

        def get_lvl_limit(_: int) -> float:
            return float("inf")

        self.attacker_behavior.start(
            count_fight_limit=1,
            wait_for_group=False,
            get_lvl_limit=get_lvl_limit,
            callback=partial(self.on_attacker_behavior_finished, dungeon_info=dungeon_info),
            parent=self,
        )

    def on_attacker_behavior_finished(
        self,
        error_code: str | None,
        count_fighted_on_map: int,
        dungeon_info: DungeonInfo,
    ) -> None:
        if error_code is not None:
            return self.finish(error_code)
        if count_fighted_on_map > 0:
            self._activity_performed = True
            self._room_map_id = None
        elif self.game_state.map.map_id == self._room_map_id:
            if monotonic() - self._room_started_at >= 60:
                return self.finish(DungeonError.NO_PROGRESS)
            return self.run_timer(0.5, lambda: self.on_new_map(dungeon_info))
        self.on_new_map(dungeon_info)

    def traverse_room(self, dungeon_info: DungeonInfo, target_map_id: int, *, leaving: bool = False) -> None:
        self.traversal_behavior.start(
            target_map_id=target_map_id,
            parent=self,
            callback=partial(self.on_traversal_finished, dungeon_info=dungeon_info, leaving=leaving),
        )

    def on_traversal_finished(self, error_code: str | None, dungeon_info: DungeonInfo, leaving: bool) -> None:
        if error_code is not None:
            self._traversal_failures += 1
            if self._traversal_failures <= 3 and self.game_state.map.map_id in dungeon_info.room_transitions:
                return self.run_timer(0.5, lambda: self.on_new_map(dungeon_info))
            return self.finish(error_code)
        if leaving:
            if self.game_state.map.map_id in dungeon_info.interior_map_ids:
                return self.finish(DungeonError.UNEXPECTED_MAP)
            return self.start_next_dungeon()
        self.on_new_map(dungeon_info)

    def exit_dungeon(self, dungeon_info: DungeonInfo) -> None:
        if self.game_state.map.map_id not in dungeon_info.exit_map_ids:
            return self.finish(DungeonError.UNEXPECTED_MAP)
        if dungeon_info.exit_npc_info is None:
            return self.traverse_room(dungeon_info, dungeon_info.dungeon.exitMapId, leaving=True)

        self._exit_dialog_finished = False
        self._exit_map_received = False
        self.event_manager.on(
            MapComplementaryInformationEvent,
            callback=self.on_new_map_after_exit_dungeon,
            originator=self,
            once=True,
            timeout=60,
            on_timeout=lambda: self.finish(DungeonError.NO_PROGRESS),
        )
        self.npc_dialog_behavior.start(
            npc_dialog_info=dungeon_info.exit_npc_info,
            turn_variants=[dungeon_info.exit_turns],
            callback=self.on_exit_npc_dialog_behavior_finished,
            parent=self,
        )

    def on_exit_npc_dialog_behavior_finished(self, error_code: str | None) -> None:
        if error_code is not None:
            return self.finish(error_code)
        self._exit_dialog_finished = True
        self.continue_after_exit()

    def on_new_map_after_exit_dungeon(self, msg: MapComplementaryInformationEvent) -> None:
        assert self._current_dungeon is not None
        if msg.map_id in self._current_dungeon.interior_map_ids:
            return self.finish(DungeonError.UNEXPECTED_MAP)
        self._exit_map_received = True
        self.continue_after_exit()

    def continue_after_exit(self) -> None:
        if self._exit_dialog_finished and self._exit_map_received:
            self.start_next_dungeon()
