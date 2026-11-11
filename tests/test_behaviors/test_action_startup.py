from collections.abc import Callable
from unittest.mock import Mock

import pytest

from DBDofusUnity.datas.protos.non_obf.game.dialog_pb2 import DialogLeaveEvent
from DBDofusUnity.datas.protos.non_obf.game.gamemap_pb2 import MapComplementaryInformationEvent
from src.core.bot.bot import Bot
from src.core.bot.execution import behavior_coordinator as coordinator_module
from src.core.engine.dungeons.dungeon_info import BOUFTOU_ROYAL_DUNGEON as ROYAL
from src.core.states.dialog_state import OpenDialogKind
from tests.fixtures.bot_runtime import make_behavior_coordinator


@pytest.mark.parametrize("recover_dungeon", [False, True])
def test_startup_resumes_fight_and_rechecks_the_dungeon(
    runtime_bot: Bot, monkeypatch: pytest.MonkeyPatch, recover_dungeon: bool
) -> None:
    behavior = runtime_bot.action_startup_behavior
    state = runtime_bot.game_state
    state.map.map_id = ROYAL.dungeon.mapIds[0]
    state.fight.in_fight = True
    fight = Mock()
    dungeon = Mock()
    finished = Mock()
    monkeypatch.setattr(behavior.recovery.fight_behavior, "start", fight)
    monkeypatch.setattr(behavior.recovery.dungeon_behavior, "start", dungeon)
    try:
        behavior.start(callback=finished, parent=None, recover_dungeon=recover_dungeon)
        fight.assert_called_once()
        finished.assert_not_called()
        dungeon.assert_not_called()
        state.fight.in_fight = False
        fight.call_args.kwargs["callback"](None)
        if recover_dungeon:
            assert dungeon.call_args.kwargs["dungeon_info"] is ROYAL
            finished.assert_not_called()
            state.map.map_id = 191105026
            dungeon.call_args.kwargs["callback"](None)
        else:
            dungeon.assert_not_called()
        finished.assert_called_once_with(None)
    finally:
        behavior.stop()


def test_startup_leaves_haven_bag_and_closes_pending_dialog(runtime_bot: Bot) -> None:
    behavior = runtime_bot.action_startup_behavior
    state = runtime_bot.game_state
    state.map.map_id = 191105026
    state.map.is_in_haven_bag = True
    behavior.event_manager.on_send_game_callback = Mock()
    finished = Mock()
    try:
        behavior.start(callback=finished, parent=None)
        finished.assert_not_called()
        state.map.is_in_haven_bag = False
        state.dialog.set_open(OpenDialogKind.NPC_DIALOG)
        behavior.event_manager.process_msg(MapComplementaryInformationEvent(map_id=191105026))
        finished.assert_not_called()
        state.dialog.clear_state()
        behavior.event_manager.process_msg(DialogLeaveEvent())
        finished.assert_called_once_with(None)
    finally:
        behavior.stop()


def test_startup_propagates_recovery_failure(runtime_bot: Bot, monkeypatch: pytest.MonkeyPatch) -> None:
    behavior = runtime_bot.action_startup_behavior
    runtime_bot.game_state.fight.in_fight = True
    fight = Mock()
    monkeypatch.setattr(behavior.recovery.fight_behavior, "start", fight)
    finished = Mock()
    behavior.start(callback=finished, parent=None)
    fight.call_args.kwargs["callback"]("recovery failed")
    finished.assert_called_once_with("recovery failed")


def test_reconnection_prepares_current_state_before_running_the_action(monkeypatch: pytest.MonkeyPatch) -> None:
    coordinator = make_behavior_coordinator()
    def execute(function: Callable[[Callable[[str], None]], None]) -> None:
        function(Mock())

    monkeypatch.setattr(coordinator_module, "run_in_background", execute)
    action = Mock()
    coordinator.play_action(action)
    action.assert_not_called()
    coordinator.is_connected_event.set()
    coordinator.is_ready_to_play_event.set()
    coordinator.run_current_bot_action()
    action.assert_not_called()
    startup = coordinator.action_startup_behavior.start
    assert isinstance(startup, Mock)
    startup.call_args.kwargs["callback"](None)
    action.assert_called_once()


def test_queued_pause_does_not_stop_a_new_action(monkeypatch: pytest.MonkeyPatch) -> None:
    coordinator = make_behavior_coordinator()
    tasks: list[Callable[[Callable[[str], None]], None]] = []
    monkeypatch.setattr(coordinator_module, "run_in_background", tasks.append)
    coordinator.is_connected_event.set()
    coordinator.is_ready_to_play_event.set()
    stop = Mock()
    monkeypatch.setattr(coordinator, "stop_behaviors", stop)
    old = Mock()
    current = Mock()
    coordinator.play_action(old)
    coordinator.on_stop()
    coordinator.play_action(current)
    tasks[2](Mock())
    startup = coordinator.action_startup_behavior.start
    assert isinstance(startup, Mock)
    startup.call_args.kwargs["callback"](None)
    assert stop.call_count == 2
    tasks[0](Mock())
    tasks[1](Mock())
    old.assert_not_called()
    current.assert_called_once()
    assert stop.call_count == 2


def test_startup_waits_for_current_map_to_finish_loading(runtime_bot: Bot) -> None:
    behavior = runtime_bot.action_startup_behavior
    state = runtime_bot.game_state
    state.map.map_id = 191105026
    state.map.is_in_map_transition = True
    finished = Mock()
    try:
        behavior.start(callback=finished, parent=None)
        finished.assert_not_called()
        state.map.is_in_map_transition = False
        behavior.event_manager.process_msg(MapComplementaryInformationEvent(map_id=191105026))
        finished.assert_called_once_with(None)
    finally:
        behavior.stop()


def test_startup_closes_previous_dialog_before_resuming_a_dungeon(
    runtime_bot: Bot, monkeypatch: pytest.MonkeyPatch
) -> None:
    behavior = runtime_bot.action_startup_behavior
    state = runtime_bot.game_state
    state.map.map_id = ROYAL.dungeon.mapIds[0]
    state.dialog.set_open(OpenDialogKind.NPC_DIALOG)
    behavior.event_manager.on_send_game_callback = Mock()
    dungeon = Mock()
    monkeypatch.setattr(behavior.recovery.dungeon_behavior, "start", dungeon)
    try:
        behavior.start(callback=None, parent=None)
        dungeon.assert_not_called()
        state.dialog.clear_state()
        behavior.event_manager.process_msg(DialogLeaveEvent())
        assert dungeon.call_args.kwargs["dungeon_info"] is ROYAL
    finally:
        behavior.stop()


def test_disconnect_before_queued_start_waits_for_reconnection(monkeypatch: pytest.MonkeyPatch) -> None:
    coordinator = make_behavior_coordinator()
    tasks: list[Callable[[Callable[[str], None]], None]] = []
    monkeypatch.setattr(coordinator_module, "run_in_background", tasks.append)
    coordinator.is_connected_event.set()
    coordinator.is_ready_to_play_event.set()
    action = Mock()
    coordinator.play_action(action)
    coordinator.is_connected_event.clear()
    coordinator.is_ready_to_play_event.clear()
    tasks.pop()(Mock())
    startup = coordinator.action_startup_behavior.start
    assert isinstance(startup, Mock)
    startup.assert_not_called()
    action.assert_not_called()
    coordinator.is_connected_event.set()
    coordinator.is_ready_to_play_event.set()
    coordinator.run_current_bot_action()
    tasks.pop()(Mock())
    startup.call_args.kwargs["callback"](None)
    action.assert_called_once()
