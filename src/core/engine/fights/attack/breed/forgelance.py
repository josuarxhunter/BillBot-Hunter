from src.core.engine.contexts import AttackContext
from src.core.engine.fights.attack.breed.types import SupportAction, SupportActionRule
from src.core.engine.fights.attack.spell_filter import resolve_castable_spell_lvl
from src.core.engine.fights.damage_calculator import DamageCalculator
from src.core.engine.fights.forgelance import ForgelanceStance
from src.core.engine.fights.reachable_cells.fight_reachable_cells import FightReachableCells

_CHEVALERIE_SPELL_ID = 23826


def _recall_lance(
    context: AttackContext,
    _reachable_cells: FightReachableCells,
    _damage_calculator: DamageCalculator,
) -> SupportAction | None:
    if ForgelanceStance.DISARMED not in context.own_state_ids:
        return None
    spell = resolve_castable_spell_lvl(context, _CHEVALERIE_SPELL_ID)
    if spell is None:
        return None
    return context.player_map_point, spell, context.player_map_point


URGENT_RULES: list[SupportActionRule] = [_recall_lance]
