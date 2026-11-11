from unittest.mock import Mock

import pytest

from DBDofusUnity.datas.protos.non_obf.game.common_pb2 import ObjectItem, ObjectItemInventory
from DBDofusUnity.dofus_unity_reader.data_center.world_graph_reader import WorldGraphReader
from DBDofusUnity.dofus_unity_reader.game_constants.inventory_position import CharacterInventoryPositionEnum
from src.core.behaviors.movements.auto_trip.auto_trip_behavior import AutoTripErrorCode
from src.core.behaviors.quests.dungeon_behavior import DungeonError
from src.core.bot.bot import Bot
from src.core.engine.dungeons.dungeon_info import KANKREBLATH_DUNGEON, PLAYABLE_DUNGEONS, DungeonInfo


@pytest.fixture
def at_astrub_zaap(runtime_bot: Bot, monkeypatch: pytest.MonkeyPatch) -> Bot:
    state = runtime_bot.game_state
    state.map.map_id = 191105026
    monkeypatch.setattr(type(state.player), "is_sub", property(lambda _player: True))
    state.player.level = 200
    state.player.waypoint_map_ids = [191105026]
    state.inventory.objects_by_uid.clear()
    source = next(iter(WorldGraphReader().get_vertexes(state.map.map_id)))
    monkeypatch.setattr(type(state.map), "curr_vertex", property(lambda _map: source))
    return runtime_bot


@pytest.mark.parametrize("info", [info for info in PLAYABLE_DUNGEONS if info.access_note is None], ids=lambda info: str(info.dungeon.id))
def test_standard_dungeon_entrances_have_a_route_from_astrub(at_astrub_zaap: Bot, info: DungeonInfo) -> None:
    bot = at_astrub_zaap
    travel = bot.dungeon_behavior.auto_trip_smart_behavior.auto_trip_explorator_behavior.auto_trip_zaap_behavior
    assert travel.can_reach({info.entrance_npc_info.npc_map_id}), info.name


@pytest.mark.parametrize("gid,equipped,reachable", [(15990, False, False), (15990, True, True), (31494, False, True), (15991, False, False)])
def test_kankreblath_route_checks_the_miniature_passage_requirement(
    at_astrub_zaap: Bot, gid: int, equipped: bool, reachable: bool
) -> None:
    bot = at_astrub_zaap
    bot.game_state.inventory.objects_by_uid[1] = ObjectItemInventory(
        item=ObjectItem(uid=1, gid=gid, quantity=1),
        position=1 if equipped else CharacterInventoryPositionEnum.InventoryPositionNotEquiped,
    )
    travel = bot.dungeon_behavior.auto_trip_smart_behavior.auto_trip_explorator_behavior.auto_trip_zaap_behavior
    path = travel.auto_trip_behavior.world_path_finder.find_path(
        bot.game_state.get_world_path_context(), bot.game_state.map.curr_vertex,
        {KANKREBLATH_DUNGEON.entrance_npc_info.npc_map_id},
    )
    assert (path is not None) is reachable


def test_unreachable_dungeon_does_not_teleport_or_discover_a_zaap(
    at_astrub_zaap: Bot, monkeypatch: pytest.MonkeyPatch
) -> None:
    travel = at_astrub_zaap.dungeon_behavior.auto_trip_smart_behavior.auto_trip_explorator_behavior
    teleport = Mock()
    finished = Mock()
    monkeypatch.setattr(travel.auto_trip_zaap_behavior, "start", teleport)
    travel.start(callback=finished, parent=None, map_ids={KANKREBLATH_DUNGEON.entrance_npc_info.npc_map_id})
    teleport.assert_not_called()
    finished.assert_called_once_with(AutoTripErrorCode.PATH_NOT_FOUND)


def test_route_failure_reports_an_actionable_dungeon_error(runtime_bot: Bot, monkeypatch: pytest.MonkeyPatch) -> None:
    behavior = runtime_bot.dungeon_behavior
    finished = Mock()
    monkeypatch.setattr(behavior.auto_trip_smart_behavior, "start", Mock())
    behavior.start(callback=finished, parent=None, dungeon_info=KANKREBLATH_DUNGEON)
    behavior.on_auto_trip_smart_behavior_to_entrance_finished(AutoTripErrorCode.PATH_NOT_FOUND, KANKREBLATH_DUNGEON)
    finished.assert_called_once_with(DungeonError.ENTRANCE_UNREACHABLE)


