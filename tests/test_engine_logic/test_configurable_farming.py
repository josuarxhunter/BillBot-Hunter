from dataclasses import replace
from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock
from pathlib import Path

import pytest
from DBDofusUnity.datas.protos.non_obf.game.common_pb2 import ObjectItem, ObjectItemInventory
from DBDofusUnity.dofus_unity_reader.data_center.area_info import AreaInfo
from DBDofusUnity.dofus_unity_reader.game_constants.job import JobEnum
from DBDofusUnity.dofus_unity_reader.models.world_graph import Edge, Vertice
from DBDofusUnity.dofus_unity_reader.game_constants.map_id import MapIdEnum
from DBDofusUnity.dofus_unity_reader.data_center.world_graph_reader import WorldGraphReader
from src.core.bot.bot import Bot
from src.core.config import ConfigurableAutoSettings, HarvestGoal
from src.core.engine.movements.world import farm_travel
from src.core.engine.movements.world.world_path_finder import WorldPathFinder
from src.core.engine.contexts import WorldPathContext
from DBDofusUnity.dofus_unity_reader.models.datas.map_positions_root import MapInformationRootItem
from src.core.engine.weights import weight_areas
from src.core.engine.weights.harvester import weight_collectable
from src.controller.game_data import GameDataController


def test_resource_goal_filters_skill_level_and_completed_targets(monkeypatch: pytest.MonkeyPatch) -> None:
    job = JobEnum.MINER
    monkeypatch.setattr(weight_collectable, "get_harvest_requirements", lambda: {100: (job, 40)})
    monkeypatch.setattr(
        weight_collectable,
        "GameDataController",
        lambda: SimpleNamespace(
            get_avg_price_by_gid=Mock(return_value={100: 100.0}),
            get_price_confidence=Mock(return_value=1.0),
        ),
    )
    preferences = ConfigurableAutoSettings(
        goal=HarvestGoal.TARGETS, target_resource_ids=(100,), target_quantity=10
    )
    weight = weight_collectable.get_weight_collectable
    assert weight(job, 39, 100, {}, True, 1, preferences) == 0
    assert weight(job, 40, 100, {}, True, 1, preferences) > 0
    stored = {100: ObjectItemInventory(item=ObjectItem(gid=100, quantity=10))}
    assert weight(job, 40, 100, stored, True, 1, preferences) == 0
    assert weight(job, 200, 100, {}, True, 1, ConfigurableAutoSettings(goal=HarvestGoal.EXPERIENCE)) == 0


