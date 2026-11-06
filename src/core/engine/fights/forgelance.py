from enum import IntEnum

from DBDofusUnity.dofus_unity_reader.models.datas.spell_levels_root import SpellLevelsRootItem


class ForgelanceStance(IntEnum):
    ARMED = 3360
    DISARMED = 3361


APPLY_STATE_ACTION_ID = 950
STANCE_BY_SPELL_ID = {
    23385: ForgelanceStance.ARMED,
    23286: ForgelanceStance.DISARMED,
}
LANCE_TARGET_WHEN_DISARMED = frozenset({23738, 23841})  # Terre du Milieu, Prélude au Fer
_ARMED_ATTACK_SPELL_IDS = frozenset({23263, 23754})  # Lance à Incendie, Estoc Brûlant


def can_use_armed_attack(spell: SpellLevelsRootItem, state_ids: frozenset[int]) -> bool:
    return (
        spell.spellId in _ARMED_ATTACK_SPELL_IDS
        and spell.statesCriterion == "HS=3360|HS=3589"
        and ForgelanceStance.ARMED in state_ids
    )
