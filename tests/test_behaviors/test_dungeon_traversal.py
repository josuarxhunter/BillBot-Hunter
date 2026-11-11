from unittest.mock import Mock

import pytest

from DBDofusUnity.datas.protos.non_obf.game.common_pb2 import ActorPositionInformation, EntityDisposition
from DBDofusUnity.datas.protos.non_obf.game.gamemap_pb2 import MapComplementaryInformationEvent, MapObstacle
from DBDofusUnity.dofus_unity_reader.grid.map_point import MapPoint
from src.core.bot.bot import Bot
from src.core.behaviors.behavior import BehaviorState
from src.core.behaviors.movements.map_change_behavior import MapChangeError
from src.core.engine.movements.map.path_finding.movement_path import MovementPath


@pytest.fixture(autouse=True)
def player_on_map(runtime_bot: Bot) -> None:
    player_id = runtime_bot.game_state.player.character_id
    runtime_bot.game_state.entity.actor_by_id[player_id] = ActorPositionInformation(
        actor_id=player_id, disposition=EntityDisposition(cell_id=100)
    )


@pytest.mark.parametrize("map_first", [False, True])
def test_traversal_waits_for_edge_completion_and_map_contents(
    runtime_bot: Bot, monkeypatch: pytest.MonkeyPatch, map_first: bool
) -> None:
    behavior = runtime_bot.dungeon_behavior.traversal_behavior
    behavior.game_state.map.map_id = 94116864
    edge_start = Mock()
    finished = Mock()
    monkeypatch.setattr(behavior.edge_behavior, "start", edge_start)
    try:
        behavior.start(callback=finished, parent=None, target_map_id=88080899)
        if map_first:
            behavior.game_state.map.map_id = 88080899
            behavior.event_manager.process_msg(MapComplementaryInformationEvent(map_id=88080899))
            finished.assert_not_called()
            edge_start.call_args.kwargs["callback"](None)
        else:
            edge_start.call_args.kwargs["callback"](None)
            finished.assert_not_called()
            behavior.game_state.map.map_id = 88080899
            behavior.event_manager.process_msg(MapComplementaryInformationEvent(map_id=88080899))
        finished.assert_called_once_with(None)
    finally:
        behavior.stop()


def test_trap_approach_blocks_fall_cells_without_mutating_the_game_map(
    runtime_bot: Bot, monkeypatch: pytest.MonkeyPatch
) -> None:
    behavior = runtime_bot.dungeon_behavior.traversal_behavior
    behavior.game_state.map.map_id = 94111744
    original = behavior.game_state.get_map_movement_context()
    approach = Mock(return_value=MovementPath(MapPoint.from_cell_id(100), MapPoint.from_cell_id(101), []))
    move = Mock()
    edge = Mock()
    monkeypatch.setattr(behavior.path_finding, "get_interactive_near_path", approach)
    monkeypatch.setattr(behavior.map_move_behavior, "start", move)
    monkeypatch.setattr(behavior.edge_behavior, "start", edge)
    try:
        behavior.start(callback=None, parent=None, target_map_id=94112768)
        planned = approach.call_args.args[0]
        assert planned.obstacle_on_cell_id[384].state == MapObstacle.OBSTACLE_CLOSED
        assert behavior.game_state.get_map_movement_context() == original
        edge.assert_not_called()
        move.call_args.kwargs["callback"](None)
        edge.assert_called_once()
    finally:
        behavior.stop()


def test_unknown_passage_fails_instead_of_wandering(
    runtime_bot: Bot, monkeypatch: pytest.MonkeyPatch
) -> None:
    behavior = runtime_bot.dungeon_behavior.traversal_behavior
    behavior.game_state.map.map_id = 94116864
    edge = Mock()
    finished = Mock()
    monkeypatch.setattr(behavior.edge_behavior, "start", edge)

    behavior.start(callback=finished, parent=None, target_map_id=123)

    finished.assert_called_once_with("DUNGEON_PASSAGE_UNAVAILABLE")
    edge.assert_not_called()


def test_transition_timeout_does_not_cancel_an_active_fight(
    runtime_bot: Bot, monkeypatch: pytest.MonkeyPatch
) -> None:
    behavior = runtime_bot.dungeon_behavior.traversal_behavior
    behavior.game_state.map.map_id = 94116864
    finished = Mock()
    monkeypatch.setattr(behavior.edge_behavior, "start", Mock())
    try:
        behavior.start(callback=finished, parent=None, target_map_id=88080899)
        behavior.game_state.fight.in_fight = True
        behavior.on_map_timeout()
        finished.assert_not_called()
        behavior.game_state.fight.in_fight = False
        behavior.on_map_timeout()
        finished.assert_called_once_with(MapChangeError.TIMEOUT)
    finally:
        behavior.game_state.fight.in_fight = False
        behavior.stop()


def test_map_refresh_after_aggression_does_not_abort_the_passage(
    runtime_bot: Bot, monkeypatch: pytest.MonkeyPatch
) -> None:
    behavior = runtime_bot.dungeon_behavior.traversal_behavior
    behavior.game_state.map.map_id = 94116864
    edge = Mock()
    finished = Mock()
    monkeypatch.setattr(behavior.edge_behavior, "start", edge)
    try:
        behavior.start(callback=finished, parent=None, target_map_id=88080899)
        monkeypatch.setattr(behavior.edge_behavior.fight_behavior, "_state", BehaviorState.RUNNING)
        behavior.event_manager.process_msg(MapComplementaryInformationEvent(map_id=94116864))
        finished.assert_not_called()
        monkeypatch.setattr(behavior.edge_behavior.fight_behavior, "_state", BehaviorState.STOPPED)
        edge.call_args.kwargs["callback"](None)
        behavior.game_state.map.map_id = 88080899
        behavior.event_manager.process_msg(MapComplementaryInformationEvent(map_id=88080899))
        finished.assert_called_once_with(None)
    finally:
        behavior.stop()