def test_travel_can_leave_incarnam_via_existing_smart_route(
    runtime_bot: Bot, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = runtime_bot.game_state
    state.map.map_id = MapIdEnum.INCARNAM_PORTAL
    state.player.level = 20
    source = next(iter(WorldGraphReader().get_vertexes(MapIdEnum.INCARNAM_PORTAL)))
    monkeypatch.setattr(type(state.map), "curr_vertex", property(lambda _map: source))
    route = runtime_bot.configurable_auto_behavior.multi_farming_behavior.random_farm_behavior
    finder = route.auto_trip_smart_behavior.auto_trip_explorator_behavior.auto_trip_zaap_behavior.auto_trip_behavior.world_path_finder
    assert (
        farm_travel.plan_farm_travel(state, finder, {MapIdEnum.ASTRUB_BANK}, ConfigurableAutoSettings())
        is not None
    )


def test_full_area_does_not_gain_score_by_repeating_identical_subareas(
    runtime_bot: Bot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    area = AreaInfo(area_id=1)
    subarea = AreaInfo(area_id=1, sub_area_id=10)
    monkeypatch.setattr(
        weight_areas,
        "DataReader",
        lambda: SimpleNamespace(
            sub_area_by_id={10: SimpleNamespace(level=1), 11: SimpleNamespace(level=1)},
            sub_areas_by_area_id={1: [10, 11]},
        ),
    )
    monkeypatch.setattr(weight_areas, "get_harvest_requirements", Mock(return_value={}))
    monkeypatch.setattr(weight_areas, "get_fast_weight_harvester_sub_area", Mock(return_value=10.0))
    context = replace(runtime_bot.configurable_auto_behavior.get_harvester_area_context(), player_level=200)
    scores = weight_areas.get_harvesting_area_weights(
        context, [], ConfigurableAutoSettings(), [area, subarea]
    )
    assert scores[area] == scores[subarea]


def test_harvest_stock_counts_bank_and_inventory_without_mutating_bank(runtime_bot: Bot) -> None:
    inventory = runtime_bot.game_state.inventory
    inventory.bank_objects_by_uid = {
        1: ObjectItemInventory(item=ObjectItem(uid=1, gid=100, quantity=3)),
        2: ObjectItemInventory(item=ObjectItem(uid=2, gid=100, quantity=4)),
    }
    inventory.objects_by_uid.clear()
    inventory.objects_by_uid[3] = ObjectItemInventory(item=ObjectItem(uid=3, gid=100, quantity=5))
    assert inventory.get_harvest_stock_by_gid()[100].item.quantity == 12
    assert inventory.get_harvest_stock_by_gid()[100].item.quantity == 12
    assert inventory.bank_objects_by_uid[1].item.quantity == 3
    assert inventory.bank_objects_by_uid[2].item.quantity == 4


@pytest.mark.parametrize("reserve,expected_zaap", [(1000, 3), (5000, None)])
def test_travel_rejects_unreachable_zaap_and_preserves_reserve(
    runtime_bot: Bot,
    monkeypatch: pytest.MonkeyPatch,
    reserve: int,
    expected_zaap: int | None,
) -> None:
    state = runtime_bot.game_state
    monkeypatch.setattr(type(state.player), "is_sub", property(lambda _player: True))
    state.player.level = 100
    state.inventory.kamas = 5000
    state.player.waypoint_map_ids = [2, 3]
    state.haven_bag_zaap_costs = {2: 0, 3: 100}
    state.haven_bag_zaap_origin_map_id = state.map.map_id
    source = Vertice(1, 1, 1)
    monkeypatch.setattr(type(state.map), "curr_vertex", property(lambda _map: source))
    positions = {
        map_id: SimpleNamespace(
            id=map_id,
            posX=map_id,
            posY=0,
            worldMap=1,
            subAreaId=99,
        )
        for map_id in (1, 2, 3, 4)
    }
    monkeypatch.setattr(
        farm_travel,
        "DataReader",
        lambda: SimpleNamespace(
            map_info_by_map_id=positions,
            sub_area_by_id={state.map.sub_area_id: SimpleNamespace(areaId=1), 99: SimpleNamespace(areaId=1)},
            waypoint_by_id={index: SimpleNamespace(activated=1, mapId=index) for index in (2, 3)},
        ),
    )
    monkeypatch.setattr(farm_travel, "get_final_world_entry_map_positions", Mock(return_value=[]))

    def distance(position: MapInformationRootItem, _targets: list[MapInformationRootItem]) -> float:
        return abs(position.posX - 4)

    def vertexes(map_id: int) -> list[Vertice]:
        return [Vertice(map_id, 1, map_id)]

    monkeypatch.setattr(farm_travel, "get_dist_to_maps", distance)
    monkeypatch.setattr(
        farm_travel,
        "WorldGraphReader",
        lambda: SimpleNamespace(
            get_vertexes=vertexes,
        ),
    )
    edge = Edge(source, Vertice(4, 1, 4), [])
    finder = Mock(spec=WorldPathFinder)

    def path(_context: WorldPathContext, vertex: Vertice, _targets: set[int]) -> list[Edge] | None:
        paths: dict[int, list[Edge] | None] = {1: [edge] * 10, 2: None, 3: [edge]}
        return paths[vertex.m_mapId]

    finder.find_path.side_effect = path
    plan = farm_travel.plan_farm_travel(
        state,
        cast(WorldPathFinder, finder),
        {4},
        ConfigurableAutoSettings(
            reserve_kamas=reserve,
        ),
    )
    assert plan is not None
    assert plan.waypoint_map_id == expected_zaap


def test_price_confidence_survives_reload_and_decreases_with_age(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    controller = GameDataController()
    monkeypatch.setattr(controller, "_FILE_PATH", tmp_path / "game_data.json")
    monkeypatch.setattr("src.controller.game_data.time", lambda: 1000)
    controller.add_multiple_avg_price_by_gid(1, [(500, 100)])
    assert controller.get_price_confidence(1, 100, 24) == 1
    monkeypatch.setattr(controller, "_game_data", None)
    monkeypatch.setattr("src.controller.game_data.time", lambda: 1000 + 86400)
    assert controller.get_price_confidence(1, 100, 24) == 0.5
    assert controller.get_price_confidence(1, 200, 24) == 0.5
