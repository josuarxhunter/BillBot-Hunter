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
    player = behavior.game_state.entity.actor_by_id[behavior.game_state.player.character_id]
    player.disposition.cell_id = 486
    original = behavior.game_state.get_map_movement_context()
    plan = Mock(return_value=MovementPath(MapPoint.from_cell_id(486), MapPoint.from_cell_id(374), []))
    move = Mock()
    edge = Mock()
    monkeypatch.setattr(behavior.path_finding, "find_path", plan)
    monkeypatch.setattr(behavior.map_move_behavior, "start", move)
    monkeypatch.setattr(behavior.edge_behavior, "start", edge)
    try:
        behavior.start(callback=None, parent=None, target_map_id=94112768)
        planned = plan.call_args.args[0]
        assert planned.obstacle_on_cell_id[384].state == MapObstacle.OBSTACLE_CLOSED
        assert behavior.game_state.get_map_movement_context() == original
        assert move.call_args.kwargs["move_path"].end.cell_id == 374
        edge.assert_not_called()
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



@pytest.mark.parametrize("start_cell,expected", [
    (486, [374, 287, 283, 282]),
    (374, [287, 283, 282]),
    (287, [283, 282]),
    (283, [282]),
])
def test_scaraleaf_uses_the_user_waypoints_before_approaching_the_door(
    runtime_bot: Bot, monkeypatch: pytest.MonkeyPatch, start_cell: int, expected: list[int]
) -> None:
    behavior = runtime_bot.dungeon_behavior.traversal_behavior
    state = behavior.game_state
    state.map.map_id = 94111744
    player = state.entity.actor_by_id[state.player.character_id]
    player.disposition.cell_id = start_cell
    original = state.get_map_movement_context()
    move = Mock()
    edge = Mock()
    monkeypatch.setattr(behavior.map_move_behavior, "start", move)
    monkeypatch.setattr(behavior.edge_behavior, "start", edge)
    try:
        behavior.start(callback=None, parent=None, target_map_id=94112768)
        for index, destination in enumerate(expected):
            edge.assert_not_called()
            assert move.call_count == index + 1
            path = move.call_args.kwargs["move_path"]
            assert path.end.cell_id == destination
            cells = {element.step.cell_id for element in path.path} | {path.end.cell_id}
            assert {384, 441, 429}.isdisjoint(cells)
            player.disposition.cell_id = destination
            move.call_args.kwargs["callback"](None)
        edge.assert_called_once()
        assert state.get_map_movement_context().obstacle_on_cell_id == original.obstacle_on_cell_id
    finally:
        behavior.stop()


