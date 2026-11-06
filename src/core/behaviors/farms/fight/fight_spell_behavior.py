from collections import defaultdict
from dataclasses import dataclass, field
from enum import StrEnum, auto

from DBDofusUnity.datas.protos.non_obf.game.basic_pb2 import TextInformationEvent
from DBDofusUnity.datas.protos.non_obf.game.common_pb2 import SpellModifierType
from DBDofusUnity.datas.protos.non_obf.game.game_action_pb2 import (
    GameActionFightCastRequest,
    SequenceEndEvent,
    SequenceType,
)
from DBDofusUnity.dofus_unity_reader.game_constants.text_enum import TextEnum
from DBDofusUnity.dofus_unity_reader.grid.map_point import MapPoint
from DBDofusUnity.dofus_unity_reader.models.datas.spell_levels_root import SpellLevelsRootItem
from src.core.behaviors.behavior import BehaviorState
from src.core.behaviors.farms.fight.fight_listener_behavior import FightListenerBehavior
from src.core.engine.fights.attack.cast_validator import can_cast_spell_on_mp
from src.core.engine.fights.attack.positions import get_positions
from src.core.engine.fights.attack.rejection_stat import RejectionStat
from src.core.engine.fights.spell import get_possible_mp_spell
from src.core.engine.fights.spell_modifier import SpellModifiers
from src.services.human_timings import HumanTimingsService

SPELL_CONFIRMATION_TIMEOUT_SECONDS = 3.0


class FightSpellError(StrEnum):
    INVALID_TARGET = auto()
    REFUSED = auto()
    NO_CONFIRMATION = auto()


@dataclass(frozen=True)
class PendingCast:
    request: GameActionFightCastRequest
    turn: int
    previous_count: int
    previous_cast_turn: int | None


@dataclass
class FightSpellBehavior(FightListenerBehavior):
    _pending_cast: PendingCast | None = field(init=False, default=None)

    def run(self, spell_lvl: SpellLevelsRootItem, from_mp: MapPoint, target_mp: MapPoint) -> None:
        self._pending_cast = None
        self.register_fight_death_check()
        self.run_timer(
            HumanTimingsService().get_timing_before_spell_cast(),
            lambda: self._send_cast(spell_lvl, from_mp, target_mp),
        )

    def _send_cast(self, spell_lvl: SpellLevelsRootItem, from_mp: MapPoint, target_mp: MapPoint) -> None:
        context = self.game_state.get_attack_context_if_available()
        if context is None or context.player_map_point != from_mp:
            return self.finish(FightSpellError.INVALID_TARGET)

        spell_id = spell_lvl.spellId
        modifiers_map = context.modifier_by_type_and_spell_id
        possible_cells = get_possible_mp_spell(
            from_mp,
            spell_lvl,
            context.range,
            modifier_range_min=modifiers_map.get((spell_id, SpellModifierType.RANGE_MIN)),
            modifier_range_max=modifiers_map.get((spell_id, SpellModifierType.RANGE_MAX)),
            modifier_cast_line=modifiers_map.get((spell_id, SpellModifierType.CAST_LINE)),
        )
        if target_mp not in possible_cells:
            self.logger.info(
                "Spell %s is out of range from %s to %s", spell_id, from_mp.cell_id, target_mp.cell_id
            )
            return self.finish(FightSpellError.INVALID_TARGET)

        positions = get_positions(context)
        rejections: dict[RejectionStat, int] = defaultdict(int)
        if not can_cast_spell_on_mp(
            context,
            from_mp,
            spell_lvl,
            target_mp,
            SpellModifiers.from_spell(context.range, spell_lvl, modifiers_map),
            positions.entities_mp,
            positions.entities_id_by_mp,
            rejections,
        ):
            self.logger.info(
                "Spell %s is no longer valid from %s to %s: %s",
                spell_id,
                from_mp.cell_id,
                target_mp.cell_id,
                dict(rejections),
            )
            return self.finish(FightSpellError.INVALID_TARGET)

        with self.event_manager.lock:
            if self.state is not BehaviorState.RUNNING:
                return
            pending = PendingCast(
                request=GameActionFightCastRequest(spell_id=spell_id, cell=target_mp.cell_id),
                turn=context.fight_turn,
                previous_count=context.count_casted_by_spell_id_on_current_turn.get(spell_id, 0),
                previous_cast_turn=context.cast_turn_by_spell_id.get(spell_id),
            )
            self._pending_cast = pending
            self.event_manager.on(SequenceEndEvent, self.on_sequence_end_event, originator=self)
            self.event_manager.on(TextInformationEvent, self.on_text_information_event, originator=self)
            self.run_timer(
                SPELL_CONFIRMATION_TIMEOUT_SECONDS,
                lambda: self._finish_pending(pending, FightSpellError.NO_CONFIRMATION),
            )
            self.event_manager.send(pending.request)

    def on_sequence_end_event(self, msg: SequenceEndEvent) -> None:
        if msg.author_id == self.game_state.player.character_id and msg.sequence_type == SequenceType.SPELL:
            if (pending := self._pending_cast) is not None:
                self._finish_pending(pending)

    def on_text_information_event(self, msg: TextInformationEvent) -> None:
        if (
            msg.message_type == TextInformationEvent.TextInformationType.TEXT_INFORMATION_ERROR
            and msg.message_id == TextEnum.SPELL_OUT_OF_RANGE
            and (pending := self._pending_cast) is not None
        ):
            self._finish_pending(pending, FightSpellError.REFUSED)

    def _finish_pending(self, pending: PendingCast, error: FightSpellError | None = None) -> None:
        with self._state_lock:
            if self._pending_cast is not pending:
                return
            self._pending_cast = None
        if error is FightSpellError.REFUSED:
            self._restore_refused_cast(pending)
        self.finish(error)

    def clear_behavior(self) -> None:
        with self._state_lock:
            self._pending_cast = None
        super().clear_behavior()

    def _restore_refused_cast(self, pending: PendingCast) -> None:
        fight = self.game_state.fight
        spell_id = pending.request.spell_id
        counts = fight.count_casted_by_spell_id_on_current_turn
        cast_turns = fight.cast_turn_by_spell_id
        if (
            fight.fight_turn != pending.turn
            or counts.get(spell_id) != pending.previous_count + 1
            or cast_turns.get(spell_id) != pending.turn
        ):
            return
        if pending.previous_count:
            counts[spell_id] = pending.previous_count
        else:
            counts.pop(spell_id, None)
        if pending.previous_cast_turn is None:
            cast_turns.pop(spell_id, None)
        else:
            cast_turns[spell_id] = pending.previous_cast_turn
