from enum import StrEnum
from logging import Logger

from DBDofusUnity.datas.protos.non_obf.game.common_pb2 import (
    ObjectItemInventory,
)
from DBDofusUnity.dofus_unity_reader.data_center.data_reader import DataReader
from DBDofusUnity.dofus_unity_reader.data_center.i18n import I18N
from DBDofusUnity.dofus_unity_reader.game_constants.item import ItemEnum, ItemTypeEnum

from src.core.engine.dungeons.dungeon_info import DungeonInfo


class DungeonAccess(StrEnum):
    KEYRING = "keyring"
    INVENTORY_KEY = "inventory_key"


def get_dungeon_access(
    dungeon_info: DungeonInfo,
    objects_by_uid: dict[int, ObjectItemInventory],
    logger: Logger,
) -> DungeonAccess | None:
    if dungeon_info.blocked_reason is not None:
        return None
    related_item_key_ids = {
        item.id
        for item in DataReader().item_by_id.values()
        if item.nameId is not None
        and dungeon_info.key_name in I18N().name_by_id.get(item.nameId, "")
        and item.typeId == ItemTypeEnum.KEY
    }
    if not related_item_key_ids:
        logger.error("No key definition found for dungeon %s", dungeon_info.name)
        return None

    keyring = next(
        (
            object.item
            for object in objects_by_uid.values()
            if object.item.gid == ItemEnum.KEY_RING and object.item.quantity > 0
        ),
        None,
    )
    if keyring is not None and any(effect.value_int in related_item_key_ids for effect in keyring.effects):
        return DungeonAccess.KEYRING
    if any(
        object.item.gid in related_item_key_ids and object.item.quantity > 0
        for object in objects_by_uid.values()
    ):
        return DungeonAccess.INVENTORY_KEY
    return None
