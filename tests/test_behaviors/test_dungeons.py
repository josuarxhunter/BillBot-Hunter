from collections.abc import Iterator
from typing import cast
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from DBDofusUnity.datas.protos.non_obf.game.gamemap_pb2 import MapComplementaryInformationEvent
from DBDofusUnity.datas.protos.non_obf.game.common_pb2 import ObjectEffect, ObjectItem, ObjectItemInventory
from DBDofusUnity.datas.protos.non_obf.game.npc_pb2 import NpcDialogQuestionEvent
from DBDofusUnity.dofus_unity_reader.game_constants.item import ItemEnum
from src.controller.settings import SettingsService
from src.core.behaviors.behavior import BehaviorState
from src.core.behaviors.quests import dungeon_behavior as module
from src.core.behaviors.quests.dungeon_behavior import DungeonBehavior, DungeonError
from src.core.bot.bot import Bot
from src.core.config import DungeonSettings
from src.core.engine.dungeons.dungeon_access import DungeonAccess, get_dungeon_access
from src.core.engine.dungeons.dungeon_info import (
    BOUFTOU_ROYAL_DUNGEON as ROYAL,
    GRANGE_TOURNESOL_DUNGEON as FIELDS,
    DungeonInfo,
)
from src.core.engine.npcs.dialog_turn import DialogTurn, DialogVariants
from src.core.engine.dungeons.dungeon_info import (
    BLACKSMITH_DUNGEON,
    LARVA_DUNGEON,
    SCARAFLEAF_DUNGEON,
    TOFU_DUNGEON,
)

OUTSIDE_MAP_ID = 88090898


@pytest.mark.parametrize("sequence", [False, True])
def test_larvae_is_blocked_before_starting_any_dungeon(
    runtime_bot: Bot, monkeypatch: pytest.MonkeyPatch, sequence: bool
) -> None:
    behavior = runtime_bot.dungeon_behavior
    travel = Mock()
    finished = Mock()
    monkeypatch.setattr(behavior.auto_trip_smart_behavior, "start", travel)
    preferences = DungeonSettings(
        dungeon_id=LARVA_DUNGEON.dungeon.id,
        follow_sequence=sequence,
        sequence=(FIELDS.dungeon.id, LARVA_DUNGEON.dungeon.id),
    )
    behavior.start(callback=finished, parent=None, preferences=preferences)
    finished.assert_called_once_with(DungeonError.PARTY_REQUIRED)
    travel.assert_not_called()


@pytest.mark.parametrize(
    "info,map_id,target",
    [
        (SCARAFLEAF_DUNGEON, 94109696, 94110720),
        (SCARAFLEAF_DUNGEON, 94111746, 94111744),
        (TOFU_DUNGEON, 96206852, 96206850),
        (BLACKSMITH_DUNGEON, 87297537, 87294467),
    ],
)
def test_transit_rooms_advance_instead_of_waiting_for_monsters(
    runtime_bot: Bot, monkeypatch: pytest.MonkeyPatch, info: DungeonInfo, map_id: int, target: int
) -> None:
    behavior = runtime_bot.dungeon_behavior
    behavior.game_state.map.map_id = map_id
    traverse = Mock()
    attack = Mock()
    monkeypatch.setattr(behavior.traversal_behavior, "start", traverse)
    monkeypatch.setattr(behavior.attacker_behavior, "start", attack)
    try:
        behavior.start(callback=None, parent=None, dungeon_info=info)
        assert traverse.call_args.kwargs["target_map_id"] == target
        attack.assert_not_called()
    finally:
        behavior.stop()


