from dataclasses import dataclass, field
from enum import StrEnum
from functools import partial
from time import monotonic

from DBDofusUnity.datas.protos.non_obf.game.gamemap_pb2 import (
    MapComplementaryInformationEvent,
)
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
        self._room_map_id = None
        self._traversal_failures = 0
        self.logger.info("Starting dungeon %s; %s remaining", dungeon_info.name, len(self._pending_dungeons))
        if self.game_state.map.map_id in dungeon_info.interior_map_ids:
            return self.on_new_map(dungeon_info)

        self.auto_trip_smart_behavior.start(
            map_ids={dungeon_info.entrance_npc_info.npc_map_id},
            callback=partial(
                self.on_auto_trip_smart_behavior_to_entrance_finished,
                dungeon_info=dungeon_info,
            ),
            parent=self,
        )

    def on_auto_trip_smart_behavior_to_entrance_finished(
        self, error_code: str | None, dungeon_info: DungeonInfo
    ) -> None:
        if error_code is not None:
            if error_code == AutoTripErrorCode.PATH_NOT_FOUND:
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
