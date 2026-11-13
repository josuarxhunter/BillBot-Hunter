from collections.abc import Iterable
from unittest.mock import Mock

import pytest

from DBDofusUnity.datas.protos.non_obf.game.common_pb2 import ObjectItem, ObjectItemInventory
from DBDofusUnity.datas.protos.non_obf.game.inventory_pb2 import ObjectMovementEvent
from DBDofusUnity.dofus_unity_reader.game_constants.characteristic import EffectElement
from DBDofusUnity.dofus_unity_reader.game_constants.inventory_position import (
    CharacterInventoryPositionEnum,
)
from pytest import MonkeyPatch

from src.core.behaviors.items.auto_equipment_from_inventory_behavior import (
    AutoEquipmentFromInventoryBehavior,
)
from src.core.behaviors.items import auto_equipment_from_inventory_behavior
from src.core.events_manager.event_manager import EventManager
from src.core.engine.dungeons.dungeon_info import KANKREBLATH_DUNGEON
from tests.fixtures.game_state import GameStateContext


def _item(uid: int) -> ObjectItemInventory:
    return ObjectItemInventory(item=ObjectItem(uid=uid, gid=uid, quantity=1))


def test_best_loadout_keeps_a_pair_that_is_only_better_together(
    game_state_ctx: GameStateContext, monkeypatch: MonkeyPatch
) -> None:
    behavior = AutoEquipmentFromInventoryBehavior(
        event_manager=EventManager(_logger=game_state_ctx.logger),
        game_state=game_state_ctx.game_state,
        _logger=game_state_ctx.logger,
    )
    hat = _item(1)
    cape = _item(2)
    dropped_hat = _item(3)
    dropped_cape = _item(4)
    scores_by_uids = {
        frozenset({1, 2}): 100.0,
        frozenset({3, 2}): 90.0,
        frozenset({1, 4}): 90.0,
        frozenset({3, 4}): 120.0,
    }
    def score(items: Iterable[ObjectItemInventory], _elem: EffectElement) -> float:
        return scores_by_uids[frozenset(item.item.uid for item in items)]

    def positions(gid: int) -> tuple[CharacterInventoryPositionEnum, ...]:
        return {
            3: (CharacterInventoryPositionEnum.AccessoryPositionHat,),
            4: (CharacterInventoryPositionEnum.AccessoryPositionCape,),
        }.get(gid, ())

    monkeypatch.setattr(
        auto_equipment_from_inventory_behavior,
        "equipment_score",
        score,
    )
    monkeypatch.setattr(
        auto_equipment_from_inventory_behavior,
        "get_equipment_positions",
        positions,
    )
    current = {
        CharacterInventoryPositionEnum.AccessoryPositionHat: hat,
        CharacterInventoryPositionEnum.AccessoryPositionCape: cape,
    }

    best = behavior._best_loadout(current, [dropped_hat, dropped_cape])

    assert best == {
        CharacterInventoryPositionEnum.AccessoryPositionHat: dropped_hat,
        CharacterInventoryPositionEnum.AccessoryPositionCape: dropped_cape,
    }


@pytest.mark.parametrize("map_id,keep_wand", [
    (KANKREBLATH_DUNGEON.dungeon.mapIds[0], True),
    (KANKREBLATH_DUNGEON.exit_dialog_map_id, True),
    (191105026, False),
])
def test_kankreblath_preserves_access_wand_but_still_equips_other_upgrades(
    game_state_ctx: GameStateContext, monkeypatch: MonkeyPatch, map_id: int, keep_wand: bool,
) -> None:
    state = game_state_ctx.game_state
    state.map.map_id = map_id
    behavior = AutoEquipmentFromInventoryBehavior(
        event_manager=EventManager(_logger=game_state_ctx.logger), game_state=state, _logger=game_state_ctx.logger,
    )
    weapon = CharacterInventoryPositionEnum.AccessoryPositionWeapon
    hat = CharacterInventoryPositionEnum.AccessoryPositionHat
    unequipped = CharacterInventoryPositionEnum.InventoryPositionNotEquiped
    state.inventory.objects_by_uid.clear()
    state.inventory.objects_by_uid.update({
        1: ObjectItemInventory(item=ObjectItem(uid=1, gid=15990, quantity=1), position=weapon),
        2: ObjectItemInventory(item=ObjectItem(uid=2, gid=2, quantity=1), position=unequipped),
        3: ObjectItemInventory(item=ObjectItem(uid=3, gid=3, quantity=1), position=unequipped),
    })
    scores = {1: 1.0, 2: 10.0, 3: 100.0}

    def equipable(_item: ObjectItemInventory) -> bool:
        return True

    def positions(gid: int) -> tuple[CharacterInventoryPositionEnum, ...]:
        return (hat,) if gid == 3 else (weapon,)

    def score(item: ObjectItemInventory, _elem: EffectElement) -> float:
        return scores[item.item.uid]

    def loadout_score(items: Iterable[ObjectItemInventory], elem: EffectElement) -> float:
        return sum(score(item, elem) for item in items)

    monkeypatch.setattr(behavior, "_is_equipable", equipable)
    monkeypatch.setattr(auto_equipment_from_inventory_behavior, "get_equipment_positions", positions)
    monkeypatch.setattr(auto_equipment_from_inventory_behavior, "roll_score", score)
    monkeypatch.setattr(auto_equipment_from_inventory_behavior, "equipment_score", loadout_score)
    send, finished = Mock(), Mock()
    monkeypatch.setattr(behavior, "send_message_delayed", send)
    try:
        behavior.start(callback=finished, parent=None)
        request = send.call_args.args[0]
        assert (request.object_uid, request.position) == (3, hat)
        behavior.event_manager.process_msg(ObjectMovementEvent(object_uid=3, position=hat))
        if not keep_wand:
            request = send.call_args.args[0]
            assert (request.object_uid, request.position) == (2, weapon)
            behavior.event_manager.process_msg(ObjectMovementEvent(object_uid=2, position=weapon))
        assert send.call_count == (1 if keep_wand else 2)
        finished.assert_called_once_with(None)
    finally:
        behavior.stop()