def test_scarafeuille_exit_uses_the_passage_instead_of_a_dialogue(
    runtime_bot: Bot, monkeypatch: pytest.MonkeyPatch
) -> None:
    behavior = runtime_bot.dungeon_behavior
    info = SCARAFLEAF_DUNGEON
    behavior.game_state.map.map_id = info.exit_dialog_map_id
    traverse = Mock()
    dialog = Mock()
    finished = Mock()
    monkeypatch.setattr(behavior.traversal_behavior, "start", traverse)
    monkeypatch.setattr(behavior.npc_dialog_behavior, "start", dialog)
    try:
        behavior.start(callback=finished, parent=None, dungeon_info=info)
        assert traverse.call_args.kwargs["target_map_id"] == info.dungeon.exitMapId
        dialog.assert_not_called()
        behavior.game_state.map.map_id = info.dungeon.exitMapId
        traverse.call_args.kwargs["callback"](None)
        finished.assert_called_once_with(None)
    finally:
        behavior.stop()


@pytest.mark.parametrize("map_first", [False, True])
def test_entrance_waits_for_the_dialogue_and_loaded_room(
    dungeon: tuple[DungeonBehavior, Mock, Mock], monkeypatch: pytest.MonkeyPatch, map_first: bool
) -> None:
    behavior, travel, finished = dungeon
    attack = Mock()
    monkeypatch.setattr(behavior.attacker_behavior, "start", attack)
    behavior.start(callback=finished, parent=None, preferences=DungeonSettings(dungeon_id=FIELDS.dungeon.id))
    travel.call_args.kwargs["callback"](None)
    dialog = cast(Mock, behavior.npc_dialog_behavior.start)
    map_id = FIELDS.dungeon.mapIds[0]
    behavior.game_state.map.map_id = map_id
    message = MapComplementaryInformationEvent(map_id=map_id)
    if map_first:
        behavior.event_manager.process_msg(message)
        attack.assert_not_called()
        dialog.call_args.kwargs["callback"](None)
    else:
        dialog.call_args.kwargs["callback"](None)
        attack.assert_not_called()
        behavior.event_manager.process_msg(message)
    attack.assert_called_once()
    finished.assert_not_called()


def test_empty_combat_room_eventually_stops_with_no_progress(
    dungeon: tuple[DungeonBehavior, Mock, Mock], monkeypatch: pytest.MonkeyPatch
) -> None:
    behavior, _travel, finished = dungeon
    monkeypatch.setattr(module, "monotonic", Mock(return_value=0))
    attack = Mock()
    monkeypatch.setattr(behavior.attacker_behavior, "start", attack)
    behavior.game_state.map.map_id = FIELDS.dungeon.mapIds[0]
    behavior.start(callback=finished, parent=None, dungeon_info=FIELDS)
    monkeypatch.setattr(module, "monotonic", Mock(return_value=float("inf")))

    attack.call_args.kwargs["callback"](None, 0)

    finished.assert_called_once_with(DungeonError.NO_PROGRESS)


@pytest.fixture
def dungeon(
    runtime_bot: Bot, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[DungeonBehavior, Mock, Mock]]:
    behavior = runtime_bot.dungeon_behavior
    behavior.game_state.map.map_id = OUTSIDE_MAP_ID
    travel = Mock()
    finished = Mock()
    monkeypatch.setattr(behavior.auto_trip_smart_behavior, "start", travel)
    monkeypatch.setattr(behavior.npc_dialog_behavior, "start", Mock())
    monkeypatch.setattr(module, "get_dungeon_access", Mock(return_value=DungeonAccess.KEYRING))
    yield behavior, travel, finished
    behavior.stop()


def leave_dungeon(behavior: DungeonBehavior, info: DungeonInfo, *, map_first: bool = False) -> None:
    behavior.game_state.map.map_id = info.exit_dialog_map_id
    behavior.exit_dungeon(info)
    behavior.game_state.map.map_id = OUTSIDE_MAP_ID
    message = MapComplementaryInformationEvent(map_id=OUTSIDE_MAP_ID)
    if map_first:
        behavior.event_manager.process_msg(message)
        behavior.on_exit_npc_dialog_behavior_finished(None)
    else:
        behavior.on_exit_npc_dialog_behavior_finished(None)
        behavior.event_manager.process_msg(message)


