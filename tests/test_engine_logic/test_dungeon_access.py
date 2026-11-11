import logging

import pytest

from DBDofusUnity.datas.protos.non_obf.game.common_pb2 import ObjectEffect, ObjectItem, ObjectItemInventory
from DBDofusUnity.dofus_unity_reader.game_constants.item import ItemEnum
from src.core.engine.dungeons.dungeon_access import DungeonAccess, get_dungeon_access
from src.core.engine.dungeons.dungeon_info import (
    BOUFTOU_ROYAL_DUNGEON,
    GRANGE_TOURNESOL_DUNGEON,
    DungeonInfo,
)


@pytest.fixture(params=[(GRANGE_TOURNESOL_DUNGEON, 8143), (BOUFTOU_ROYAL_DUNGEON, 1568)])
def dungeon_key(request: pytest.FixtureRequest) -> tuple[DungeonInfo, int]:
    return request.param


@pytest.mark.parametrize("has_keyring", [False, True])
def test_inventory_key_works_without_keyring_access(
    dungeon_key: tuple[DungeonInfo, int], has_keyring: bool
) -> None:
    dungeon, key_gid = dungeon_key
    inventory = {1: ObjectItemInventory(item=ObjectItem(uid=1, gid=key_gid, quantity=1))}
    if has_keyring:
        inventory[2] = ObjectItemInventory(item=ObjectItem(uid=2, gid=ItemEnum.KEY_RING, quantity=1))

    assert get_dungeon_access(dungeon, inventory, logging.getLogger()) is DungeonAccess.INVENTORY_KEY


def test_available_keyring_is_preferred_to_consuming_a_key(dungeon_key: tuple[DungeonInfo, int]) -> None:
    dungeon, key_gid = dungeon_key
    inventory = {
        1: ObjectItemInventory(item=ObjectItem(uid=1, gid=key_gid, quantity=1)),
        2: ObjectItemInventory(
            item=ObjectItem(
                uid=2, gid=ItemEnum.KEY_RING, quantity=1, effects=[ObjectEffect(value_int=key_gid)]
            )
        ),
    }

    assert get_dungeon_access(dungeon, inventory, logging.getLogger()) is DungeonAccess.KEYRING


@pytest.mark.parametrize("quantity", [0, 1])
def test_depleted_or_unrelated_keys_do_not_grant_access(
    dungeon_key: tuple[DungeonInfo, int], quantity: int
) -> None:
    dungeon, key_gid = dungeon_key
    other_key_gid = 1568 if key_gid == 8143 else 8143
    inventory = {
        1: ObjectItemInventory(item=ObjectItem(uid=1, gid=key_gid, quantity=0)),
        2: ObjectItemInventory(item=ObjectItem(uid=2, gid=other_key_gid, quantity=quantity)),
    }

    assert get_dungeon_access(dungeon, inventory, logging.getLogger()) is None
