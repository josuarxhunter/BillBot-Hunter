import pytest

from DBDofusUnity.dofus_unity_reader.data_center.map_reader import MapReader
from DBDofusUnity.dofus_unity_reader.data_center.world_graph_reader import WorldGraphReader
from DBDofusUnity.dofus_unity_reader.game_constants.transition_type import TransitionTypeEnum
from DBDofusUnity.dofus_unity_reader.grid.map_point import MapPoint
from src.core.engine.contexts import MapMovementContext
from src.core.engine.dungeons.dungeon_info import BLACKSMITH_DUNGEON, BWORK_DUNGEON, SCARAFLEAF_DUNGEON, TOFU_DUNGEON, DungeonInfo
from src.core.engine.movements.map.map_data_adapter import DataMapProvider


@pytest.mark.parametrize("info,map_id,cell_id", [
    (SCARAFLEAF_DUNGEON, 94111744, 384),
    (TOFU_DUNGEON, 96206850, 371),
    (BWORK_DUNGEON, 104599041, 372),
    (BLACKSMITH_DUNGEON, 87297537, 174),
    (BLACKSMITH_DUNGEON, 87296517, 178),
])
def test_fall_cells_are_blocked_for_every_walk_but_not_combat(
    info: DungeonInfo, map_id: int, cell_id: int,
) -> None:
    graph = WorldGraphReader()
    assert any(
        transition.m_type == TransitionTypeEnum.MAP_ACTION and transition.m_cellId == cell_id
        for vertex in graph.get_vertexes(map_id)
        for edge in graph.get_outgoing_edges_from_vertex(vertex)
        if edge.m_to.m_mapId != info.room_transitions[map_id]
        for transition in edge.m_transitions
    )
    provider = DataMapProvider()
    for in_fight in (False, True):
        provider.set_context(MapMovementContext(
            map_id=map_id, in_fight=in_fight, obstacle_on_cell_id={}, occupied_cell_ids=frozenset(),
        ))
        cell = MapReader().get_cell_data_by_cell_id(map_id, cell_id)
        assert cell.movDuringRP
        assert provider.can_mov_to_mp(MapPoint.from_cell_id(cell_id)) == (in_fight and cell.movDuringFight)
    assert cell_id in info.room_avoid_cells[map_id]


@pytest.mark.parametrize("cell_id", [261, 288, 330, 367, 371, 381, 385, 423, 466])
def test_tofu_holes_marked_by_the_user_are_blocked_outside_combat(cell_id: int) -> None:
    provider = DataMapProvider()
    provider.set_context(MapMovementContext(
        map_id=96206850, in_fight=False, obstacle_on_cell_id={}, occupied_cell_ids=frozenset(),
    ))
    assert not provider.can_mov_to_mp(MapPoint.from_cell_id(cell_id))


def test_bwork_blocks_the_whole_zone_containing_the_recorded_fall() -> None:
    provider = DataMapProvider()
    provider.set_context(MapMovementContext(
        map_id=104599041, in_fight=False, obstacle_on_cell_id={}, occupied_cell_ids=frozenset(),
    ))
    cells = MapReader().map_by_id(104599041).mapData.cellsData
    fall_zone = cells[386].linkedZone
    assert fall_zone == cells[372].linkedZone
    for cell in cells:
        if cell.movDuringRP and cell.linkedZone == fall_zone:
            assert not provider.can_mov_to_mp(MapPoint.from_cell_id(cell.cellNumber)), cell.cellNumber