def test_dungeon_preferences_persist_independently_per_account(monkeypatch: pytest.MonkeyPatch) -> None:
    service = SettingsService()
    sequence = DungeonSettings(
        dungeon_id=ROYAL.dungeon.id,
        follow_sequence=True,
        sequence=(ROYAL.dungeon.id, FIELDS.dungeon.id),
    )
    service.update_dungeons(101, sequence)
    service.update_dungeons(202, DungeonSettings(dungeon_id=FIELDS.dungeon.id))
    monkeypatch.setattr(service, "_settings", None)

    assert service.dungeons(101) == sequence
    assert service.dungeons(202).dungeon_id == FIELDS.dungeon.id
    assert service.dungeons(303) == DungeonSettings()


def test_sequence_requires_at_least_one_dungeon() -> None:
    with pytest.raises(ValidationError, match="Add at least one dungeon"):
        DungeonSettings(follow_sequence=True)


def test_single_selection_ignores_disabled_sequence(dungeon: tuple[DungeonBehavior, Mock, Mock]) -> None:
    behavior, travel, finished = dungeon
    behavior.start(
        callback=finished,
        parent=None,
        preferences=DungeonSettings(dungeon_id=ROYAL.dungeon.id, sequence=(FIELDS.dungeon.id,)),
    )
    assert travel.call_args.kwargs["map_ids"] == {ROYAL.entrance_npc_info.npc_map_id}

    leave_dungeon(behavior, ROYAL)

    finished.assert_called_once_with(None)
    assert travel.call_count == 1
    assert behavior.state is BehaviorState.STOPPED


@pytest.mark.parametrize("map_first", [False, True])
def test_sequence_runs_once_in_configured_order(
    dungeon: tuple[DungeonBehavior, Mock, Mock], map_first: bool
) -> None:
    behavior, travel, finished = dungeon
    sequence = (ROYAL, FIELDS)
    behavior.start(
        callback=finished,
        parent=None,
        preferences=DungeonSettings(
            follow_sequence=True, sequence=tuple(info.dungeon.id for info in sequence)
        ),
    )

    for index, info in enumerate(sequence):
        assert travel.call_args.kwargs["map_ids"] == {info.entrance_npc_info.npc_map_id}
        assert travel.call_count == index + 1
        finished.assert_not_called()
        leave_dungeon(behavior, info, map_first=map_first)

    finished.assert_called_once_with(None)
    assert travel.call_count == len(sequence)


def test_planned_dungeon_uses_saved_account_selection(dungeon: tuple[DungeonBehavior, Mock, Mock]) -> None:
    behavior, travel, finished = dungeon
    SettingsService().update_dungeons(behavior.account_id, DungeonSettings(dungeon_id=ROYAL.dungeon.id))

    behavior.start(callback=finished, parent=None)

    assert travel.call_args.kwargs["map_ids"] == {ROYAL.entrance_npc_info.npc_map_id}


def test_recovery_ignores_saved_sequence(dungeon: tuple[DungeonBehavior, Mock, Mock]) -> None:
    behavior, travel, finished = dungeon
    SettingsService().update_dungeons(
        behavior.account_id, DungeonSettings(follow_sequence=True, sequence=(ROYAL.dungeon.id,))
    )
    behavior.game_state.map.map_id = FIELDS.exit_dialog_map_id

    behavior.start(callback=finished, parent=None, dungeon_info=FIELDS)
    leave_dungeon(behavior, FIELDS)

    finished.assert_called_once_with(None)
    travel.assert_not_called()


def test_no_key_for_next_dungeon_stops_sequence(
    dungeon: tuple[DungeonBehavior, Mock, Mock], monkeypatch: pytest.MonkeyPatch
) -> None:
    behavior, travel, finished = dungeon
    monkeypatch.setattr(module, "get_dungeon_access", Mock(side_effect=[DungeonAccess.KEYRING, None]))
    behavior.start(
        callback=finished,
        parent=None,
        preferences=DungeonSettings(follow_sequence=True, sequence=(ROYAL.dungeon.id, FIELDS.dungeon.id)),
    )

    leave_dungeon(behavior, ROYAL)

    finished.assert_called_once_with(DungeonError.NO_KEY_ACCESS)
    assert travel.call_count == 1