def test_scaraleaf_door_does_not_replan_an_unprotected_walk(
    runtime_bot: Bot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from DBDofusUnity.datas.protos.non_obf.game.common_pb2 import InteractiveElement
    from DBDofusUnity.datas.protos.non_obf.game.interactive_element_pb2 import InteractiveUseRequest
    behavior = runtime_bot.dungeon_behavior.traversal_behavior
    state = behavior.game_state
    state.map.map_id = 94111744
    player = state.entity.actor_by_id[state.player.character_id]
    player.disposition.cell_id = 486
    state.interactive.interactive_element_by_id[472868] = InteractiveElement(
        element_id=472868, on_current_map=True,
        enabled_skills=[InteractiveElement.InteractiveElementSkill(skill_id=184, skill_instance_uid=123)],
    )
    move = Mock()
    send = Mock()
    monkeypatch.setattr(behavior.map_move_behavior, "start", move)
    monkeypatch.setattr(behavior.event_manager, "send", send)
    try:
        behavior.start(callback=None, parent=None, target_map_id=94112768)
        for destination in (374, 287, 283, 282):
            path = move.call_args.kwargs["move_path"]
            assert path.end.cell_id == destination
            player.disposition.cell_id = destination
            move.call_args.kwargs["callback"](None)
        assert move.call_count == 4
        request = send.call_args.args[0]
        assert isinstance(request, InteractiveUseRequest)
        assert request.element_id == 472868
    finally:
        behavior.stop()


def test_waypoint_is_not_skipped_when_movement_did_not_reach_it(runtime_bot: Bot, monkeypatch: pytest.MonkeyPatch) -> None:
    from src.core.behaviors.movements.map_move_behavior import MapMoveError
    behavior = runtime_bot.dungeon_behavior.traversal_behavior
    state = behavior.game_state
    state.map.map_id = 94111744
    state.entity.actor_by_id[state.player.character_id].disposition.cell_id = 486
    move = Mock()
    finished = Mock()
    monkeypatch.setattr(behavior.map_move_behavior, "start", move)
    behavior.start(callback=finished, parent=None, target_map_id=94112768)
    move.call_args.kwargs["callback"](None)
    assert move.call_count == 1
    finished.assert_called_once_with(MapMoveError.CANCELED_MOVEMENT)


def test_pause_mid_segment_preserves_the_next_waypoint(runtime_bot: Bot, monkeypatch: pytest.MonkeyPatch) -> None:
    behavior = runtime_bot.dungeon_behavior.traversal_behavior
    state = behavior.game_state
    state.map.map_id = 94111744
    player = state.entity.actor_by_id[state.player.character_id]
    player.disposition.cell_id = 486
    move = Mock()
    monkeypatch.setattr(behavior.map_move_behavior, "start", move)
    try:
        behavior.start(callback=None, parent=None, target_map_id=94112768)
        player.disposition.cell_id = 402
        behavior.stop()
        behavior.start(callback=None, parent=None, target_map_id=94112768)
        assert move.call_args.kwargs["move_path"].end.cell_id == 374
    finally:
        behavior.stop()


def test_waypoint_detour_is_refused_instead_of_crossing_unknown_cells(runtime_bot: Bot, monkeypatch: pytest.MonkeyPatch) -> None:
    from src.core.engine.movements.map.path_finding.path_element import PathElement
    behavior = runtime_bot.dungeon_behavior.traversal_behavior
    state = behavior.game_state
    state.map.map_id = 94111744
    state.entity.actor_by_id[state.player.character_id].disposition.cell_id = 486
    start = MapPoint.from_cell_id(486)
    destination = MapPoint.from_cell_id(374)
    detour = MapPoint.from_cell_id(471)
    path = MovementPath(start, destination, [PathElement(detour, detour.orientation_to(destination))])
    monkeypatch.setattr(behavior.path_finding, "find_path", Mock(return_value=path))
    move = Mock()
    finished = Mock()
    monkeypatch.setattr(behavior.map_move_behavior, "start", move)
    behavior.start(callback=finished, parent=None, target_map_id=94112768)
    finished.assert_called_once_with("DUNGEON_WAYPOINT_DETOUR_REFUSED")
    move.assert_not_called()


@pytest.mark.parametrize("start_cell,waypoints", [
    (452, (396, 301, 273, 260, 289, 262)),
    (301, (273, 260, 289, 262)),
])
def test_tofu_room_two_follows_the_marked_route_without_crossing_holes(
    runtime_bot: Bot, monkeypatch: pytest.MonkeyPatch, start_cell: int, waypoints: tuple[int, ...],
) -> None:
    behavior = runtime_bot.dungeon_behavior.traversal_behavior
    state = behavior.game_state
    state.map.map_id = 96206850
    player = state.entity.actor_by_id[state.player.character_id]
    player.disposition.cell_id = start_cell
    move, edge, finished = Mock(), Mock(), Mock()
    monkeypatch.setattr(behavior.map_move_behavior, "start", move)
    monkeypatch.setattr(behavior.edge_behavior, "start", edge)
    holes = {261, 288, 330, 367, 371, 381, 385, 423, 466}
    try:
        behavior.start(callback=finished, parent=None, target_map_id=96206848)
        for destination in waypoints:
            finished.assert_not_called()
            edge.assert_not_called()
            path = move.call_args.kwargs["move_path"]
            assert path.end.cell_id == destination
            assert holes.isdisjoint({step.step.cell_id for step in path.path} | {path.end.cell_id})
            player.disposition.cell_id = destination
            move.call_args.kwargs["callback"](None)
        # Any final approach must also avoid the holes before using the door.
        if not edge.called:
            path = move.call_args.kwargs["move_path"]
            assert holes.isdisjoint({step.step.cell_id for step in path.path} | {path.end.cell_id})
            player.disposition.cell_id = path.end.cell_id
            move.call_args.kwargs["callback"](None)
        edge.assert_called_once()
        finished.assert_not_called()
    finally:
        behavior.stop()


@pytest.mark.parametrize("start_cell,route", [
    (396, (381, 367, 353, 340, 326, 313, 299, 300, 287, 301, 316)),
    (470, (456, 442, 429, 415, 401, 387, 374, 359, 345, 330, 316)),
    (367, (353, 340, 326, 313, 299, 300, 287, 301, 316)),
    (402, (415, 401, 387, 374, 359, 345, 330, 316)),
])
def test_bwork_approach_goes_around_the_entire_marked_hole(
    runtime_bot: Bot, monkeypatch: pytest.MonkeyPatch, start_cell: int, route: tuple[int, ...],
) -> None:
    behavior = runtime_bot.dungeon_behavior.traversal_behavior
    state = behavior.game_state
    state.map.map_id = 104599041
    player = state.entity.actor_by_id[state.player.character_id]
    player.disposition.cell_id = start_cell
    move, edge, finished = Mock(), Mock(), Mock()
    monkeypatch.setattr(behavior.map_move_behavior, "start", move)
    monkeypatch.setattr(behavior.edge_behavior, "start", edge)
    holes = {
        328, 329, 342, 343, 344, 355, 356, 357, 358, 369, 370, 371, 372, 383, 384, 385, 386,
        397, 398, 399, 400, 411, 412, 413, 426, 427,
    }
    try:
        behavior.start(callback=finished, parent=None, target_map_id=104595971)
        for destination in route:
            finished.assert_not_called()
            edge.assert_not_called()
            path = move.call_args.kwargs["move_path"]
            assert path.end.cell_id == destination
            assert holes.isdisjoint({step.step.cell_id for step in path.path} | {path.end.cell_id})
            player.disposition.cell_id = destination
            move.call_args.kwargs["callback"](None)
        assert player.disposition.cell_id == 316
        # The footprint also applies to movement replanned outside this traversal.
        provider = behavior.path_finding.data_map_provider
        provider.set_context(state.get_map_movement_context())
        assert all(not provider.can_mov_to_mp(MapPoint.from_cell_id(cell)) for cell in holes)
        edge.assert_called_once()
    finally:
        behavior.stop()


def test_waypoint_completion_during_a_fall_waits_for_the_loaded_map(
    runtime_bot: Bot, monkeypatch: pytest.MonkeyPatch,
) -> None:
    behavior = runtime_bot.dungeon_behavior.traversal_behavior
    state = runtime_bot.game_state
    state.map.map_id = 104599041
    state.entity.actor_by_id[state.player.character_id].disposition.cell_id = 401
    move, finished = Mock(), Mock()
    monkeypatch.setattr(behavior.map_move_behavior, "start", move)
    try:
        behavior.start(callback=finished, parent=None, target_map_id=104595971)
        state.map.map_id = 104599043
        state.entity.actor_by_id.clear()
        move.call_args.kwargs["callback"](None)
        finished.assert_not_called()
        behavior.event_manager.process_msg(MapComplementaryInformationEvent(map_id=104599043))
        finished.assert_called_once_with(MapChangeError.UNEXPECTED_NEW_MAP)
    finally:
        behavior.stop()
