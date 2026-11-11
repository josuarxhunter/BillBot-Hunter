from dataclasses import dataclass

from DBDofusUnity.dofus_unity_reader.data_center.data_reader import DataReader
from DBDofusUnity.dofus_unity_reader.game_constants.area import AreaEnum
from DBDofusUnity.dofus_unity_reader.models.datas.map_positions_root import MapInformationRootItem
from DBDofusUnity.dofus_unity_reader.models.world_graph import Edge

from src.core.engine.movements.world.map_position import get_dist_to_maps

ADDITIONAL_WEIGHT_WAYPOINT = 2


@dataclass
class WaypointInfoNode:
    map_id: int
    map_position: MapInformationRootItem
    dist_to_target: float


def get_final_world_entry_map_positions(
    edge_path: list[Edge] | None,
) -> list[MapInformationRootItem]:
    if not edge_path:
        return []

    positions = [DataReader().map_info_by_map_id[edge_path[0].m_from.m_mapId]]
    positions.extend(DataReader().map_info_by_map_id[edge.m_to.m_mapId] for edge in edge_path)
    final_world_map_id = positions[-1].worldMap
    previous_world_position: MapInformationRootItem | None = None
    entry_position: MapInformationRootItem | None = None
    for position in positions:
        # Indoor maps use -1 for their world: leaving a building is not a world crossing.
        if position.worldMap < 0:
            continue
        if previous_world_position is not None and previous_world_position.worldMap != position.worldMap:
            entry_position = previous_world_position if position.worldMap == final_world_map_id else None
        previous_world_position = position
    return [entry_position] if entry_position is not None else []


def get_near_waypoint(
    available_waypoint_map_ids: list[int],
    dist_player_to_ends: float | None,
    ends_pos: list[MapInformationRootItem],
    check_owned: bool,
):
    near_waypoint: WaypointInfoNode | None = None

    for waypoint in DataReader().waypoint_by_id.values():
        if waypoint.activated == 0:
            continue
        if check_owned and waypoint.mapId not in available_waypoint_map_ids:
            continue
        map_waypoint_pos = DataReader().map_info_by_map_id[waypoint.mapId]
        if DataReader().sub_area_by_id[map_waypoint_pos.subAreaId].areaId == AreaEnum.INCARNAM:
            continue

        dist_waypoint = get_dist_to_maps(map_waypoint_pos, ends_pos)
        if (
            dist_player_to_ends is not None
            and (dist_waypoint + ADDITIONAL_WEIGHT_WAYPOINT) >= dist_player_to_ends
        ):
            continue

        if near_waypoint is None or near_waypoint.dist_to_target > dist_waypoint:
            near_waypoint = WaypointInfoNode(
                map_id=waypoint.mapId,
                map_position=map_waypoint_pos,
                dist_to_target=dist_waypoint,
            )

    return near_waypoint