def test_travel_error_stops_sequence(dungeon: tuple[DungeonBehavior, Mock, Mock]) -> None:
    behavior, travel, finished = dungeon
    behavior.start(
        callback=finished,
        parent=None,
        preferences=DungeonSettings(follow_sequence=True, sequence=(ROYAL.dungeon.id, FIELDS.dungeon.id)),
    )
    callback = travel.call_args.kwargs["callback"]
    callback("PATH_NOT_FOUND")

    finished.assert_called_once_with("PATH_NOT_FOUND")
    assert travel.call_count == 1


def test_unknown_dungeon_is_rejected_before_travel(dungeon: tuple[DungeonBehavior, Mock, Mock]) -> None:
    behavior, travel, finished = dungeon
    behavior.start(callback=finished, parent=None, preferences=DungeonSettings(dungeon_id=999999))

    finished.assert_called_once_with(DungeonError.UNSUPPORTED_DUNGEON)
    travel.assert_not_called()


def test_missing_keys_have_no_access(runtime_bot: Bot) -> None:
    assert get_dungeon_access(ROYAL, {}, runtime_bot.logger) is None


def test_manual_dungeon_action_receives_preferences(
    runtime_bot: Bot, monkeypatch: pytest.MonkeyPatch
) -> None:
    preferences = DungeonSettings(dungeon_id=ROYAL.dungeon.id)
    started = Mock()
    monkeypatch.setattr(runtime_bot.dungeon_behavior, "start", started)
    coordinator = runtime_bot.behavior_coordinator
    monkeypatch.setattr(coordinator, "play_action", Mock())

    runtime_bot.bot_signals.play_dungeons.emit(preferences)

    play_action = cast(Mock, coordinator.play_action)
    action = play_action.call_args.args[0]
    action(Mock())
    assert started.call_args.kwargs["preferences"] == preferences


@pytest.mark.parametrize(
    "info,key_gid,key_reply,keyring_reply", [(FIELDS, 8143, 2802, 6615), (ROYAL, 1568, 10529, 10530)]
)
@pytest.mark.parametrize("keyring_available", [False, True])
@pytest.mark.parametrize("automatic", [False, True])
def test_entry_uses_the_available_key_and_matching_dialogue(
    runtime_bot: Bot,
    monkeypatch: pytest.MonkeyPatch,
    info: DungeonInfo,
    key_gid: int,
    key_reply: int,
    keyring_reply: int,
    keyring_available: bool,
    automatic: bool,
) -> None:
    behavior = runtime_bot.dungeon_behavior
    behavior.game_state.map.map_id = OUTSIDE_MAP_ID
    behavior.game_state.inventory.objects_by_uid.clear()
    behavior.game_state.inventory.objects_by_uid.update(
        {
            1: ObjectItemInventory(item=ObjectItem(uid=1, gid=key_gid, quantity=1)),
            2: ObjectItemInventory(
                item=ObjectItem(
                    uid=2,
                    gid=ItemEnum.KEY_RING,
                    quantity=1,
                    effects=[ObjectEffect(value_int=key_gid)] if keyring_available else [],
                )
            ),
        }
    )
    travel = Mock()
    dialog = Mock()
    finished = Mock()
    monkeypatch.setattr(behavior.auto_trip_smart_behavior, "start", travel)
    monkeypatch.setattr(behavior.npc_dialog_behavior, "start", dialog)
    try:
        behavior.start(
            callback=finished,
            parent=None,
            preferences=DungeonSettings(dungeon_id=None if automatic else info.dungeon.id),
        )
        assert travel.call_args.kwargs["map_ids"] == {info.entrance_npc_info.npc_map_id}
        travel.call_args.kwargs["callback"](None)
        turns = cast(list[list[DialogTurn]], dialog.call_args.kwargs["turn_variants"])
        variants = DialogVariants.from_turn_variants(turns)
        question = NpcDialogQuestionEvent()
        question.visible_replies.add().reply_id = keyring_reply
        question.visible_replies.add().reply_id = key_reply
        reply = variants.take_reply_for(question)

        assert reply is not None
        assert reply.reply_id == (keyring_reply if keyring_available else key_reply)
        finished.assert_not_called()
    finally:
        behavior.stop()