def test_sylvan_uses_a_known_valonia_zaap(at_astrub_zaap: Bot) -> None:
    travel = at_astrub_zaap.dungeon_behavior.auto_trip_smart_behavior.auto_trip_explorator_behavior.auto_trip_zaap_behavior
    at_astrub_zaap.game_state.player.waypoint_map_ids.append(223349001)
    assert travel.reachable_waypoints({223350028}) == [223349001]


def test_failed_walk_does_not_teleport_back_to_the_current_zaap(
    at_astrub_zaap: Bot, monkeypatch: pytest.MonkeyPatch
) -> None:
    bot = at_astrub_zaap
    bot.game_state.inventory.objects_by_uid[1] = ObjectItemInventory(
        item=ObjectItem(uid=1, gid=31494, quantity=1)
    )
    travel = bot.dungeon_behavior.auto_trip_smart_behavior.auto_trip_explorator_behavior.auto_trip_zaap_behavior
    teleport = Mock()
    finished = Mock()
    monkeypatch.setattr(travel.waypoint_behavior, "start", teleport)
    monkeypatch.setattr(travel, "finish", finished)
    from DBDofusUnity.dofus_unity_reader.data_center.data_reader import DataReader
    destination = KANKREBLATH_DUNGEON.entrance_npc_info.npc_map_id
    travel.on_auto_trip_behavior_finished(
        AutoTripErrorCode.PATH_NOT_FOUND, {destination}, [DataReader().map_info_by_map_id[destination]]
    )
    teleport.assert_not_called()
    finished.assert_called_once_with(AutoTripErrorCode.PATH_NOT_FOUND)


@pytest.mark.parametrize("info", [info for info in PLAYABLE_DUNGEONS if info.dungeon.id in {1, 8}], ids=lambda info: str(info.dungeon.id))
def test_dungeon_start_handles_a_known_zaap_with_unsupported_passage_conditions(
    at_astrub_zaap: Bot, monkeypatch: pytest.MonkeyPatch, info: DungeonInfo
) -> None:
    bot = at_astrub_zaap
    bot.game_state.player.waypoint_map_ids = [191105026, 108789760, 120062979]
    bot.game_state.configurable_auto = None
    travel = bot.dungeon_behavior.auto_trip_smart_behavior.auto_trip_explorator_behavior.auto_trip_zaap_behavior
    walk = Mock()
    teleport = Mock()
    finished = Mock()
    monkeypatch.setattr(travel.auto_trip_behavior, "start", walk)
    monkeypatch.setattr(travel.waypoint_behavior, "start", teleport)
    try:
        bot.dungeon_behavior.start(callback=finished, parent=None, dungeon_info=info)
        assert walk.called or teleport.called
        finished.assert_not_called()
    finally:
        bot.dungeon_behavior.stop()


@pytest.mark.parametrize("source_map_id", [191105026, 103549440])
def test_scaraleaf_trip_uses_the_nearby_zaap_from_astrub_and_its_interiors(
    at_astrub_zaap: Bot, monkeypatch: pytest.MonkeyPatch, source_map_id: int
) -> None:
    bot = at_astrub_zaap
    bot.game_state.map.map_id = source_map_id
    source = next(iter(WorldGraphReader().get_vertexes(source_map_id)))
    monkeypatch.setattr(type(bot.game_state.map), "curr_vertex", property(lambda _map: source))
    bot.game_state.player.waypoint_map_ids = [191105026, 88082704, 88212481]
    bot.game_state.configurable_auto = None
    travel = bot.dungeon_behavior.auto_trip_smart_behavior.auto_trip_explorator_behavior.auto_trip_zaap_behavior
    walk = Mock()
    teleport = Mock()
    monkeypatch.setattr(travel.auto_trip_behavior, "start", walk)
    monkeypatch.setattr(travel.waypoint_behavior, "start", teleport)
    try:
        travel.start(callback=None, parent=None, map_ids={88080387})
        teleport.assert_called_once()
        assert teleport.call_args.kwargs["map_id"] == 88212481
        walk.assert_not_called()
    finally:
        travel.stop()
