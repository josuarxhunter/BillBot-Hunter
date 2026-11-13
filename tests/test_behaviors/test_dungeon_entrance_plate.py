from unittest.mock import Mock

import pytest

from DBDofusUnity.datas.protos.non_obf.game.common_pb2 import ActorPositionInformation, ObjectItem, ObjectItemInventory
from DBDofusUnity.datas.protos.non_obf.game.gamemap_pb2 import MapComplementaryInformationEvent, MapObstacle, MapObstacleUpdateEvent
from src.core.bot.bot import Bot
from src.core.engine.dungeons.dungeon_info import SKELETON_DUNGEON


@pytest.mark.parametrize("start_cell", [99, 114])
@pytest.mark.parametrize("opens_before_arrival", [False, True])
def test_skeleton_plate_opens_the_tomb_before_walking_into_the_crypt(
    runtime_bot: Bot, monkeypatch: pytest.MonkeyPatch, start_cell: int, opens_before_arrival: bool,
) -> None:
    behavior = runtime_bot.dungeon_behavior
    state = runtime_bot.game_state
    state.map.map_id = 82314497
    player = ActorPositionInformation(actor_id=state.player.character_id)
    player.disposition.cell_id = start_cell
    state.entity.actor_by_id[player.actor_id] = player
    state.entity.obstacle_on_cell_id[259] = MapObstacle(cell_id=259, state=MapObstacle.OBSTACLE_CLOSED)
    state.inventory.objects_by_uid[1] = ObjectItemInventory(item=ObjectItem(uid=1, gid=1570, quantity=1), position=63)
    trip, move, dialog, finished = Mock(), Mock(), Mock(), Mock()
    monkeypatch.setattr(behavior.auto_trip_smart_behavior, "start", trip)
    monkeypatch.setattr(behavior.traversal_behavior.map_move_behavior, "start", move)
    monkeypatch.setattr(behavior.npc_dialog_behavior, "start", dialog)
    try:
        behavior.start(callback=finished, parent=None, dungeon_info=SKELETON_DUNGEON)
        assert trip.call_args.kwargs["map_ids"] == {82314497}
        trip.call_args.kwargs["callback"](None)
        if start_cell == 99:
            assert move.call_args.kwargs["move_path"].end.cell_id == 114
            player.disposition.cell_id = 114
            move.call_args.kwargs["callback"](None)
        assert move.call_args.kwargs["move_path"].end.cell_id == 99
        player.disposition.cell_id = 99
        opened = [MapObstacle(cell_id=cell, state=MapObstacle.OBSTACLE_OPENED) for cell in (259, 245, 232, 273, 260, 246)]
        if opens_before_arrival:
            state.entity.obstacle_on_cell_id.update({obstacle.cell_id: obstacle for obstacle in opened})
        count = move.call_count
        move.call_args.kwargs["callback"](None)
        if not opens_before_arrival:
            assert move.call_count == count
            state.entity.obstacle_on_cell_id.update({obstacle.cell_id: obstacle for obstacle in opened})
            behavior.event_manager.process_msg(MapObstacleUpdateEvent(obstacles=opened))
        assert move.call_args.kwargs["move_path"].end.cell_id == 259
        dialog.assert_not_called()
        move.call_args.kwargs["callback"](None)
        dialog.assert_not_called()
        state.map.map_id = 87032320
        behavior.event_manager.process_msg(MapComplementaryInformationEvent(map_id=87032320))
        dialog.assert_called_once()
        assert dialog.call_args.kwargs["npc_dialog_info"] is SKELETON_DUNGEON.entrance_npc_info
        finished.assert_not_called()
    finally:
        behavior.stop()