def test_key_disappearing_during_travel_stops_before_dialogue(
    runtime_bot: Bot, monkeypatch: pytest.MonkeyPatch
) -> None:
    behavior = runtime_bot.dungeon_behavior
    behavior.game_state.map.map_id = OUTSIDE_MAP_ID
    behavior.game_state.inventory.objects_by_uid.clear()
    behavior.game_state.inventory.objects_by_uid.update(
        {
            1: ObjectItemInventory(item=ObjectItem(uid=1, gid=1568, quantity=1)),
        }
    )
    travel = Mock()
    dialog = Mock()
    finished = Mock()
    monkeypatch.setattr(behavior.auto_trip_smart_behavior, "start", travel)
    monkeypatch.setattr(behavior.npc_dialog_behavior, "start", dialog)
    try:
        behavior.start(
            callback=finished, parent=None, preferences=DungeonSettings(dungeon_id=ROYAL.dungeon.id)
        )
        behavior.game_state.inventory.objects_by_uid.clear()
        travel.call_args.kwargs["callback"](None)

        finished.assert_called_once_with(DungeonError.NO_KEY_ACCESS)
        dialog.assert_not_called()
    finally:
        behavior.stop()


@pytest.mark.parametrize("preferences", [DungeonSettings(), DungeonSettings(dungeon_id=ROYAL.dungeon.id)])
def test_restart_inside_a_dungeon_continues_without_another_key(
    dungeon: tuple[DungeonBehavior, Mock, Mock], monkeypatch: pytest.MonkeyPatch, preferences: DungeonSettings
) -> None:
    behavior, travel, finished = dungeon
    behavior.game_state.map.map_id = FIELDS.exit_dialog_map_id
    monkeypatch.setattr(module, "get_dungeon_access", Mock(return_value=None))
    behavior.start(callback=finished, parent=None, preferences=preferences)
    travel.assert_not_called()
    finished.assert_not_called()
    assert cast(Mock, behavior.npc_dialog_behavior.start).call_args.kwargs["npc_dialog_info"] == FIELDS.exit_npc_info


def test_restart_sequence_continues_at_current_dungeon_instead_of_the_first(
    dungeon: tuple[DungeonBehavior, Mock, Mock]
) -> None:
    behavior, travel, finished = dungeon
    behavior.game_state.map.map_id = ROYAL.exit_dialog_map_id
    behavior.start(callback=finished, parent=None, preferences=DungeonSettings(
        follow_sequence=True, sequence=(FIELDS.dungeon.id, ROYAL.dungeon.id, TOFU_DUNGEON.dungeon.id)
    ))
    travel.assert_not_called()
    leave_dungeon(behavior, ROYAL)
    assert travel.call_args.kwargs["map_ids"] == {TOFU_DUNGEON.entrance_npc_info.npc_map_id}


def test_paused_sequence_with_repeated_dungeons_keeps_its_remaining_work(
    dungeon: tuple[DungeonBehavior, Mock, Mock]
) -> None:
    behavior, travel, finished = dungeon
    preferences = DungeonSettings(follow_sequence=True, sequence=(ROYAL.dungeon.id, ROYAL.dungeon.id, FIELDS.dungeon.id))
    behavior.start(callback=finished, parent=None, preferences=preferences)
    leave_dungeon(behavior, ROYAL)
    behavior.game_state.map.map_id = ROYAL.exit_dialog_map_id
    behavior.stop()
    travel.reset_mock()
    behavior.start(callback=finished, parent=None, preferences=preferences)
    leave_dungeon(behavior, ROYAL)
    assert travel.call_args.kwargs["map_ids"] == {FIELDS.entrance_npc_info.npc_map_id}
    assert travel.call_count == 1
