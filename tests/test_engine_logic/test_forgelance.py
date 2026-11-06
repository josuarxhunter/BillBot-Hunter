from DBDofusUnity.datas.protos.non_obf.game.common_pb2 import (
    CharacterCharacteristic,
    CharacterCharacteristicValue,
    FightRemovableEffect,
    FightRemovableEffectExtendedInformation,
)
from DBDofusUnity.datas.protos.non_obf.game.fight_pb2 import FightEffectsEvent
from DBDofusUnity.datas.protos.non_obf.game.gamemap_pb2 import FightMapInformationEvent
from DBDofusUnity.datas.protos.non_obf.game.spell_pb2 import SpellItem, SpellsEvent
from DBDofusUnity.dofus_unity_reader.game_constants.breed import BreedEnum
from DBDofusUnity.dofus_unity_reader.game_constants.characteristic import CharacteristicEnum
from src.core.bot.bot import Bot
from src.core.engine.fights.attack.spell_filter import get_valid_spells_for_turn
from src.core.frames.fight_frame import FightFrame
from tests.fixtures.game_state import set_game_state


def _stance_event(spell_id: int, target_id: int) -> FightEffectsEvent:
    return FightEffectsEvent(
        effect=FightRemovableEffectExtendedInformation(
            action_id=950,
            effect=FightRemovableEffect(spell_id=spell_id, target_id=target_id),
        )
    )


def test_forgelance_uses_class_attacks_and_recovers_lance(runtime_bot: Bot) -> None:
    game = runtime_bot.game_state
    set_game_state(game, player_cell_id=318, enemy_cell_ids=[347], include_spell_ids=[])
    game.fight.breed_id = 20
    assert game.fight.breed_id == BreedEnum.FORGELANCE
    game.fight.fight_turn = 2
    player_id = game.player.character_id
    frame = next(frame for frame in runtime_bot.frames if isinstance(frame, FightFrame))
    frame.on_spells_event(
        SpellsEvent(
            human_spells=[
                SpellItem(spell_id=23754, spell_level=3),
                SpellItem(spell_id=23263, spell_level=3),
                SpellItem(spell_id=23826, spell_level=2),
                SpellItem(spell_id=369, spell_level=3),
            ]
        )
    )
    selector = runtime_bot.fight_behavior.fight_turn_behavior.breed_ability_selector

    def valid_attacks() -> set[int]:
        return {
            level.spellId
            for level, _, _ in get_valid_spells_for_turn(game.get_attack_context(), runtime_bot.logger)
        }

    assert valid_attacks() == {369}
    frame.on_fight_effects_event(_stance_event(23385, player_id))
    assert valid_attacks() == {369, 23263, 23754}
    assert selector.find_urgent_support_action(game.get_attack_context()) is None

    frame.on_fight_effects_event(_stance_event(23286, player_id + 1))
    assert valid_attacks() == {369, 23263, 23754}

    frame.on_fight_effects_event(_stance_event(23286, player_id))
    assert valid_attacks() == {369}
    context = game.get_attack_context()
    recall = selector.find_urgent_support_action(context)
    assert recall is not None
    from_cell, spell, target_cell = recall
    assert spell.spellId == 23826
    assert from_cell == target_cell == context.player_map_point

    frame.on_fight_effects_event(_stance_event(23385, player_id))
    assert valid_attacks() == {369, 23263, 23754}
    frame.on_fight_map_information_event(FightMapInformationEvent())
    assert valid_attacks() == {369}
    assert selector.find_urgent_support_action(game.get_attack_context()) is None


def test_fire_build_prefers_forgelance_fire_attack_over_off_element_spells(runtime_bot: Bot) -> None:
    game = runtime_bot.game_state
    set_game_state(game, player_cell_id=318, enemy_cell_ids=[347], include_spell_ids=[])
    game.fight.breed_id = 20
    game.fight.fight_turn = 2
    for stat, value in ((CharacteristicEnum.AGILITY, 0), (CharacteristicEnum.INTELLIGENCE, 490)):
        game.fight.update_characteristic(
            CharacterCharacteristic(characteristic_id=stat, value=CharacterCharacteristicValue(total=value))
        )
    frame = next(frame for frame in runtime_bot.frames if isinstance(frame, FightFrame))
    frame.on_spells_event(
        SpellsEvent(
            human_spells=[
                SpellItem(spell_id=23754, spell_level=3),
                SpellItem(spell_id=24015, spell_level=3),
                SpellItem(spell_id=366, spell_level=2),
            ]
        )
    )
    frame.on_fight_effects_event(_stance_event(23385, game.player.character_id))

    attack = runtime_bot.fight_behavior.fight_turn_behavior.attack_selector.find_best_attack_from_mp(
        game.get_attack_context()
    )

    assert attack is not None
    assert attack[1].spellId == 23754
