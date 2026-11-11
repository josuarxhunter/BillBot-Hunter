from DBDofusUnity.datas.protos.non_obf.game.common_pb2 import (
    ObjectItemInventory,
)
from DBDofusUnity.dofus_unity_reader.data_center.area_info import (
    AREAS_SUB_WITH_WEIGHT,
    AREAS_UNSUB_WITH_WEIGHT,
    AreaInfo,
)
from DBDofusUnity.dofus_unity_reader.data_center.data_reader import DataReader
from src.controller.game_data import GameDataController
from src.core.config import ConfigurableAutoSettings
from DBDofusUnity.dofus_unity_reader.game_constants.area import AreaEnum
from src.core.engine.contexts import HarvesterAreaContext
from src.core.engine.weights.harvester.weight_collectable import (
    get_weight_collectable,
    get_harvest_requirements,
)


def get_fast_weight_harvester_sub_area(
    job_lvl_by_id: dict[int, int],
    storage_by_gid: dict[int, ObjectItemInventory],
    sub_area_id: int,
    is_sub: bool,
    job_id_by_item_id: dict[int, int],
    server_id: int = 1,
    preferences: ConfigurableAutoSettings | None = None,
) -> float:
    harvestables = DataReader().sub_area_by_id[sub_area_id].harvestables
    if not harvestables:
        return 0

    weight = sum(
        get_weight_collectable(
            job_id,
            job_lvl_by_id.get(job_id, 1),
            item_id,
            storage_by_gid,
            is_sub,
            server_id,
            preferences,
        )
        for item_id in harvestables
        if (job_id := job_id_by_item_id.get(item_id)) is not None
    )
    return weight / len(harvestables)


def get_harvesting_area_weights(
    context: HarvesterAreaContext,
    previous_area_info_played: list[AreaInfo],
    preferences: ConfigurableAutoSettings | None = None,
    area_infos: list[AreaInfo] | None = None,
) -> dict[AreaInfo, float]:
    if area_infos is not None:
        areas_with_weight = area_infos
    elif context.player_is_sub:
        areas_with_weight = AREAS_SUB_WITH_WEIGHT
    else:
        areas_with_weight = AREAS_UNSUB_WITH_WEIGHT

    accessible_area_infos = [
        area_info
        for area_info in areas_with_weight
        if context.player_level >= area_info.min_lvl
        and (
            area_info.waypoint_map_id_needed is None
            or area_info.waypoint_map_id_needed in context.player_waypoint_map_ids
            or (preferences is not None and area_info.area_id == AreaEnum.OTOMAI)
        )
        and (
            preferences is None
            or area_info.area_id != AreaEnum.OTOMAI
            or any(
                DataReader().sub_area_by_id[DataReader().map_info_by_map_id[map_id].subAreaId].areaId
                == AreaEnum.OTOMAI
                for map_id in context.player_waypoint_map_ids
                if map_id in DataReader().map_info_by_map_id
            )
        )
    ]
    weight_by_areas_info: dict[AreaInfo, float] = {}

    server_id = context.player_server_id
    server_area_infos = [
        info
        for (
            srv_id,
            _,
        ), info in context.current_area_infos_by_server_and_character.items()
        if srv_id == server_id
    ]

    job_id_by_item_id = (
        {item_id: job_id for item_id, job_id in GameDataController().get_item_job_by_gfx().values()}
        if preferences is None
        else {item_id: requirement[0] for item_id, requirement in get_harvest_requirements().items()}
    )
    job_lvl_by_id = dict(context.player_jobs_lvl_by_id)
    storage_by_gid = dict(context.bank_storage_by_gid)

    for area_info in accessible_area_infos:
        if area_info.sub_area_id:
            weight = get_fast_weight_harvester_sub_area(
                job_lvl_by_id,
                storage_by_gid,
                area_info.sub_area_id,
                context.player_is_sub,
                job_id_by_item_id,
                server_id,
                preferences,
            )
        else:
            subarea_weights = [
                get_fast_weight_harvester_sub_area(
                    job_lvl_by_id,
                    storage_by_gid,
                    sub_area_id,
                    context.player_is_sub,
                    job_id_by_item_id,
                    server_id,
                    preferences,
                )
                for sub_area_id in DataReader().sub_areas_by_area_id[area_info.area_id]
                if preferences is None
                or DataReader().sub_area_by_id[sub_area_id].level <= context.player_level + 40
            ]
            weight = sum(subarea_weights)
            if preferences is not None and subarea_weights:
                weight /= len(subarea_weights)
        count_area_already_playing = (
            sum(
                other.area_id == area_info.area_id
                and (
                    other.sub_area_id is None
                    or area_info.sub_area_id is None
                    or other.sub_area_id == area_info.sub_area_id
                )
                for other in server_area_infos
            )
            if preferences is not None
            else server_area_infos.count(area_info)
        )
        weight_by_areas_info[area_info] = (weight * area_info.weight_multiplier) / (
            1 + count_area_already_playing * 3 + previous_area_info_played.count(area_info)
        )

    return {
        area_info: weight_by_areas_info[area_info]
        for area_info in accessible_area_infos
        if weight_by_areas_info[area_info] > 0
    }
