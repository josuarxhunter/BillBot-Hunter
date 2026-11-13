from dataclasses import dataclass
from functools import partial

from DBDofusUnity.datas.protos.non_obf.game.gamemap_pb2 import (
    MapComplementaryInformationEvent,
)
from DBDofusUnity.datas.protos.non_obf.game.haven_bag_pb2 import (
    HavenBagEnterRequest,
)
from DBDofusUnity.dofus_unity_reader.data_center.data_reader import DataReader
from DBDofusUnity.dofus_unity_reader.game_constants.area import AreaEnum
from DBDofusUnity.dofus_unity_reader.models.datas.map_positions_root import MapInformationRootItem
from src.core.behaviors.behavior import Behavior
from src.core.behaviors.movements.auto_trip.auto_trip_behavior import (
    AutoTripBehavior,
    AutoTripErrorCode,
)
from src.core.behaviors.movements.waypoint_behavior import (
    WaypointBehavior,
    WaypointErrorCode,
)
from src.core.engine.movements.world.map_position import get_dist_to_maps
from src.core.engine.movements.world.farm_travel import find_path_from_map, plan_farm_travel
from src.core.engine.movements.world.waypoint import (
    get_final_world_entry_map_positions,
    get_near_waypoint,
)


@dataclass
class AutoTripZaapBehavior(Behavior):
    auto_trip_behavior: AutoTripBehavior
    waypoint_behavior: WaypointBehavior

    def reachable_waypoints(self, map_ids: set[int]) -> list[int]:
        context = self.game_state.get_world_path_context()
        finder = self.auto_trip_behavior.world_path_finder
        return [
            map_id
            for map_id in self.game_state.player.waypoint_map_ids
            if map_id != self.game_state.map.map_id
            and find_path_from_map(finder, context, map_id, map_ids) is not None
        ]

    def can_reach(self, map_ids: set[int]) -> bool:
        return self.auto_trip_behavior.world_path_finder.find_path(
            self.game_state.get_world_path_context(), self.game_state.map.curr_vertex, map_ids
        ) is not None or bool(self.reachable_waypoints(map_ids))

    def run(self, map_ids: set[int]) -> None:
        preferences = self.game_state.configurable_auto
        if preferences is not None:
            plan = plan_farm_travel(
                self.game_state,
                self.auto_trip_behavior.world_path_finder,
                map_ids,
                preferences,
            )
            if plan is None:
                return self.finish(AutoTripErrorCode.PATH_NOT_FOUND)
            self.logger.info("Farm travel: %s", plan)
            if plan.waypoint_map_id is not None:
                return self.waypoint_behavior.start(
                    callback=partial(self.on_configurable_waypoint_finished, map_ids=map_ids),
                    parent=self,
                    map_id=plan.waypoint_map_id,
                    dst_map_ids=map_ids,
                )
            return self.auto_trip_behavior.start(callback=self.finish, parent=self, map_ids=map_ids)
        if (
            not self.game_state.player.is_sub
            or self.game_state.player.level < 10
            or DataReader().sub_area_by_id[self.game_state.map.sub_area_id].areaId == AreaEnum.INCARNAM
            or self.game_state.inventory.kamas < 3_000
        ):
            self.logger.info("Can't use zaap, walk to dst")
            return self.auto_trip_behavior.start(callback=self.finish, parent=self, map_ids=map_ids)

        destination_map_positions = [DataReader().map_info_by_map_id[map_id] for map_id in map_ids]
        world_path = self.auto_trip_behavior.world_path_finder.find_path(
            self.game_state.get_world_path_context(), self.game_state.map.curr_vertex, map_ids
        )
        world_entry_map_positions = get_final_world_entry_map_positions(world_path)
        waypoint_target_positions = world_entry_map_positions or destination_map_positions
        dist_player_to_ends = get_dist_to_maps(self.game_state.map.map_pos, waypoint_target_positions)
        if world_path is not None:
            # Indoor entrances can share coordinates across subareas, inflating the heuristic.
            dist_player_to_ends = min(dist_player_to_ends, len(world_path))

        self.logger.info(
            "Get near waypoint with dist player to target : "
            f"{dist_player_to_ends} with waypoints : {self.game_state.player.waypoint_map_ids}"
        )
        if world_entry_map_positions:
            self.logger.info(
                "Changing world, selecting waypoint near entry maps : "
                f"{[map_position.id for map_position in world_entry_map_positions]}"
            )
        near_waypoint = get_near_waypoint(
            self.reachable_waypoints(map_ids),
            dist_player_to_ends,
            waypoint_target_positions,
            True,
        )
        if near_waypoint is not None:
            return self.waypoint_behavior.start(
                callback=partial(
                    self.on_near_waypoint_behavior_finished,
                    map_ids=map_ids,
                    ends_pos=destination_map_positions,
                ),
                parent=self,
                map_id=near_waypoint.map_id,
                dst_map_ids=map_ids,
            )
        if self.game_state.map.is_in_haven_bag:
            self.event_manager.on(
                MapComplementaryInformationEvent,
                lambda _: self.walk_to_map_ids(map_ids=map_ids, ends_pos=destination_map_positions),
                originator=self,
                once=True,
            )
            req = HavenBagEnterRequest()
            self.event_manager.send(req)
        else:
            self.walk_to_map_ids(map_ids=map_ids, ends_pos=destination_map_positions)

    def on_near_waypoint_behavior_finished(
        self,
        error_code: str | None,
        map_ids: set[int],
        ends_pos: list[MapInformationRootItem],
    ):
        if error_code is WaypointErrorCode.UNREACHABLE_HAVRE_MAP:
            return self.walk_to_map_ids(map_ids, ends_pos)
        self.raise_if_error(error_code)
        self.walk_to_map_ids(map_ids, ends_pos)

    def on_configurable_waypoint_finished(self, error_code: str | None, map_ids: set[int]) -> None:
        if error_code is not None and error_code not in {
            WaypointErrorCode.UNREACHABLE_HAVRE_MAP,
            WaypointErrorCode.UNAFFORDABLE,
        }:
            return self.finish(error_code)

        def walk() -> None:
            if not self.game_state.map.is_in_haven_bag:
                return self.auto_trip_behavior.start(callback=self.finish, parent=self, map_ids=map_ids)
            self.event_manager.on(
                MapComplementaryInformationEvent,
                lambda _: self.auto_trip_behavior.start(callback=self.finish, parent=self, map_ids=map_ids),
                originator=self,
                once=True,
            )
            self.event_manager.send(HavenBagEnterRequest())

        self.ensure_dialog_closed(walk)

    def walk_to_map_ids(self, map_ids: set[int], ends_pos: list[MapInformationRootItem]):
        self.auto_trip_behavior.start(
            parent=self,
            map_ids=map_ids,
            callback=partial(self.on_auto_trip_behavior_finished, map_ids=map_ids, ends_pos=ends_pos),
        )

    def on_auto_trip_behavior_finished(
        self,
        error_code: str | None,
        map_ids: set[int],
        ends_pos: list[MapInformationRootItem],
    ):
        if error_code is AutoTripErrorCode.PATH_NOT_FOUND:
            self.logger.info("Path not found, try to use waypoint")
            near_waypoint = get_near_waypoint(self.reachable_waypoints(map_ids), None, ends_pos, True)
            if near_waypoint is None:
                return self.finish(AutoTripErrorCode.PATH_NOT_FOUND)
            return self.waypoint_behavior.start(
                callback=partial(
                    self.on_waypoint_behavior_finished_after_auto_trip_fail,
                    map_ids=map_ids,
                ),
                parent=self,
                map_id=near_waypoint.map_id,
                dst_map_ids=map_ids,
            )
        self.finish(error_code)

    def on_waypoint_behavior_finished_after_auto_trip_fail(self, error_code: str | None, map_ids: set[int]):
        if error_code is WaypointErrorCode.UNREACHABLE_HAVRE_MAP:
            return self.finish(AutoTripErrorCode.PATH_NOT_FOUND)
        self.raise_if_error(error_code)
        self.auto_trip_behavior.start(parent=self, map_ids=map_ids, callback=self.finish)
