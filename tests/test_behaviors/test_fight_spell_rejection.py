from collections.abc import Callable
from unittest.mock import Mock

import pytest

from DBDofusUnity.datas.protos.non_obf.game.basic_pb2 import TextInformationEvent
from DBDofusUnity.datas.protos.non_obf.game.game_action_pb2 import (
    GameActionFightCastRequest,
    SequenceEndEvent,
    SequenceType,
)
from DBDofusUnity.datas.protos.non_obf.game.spell_pb2 import SpellItem
from DBDofusUnity.dofus_unity_reader.data_center.data_reader import DataReader
from DBDofusUnity.dofus_unity_reader.grid.map_point import MapPoint
from src.core.behaviors.behavior import BehaviorState
from src.core.behaviors.farms.fight.fight_spell_behavior import FightSpellError
from src.core.bot.bot import Bot
from src.core.engine.fights.los_detector import LosDetector
from tests.fixtures.game_state import set_game_state


@pytest.mark.parametrize("response", ["accepted", "refused", "timeout"])
def test_cast_completes_on_response_or_replans_with_failed_spell_excluded(
    runtime_bot: Bot, monkeypatch: pytest.MonkeyPatch, response: str
) -> None:
    state = runtime_bot.game_state
    set_game_state(state, player_cell_id=318, enemy_cell_ids=[347], include_spell_ids=[])
    turn = runtime_bot.fight_behavior.fight_turn_behavior
    cast = turn.fight_spell_behavior
    advance = Mock()
    monkeypatch.setattr(turn, "_advance_turn", advance)
    callbacks: list[Callable[[], None]] = []

    def schedule(_delay: float, callback: Callable[[], None]) -> None:
        callbacks.append(callback)

    monkeypatch.setattr(turn, "run_timer", schedule)
    monkeypatch.setattr(cast, "run_timer", schedule)
    sent = Mock(side_effect=runtime_bot.event_manager.process_msg)
    runtime_bot.event_manager.on_send_game_callback = sent
    success = Mock()
    turn.start(callback=None, parent=None)
    advance.reset_mock()
    self_cell = state.get_attack_context().player_map_point
    spell = DataReader().spell_lvl_by_spell_id[23826][0]
    turn._schedule_spell_cast(spell, self_cell, self_cell, success)
    callbacks.pop(0)()
    callbacks.pop(0)()
    sent.assert_called_once_with(GameActionFightCastRequest(spell_id=23826, cell=self_cell.cell_id))

    assert state.fight.count_casted_by_spell_id_on_current_turn[23826] == 1

    if response == "accepted":
        runtime_bot.event_manager.process_msg(
            SequenceEndEvent(author_id=state.player.character_id, sequence_type=SequenceType.SPELL)
        )
        success.assert_called_once_with(None)
        assert turn.failed_cast_spell_ids == set()
        advance.assert_not_called()
    elif response == "refused":
        runtime_bot.event_manager.process_msg(
            TextInformationEvent(
                message_type=TextInformationEvent.TextInformationType.TEXT_INFORMATION_ERROR,
                message_id=171,
                parameters=["1", "2", "0"],
            )
        )
        assert 23826 not in state.fight.count_casted_by_spell_id_on_current_turn
        assert 23826 not in state.fight.cast_turn_by_spell_id
    else:
        callbacks.pop(0)()

    if response != "accepted":
        advance.assert_called_once_with(0)
        success.assert_not_called()
        assert turn.failed_cast_spell_ids == {23826}
    assert cast.state is BehaviorState.STOPPED
    turn.stop()


def test_buff_requiring_distance_is_not_selected_as_self_cast(runtime_bot: Bot) -> None:
    state = runtime_bot.game_state
    set_game_state(state, player_cell_id=318, enemy_cell_ids=[347], include_spell_ids=[])
    state.fight.spells = [SpellItem(spell_id=23828, spell_level=1)]
    state.fight.fight_turn = 5

    selector = runtime_bot.fight_behavior.fight_turn_behavior.attack_selector
    assert selector.find_best_self_buff(state.get_attack_context()) is None


def test_cast_is_revalidated_against_current_line_of_sight(
    runtime_bot: Bot, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = runtime_bot.game_state
    set_game_state(state, player_cell_id=318, enemy_cell_ids=[347], include_spell_ids=[])
    cast = runtime_bot.fight_behavior.fight_turn_behavior.fight_spell_behavior
    callbacks: list[Callable[[], None]] = []

    def schedule(_delay: float, callback: Callable[[], None]) -> None:
        callbacks.append(callback)

    monkeypatch.setattr(cast, "run_timer", schedule)
    los = Mock(return_value=False)
    monkeypatch.setattr(LosDetector, "los_between", los)
    sent = Mock()
    runtime_bot.event_manager.on_send_game_callback = sent
    finished = Mock()

    cast.start(
        parent=None,
        callback=finished,
        spell_lvl=DataReader().spell_lvl_by_spell_id[23263][0],
        from_mp=MapPoint.from_cell_id(318),
        target_mp=MapPoint.from_cell_id(347),
    )
    callbacks.pop(0)()
    los.assert_called_once()
    sent.assert_not_called()
    finished.assert_called_once_with(FightSpellError.INVALID_TARGET)
