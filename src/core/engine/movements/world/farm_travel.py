from dataclasses import dataclass, replace

from DBDofusUnity.dofus_unity_reader.data_center.data_reader import DataReader
from DBDofusUnity.dofus_unity_reader.data_center.world_graph_reader import WorldGraphReader
from DBDofusUnity.dofus_unity_reader.game_constants.area import AreaEnum
from DBDofusUnity.dofus_unity_reader.game_constants.map_id import MapIdEnum
from DBDofusUnity.dofus_unity_reader.models.world_graph import Edge
from src.core.engine.contexts import WorldPathContext
from src.core.config import ConfigurableAutoSettings
from src.core.engine.movements.world.map_position import get_dist_to_maps
from src.core.engine.movements.world.waypoint import get_final_world_entry_map_positions
from src.core.engine.movements.world.world_path_finder import WorldPathFinder
from src.core.states.game_state import GameState


@dataclass(frozen=True)
class FarmTravelPlan:
    seconds: float
    cost: int = 0
    waypoint_map_id: int | None = None

    def effort(self, preferences: ConfigurableAutoSettings) -> float:
        return self.seconds + self.cost * 60 / preferences.travel_value_per_minute


def find_path_from_map(
    finder: WorldPathFinder,
    context: WorldPathContext,
    source_map_id: int,
    destinations: set[int],
) -> list[Edge] | None:
    position = DataReader().map_info_by_map_id[source_map_id]
    source_context = replace(
        context,
        current_map_pos=position,
        transition=replace(
            context.transition,
            criterion=replace(
                context.transition.criterion,
                map_id=source_map_id,
                sub_area_id=position.subAreaId,
            ),
        ),
    )
    paths = [
        path
        for vertex in WorldGraphReader().get_vertexes(source_map_id)
        if (path := finder.find_path(source_context, vertex, destinations)) is not None
    ]
    return min(paths, key=len) if paths else None


def plan_farm_travel(
    state: GameState,
    finder: WorldPathFinder,
    map_ids: set[int],
    preferences: ConfigurableAutoSettings,
) -> FarmTravelPlan | None:
    if not map_ids:
        return None
    if state.map.map_id in map_ids:
        return FarmTravelPlan(0)
    reader = DataReader()
    context = state.get_world_path_context()
    if reader.sub_area_by_id[state.map.sub_area_id].areaId == AreaEnum.INCARNAM and any(
        reader.sub_area_by_id[reader.map_info_by_map_id[map_id].subAreaId].areaId != AreaEnum.INCARNAM
        for map_id in map_ids
    ):
        approach = finder.find_path(context, state.map.curr_vertex, {MapIdEnum.INCARNAM_PORTAL})
        # The smart trip uses an NPC portal outside the world graph. Estimate the
        # Astrub leg from its outdoor hub; execution replans after the actual arrival.
        onward = find_path_from_map(finder, context, MapIdEnum.ASTRUB_STREET_KERUBIM, map_ids)
        if approach is None or onward is None:
            return None
        return FarmTravelPlan(
            (len(approach) + len(onward)) * preferences.seconds_per_map + preferences.teleport_seconds
        )
    walk = finder.find_path(context, state.map.curr_vertex, map_ids)
    best = FarmTravelPlan(len(walk) * preferences.seconds_per_map) if walk is not None else None
    if (
        not state.player.is_sub
        or state.player.level < 10
        or reader.sub_area_by_id[state.map.sub_area_id].areaId == AreaEnum.INCARNAM
        or state.inventory.kamas <= preferences.reserve_kamas
    ):
        return best

    destinations = [reader.map_info_by_map_id[map_id] for map_id in map_ids]
    targets = get_final_world_entry_map_positions(walk) or destinations
    owned = set(state.player.waypoint_map_ids)
    waypoints = [
        waypoint.mapId
        for waypoint in reader.waypoint_by_id.values()
        if waypoint.activated
        and waypoint.mapId in owned
        and reader.sub_area_by_id[reader.map_info_by_map_id[waypoint.mapId].subAreaId].areaId
        != AreaEnum.INCARNAM
    ]
    # Coordinates only shortlist candidates; graph paths decide accessibility and walking cost.
    waypoints.sort(
        key=lambda map_id: (
            reader.map_info_by_map_id[map_id].worldMap != targets[0].worldMap,
            get_dist_to_maps(reader.map_info_by_map_id[map_id], targets),
            map_id,
        )
    )
    for map_id in waypoints[:4]:
        cost = (
            state.haven_bag_zaap_costs.get(map_id, preferences.maximum_zaap_cost)
            if state.haven_bag_zaap_origin_map_id == state.map.map_id
            else preferences.maximum_zaap_cost
        )
        if cost > preferences.maximum_zaap_cost or state.inventory.kamas - cost < preferences.reserve_kamas:
            continue
        onward = find_path_from_map(finder, context, map_id, map_ids)
        if onward is None:
            continue
        plan = FarmTravelPlan(
            preferences.teleport_seconds + len(onward) * preferences.seconds_per_map,
            cost,
            map_id,
        )
        if best is None or plan.effort(preferences) < best.effort(preferences):
            best = plan
    return best
