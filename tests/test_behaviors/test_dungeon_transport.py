from unittest.mock import Mock

import pytest

from DBDofusUnity.datas.protos.non_obf.game.gamemap_pb2 import MapComplementaryInformationEvent
from src.core.behaviors.movements.auto_trip.auto_trip_behavior import AutoTripErrorCode
from src.core.behaviors.quests.dungeon_behavior import DungeonError
from src.core.bot.bot import Bot
from src.core.engine.dungeons.dungeon_info import HESQUE_DUNGEON, KWISMAS_DUNGEON, SYLVAN_DUNGEON, DungeonInfo


@pytest.mark.parametrize("info", [HESQUE_DUNGEON, KWISMAS_DUNGEON, SYLVAN_DUNGEON])
@pytest.mark.parametrize("map_first", [False, True])
def test_unreachable_island_boards_then_waits_for_dialog_and_map(
    runtime_bot: Bot, monkeypatch: pytest.MonkeyPatch, info: DungeonInfo, map_first: bool,
) -> None:
    behavior = runtime_bot.dungeon_behavior
    state = runtime_bot.game_state
    state.inventory.kamas = 1000
    travel, dialog, finished = Mock(), Mock(), Mock()
    monkeypatch.setattr(behavior.auto_trip_smart_behavior, "start", travel)
    monkeypatch.setattr(behavior.npc_dialog_behavior, "start", dialog)
    monkeypatch.setattr(state.entity, "resolve_npc_id", Mock(return_value=-1))
    assert info.access_npc_info is not None
    try:
        behavior.start(callback=finished, parent=None, dungeon_info=info)
        travel.call_args.kwargs["callback"](AutoTripErrorCode.PATH_NOT_FOUND)
        assert travel.call_args.kwargs["map_ids"] == {info.access_npc_info.npc_map_id}
        state.map.map_id = info.access_npc_info.npc_map_id
        travel.call_args.kwargs["callback"](None)
        assert dialog.call_args.kwargs["turn_variants"] == [info.access_turns]
        if map_first:
            state.map.map_id = info.dungeon.entranceMapId
            behavior.event_manager.process_msg(MapComplementaryInformationEvent(map_id=state.map.map_id))
            assert travel.call_count == 2
            dialog.call_args.kwargs["callback"](None)
        else:
            dialog.call_args.kwargs["callback"](None)
            assert travel.call_count == 2
            state.map.map_id = info.dungeon.entranceMapId
            behavior.event_manager.process_msg(MapComplementaryInformationEvent(map_id=state.map.map_id))
        assert travel.call_count == 3
        assert travel.call_args.kwargs["map_ids"] == {info.dungeon.entranceMapId}
        # A failed onward trip cannot board again in a loop.
        travel.call_args.kwargs["callback"](AutoTripErrorCode.PATH_NOT_FOUND)
        finished.assert_called_once_with(DungeonError.ENTRANCE_UNREACHABLE)
    finally:
        behavior.stop()


def test_missing_seasonal_npc_stops_without_opening_a_dialog(runtime_bot: Bot, monkeypatch: pytest.MonkeyPatch) -> None:
    behavior = runtime_bot.dungeon_behavior
    info = KWISMAS_DUNGEON
    assert info.access_npc_info is not None
    runtime_bot.game_state.map.map_id = info.access_npc_info.npc_map_id
    dialog, finished = Mock(), Mock()
    monkeypatch.setattr(behavior.npc_dialog_behavior, "start", dialog)
    monkeypatch.setattr(behavior, "finish", finished)
    behavior.on_access_trip_finished(None, info)
    dialog.assert_not_called()
    finished.assert_called_once_with(DungeonError.ACCESS_UNAVAILABLE)


def test_valonia_fare_is_checked_before_travel(runtime_bot: Bot, monkeypatch: pytest.MonkeyPatch) -> None:
    behavior = runtime_bot.dungeon_behavior
    runtime_bot.game_state.inventory.kamas = 99
    travel, finished = Mock(), Mock()
    monkeypatch.setattr(behavior.auto_trip_smart_behavior, "start", travel)
    monkeypatch.setattr(behavior, "finish", finished)
    behavior.travel_to_access_npc(SYLVAN_DUNGEON)
    travel.assert_not_called()
    finished.assert_called_once_with(DungeonError.ACCESS_UNAVAILABLE)
