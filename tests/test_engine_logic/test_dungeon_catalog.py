import logging

import pytest

from DBDofusUnity.datas.protos.non_obf.game.common_pb2 import ObjectItem, ObjectItemInventory
from DBDofusUnity.dofus_unity_reader.data_center.data_reader import DataReader
from DBDofusUnity.dofus_unity_reader.data_center.world_graph_reader import WorldGraphReader
from DBDofusUnity.dofus_unity_reader.game_constants.item import ItemTypeEnum
from src.core.engine.dungeons.dungeon_access import DungeonAccess, get_dungeon_access
from src.core.engine.dungeons.dungeon_info import (
    ALL_DUNGEONS,
    LARVA_DUNGEON,
    PLAYABLE_DUNGEONS,
    DungeonInfo,
    get_dungeon_info_for_map_id,
)
from src.core.engine.npcs.dialog_texts import get_reply_text, matches
from src.core.engine.npcs.reply_selector import ByText


def test_catalog_covers_the_entire_level_one_to_fifty_range() -> None:
    expected = {info.id for info in DataReader().dungeon_by_id.values() if 1 <= info.optimalPlayerLevel <= 50}
    assert {info.dungeon.id for info in ALL_DUNGEONS} == expected
    assert len(ALL_DUNGEONS) == len(expected)
    assert {info.dungeon.id for info in PLAYABLE_DUNGEONS} == expected - {LARVA_DUNGEON.dungeon.id}


@pytest.mark.parametrize("info", PLAYABLE_DUNGEONS, ids=lambda info: str(info.dungeon.id))
def test_profile_uses_existing_keys_dialogues_and_passages(info: DungeonInfo) -> None:
    reader = DataReader()
    from DBDofusUnity.dofus_unity_reader.data_center.i18n import I18N

    key = next(
        item
        for item in reader.item_by_id.values()
        if item.typeId == ItemTypeEnum.KEY
        and item.nameId is not None
        and I18N().name_by_id.get(item.nameId) == info.key_name
    )
    inventory = {1: ObjectItemInventory(item=ObjectItem(uid=1, gid=key.id, quantity=1))}
    assert get_dungeon_access(info, inventory, logging.getLogger()) is DungeonAccess.INVENTORY_KEY
    assert info.entrance_npc_info.npc_map_id == info.dungeon.entranceMapId
    assert get_dungeon_info_for_map_id(info.exit_dialog_map_id) is info

    assert info.entrance_npc_info.npc_name is not None
    npc_ids = reader.npc_ids_by_name[info.entrance_npc_info.npc_name]
    entrance_replies = {
        reply.values[0] for npc_id in npc_ids for reply in reader.npc_by_id[npc_id].dialogReplies
    }
    for turn in [*info.key_entrance_turns, *info.keyring_entrance_turns]:
        assert isinstance(turn.reply, ByText)
        assert any(matches(turn.reply.pattern, get_reply_text(reply)) for reply in entrance_replies), (
            info.name,
            turn.reply.pattern,
        )
    if info.exit_npc_info is not None:
        assert info.exit_npc_info.npc_name is not None
        exit_replies = {
            reply.values[0]
            for npc_id in reader.npc_ids_by_name[info.exit_npc_info.npc_name]
            for reply in reader.npc_by_id[npc_id].dialogReplies
        }
        for turn in info.exit_turns:
            assert isinstance(turn.reply, ByText)
            assert any(matches(turn.reply.pattern, get_reply_text(reply)) for reply in exit_replies), (
                info.name,
                turn.reply.pattern,
            )
    else:
        assert any(
            edge.m_to.m_mapId == info.dungeon.exitMapId
            for vertex in WorldGraphReader().get_vertexes(info.exit_dialog_map_id)
            for edge in WorldGraphReader().get_outgoing_edges_from_vertex(vertex)
        )
    for source, target in info.room_transitions.items():
        assert source in info.interior_map_ids and target in info.interior_map_ids
        assert any(
            edge.m_to.m_mapId == target
            for vertex in WorldGraphReader().get_vertexes(source)
            for edge in WorldGraphReader().get_outgoing_edges_from_vertex(vertex)
        ), (source, target)


def test_larvae_is_visible_but_does_not_grant_automatic_access() -> None:
    assert LARVA_DUNGEON in ALL_DUNGEONS
    assert LARVA_DUNGEON not in PLAYABLE_DUNGEONS
    assert LARVA_DUNGEON.blocked_reason is not None
    assert get_dungeon_access(LARVA_DUNGEON, {}, logging.getLogger()) is None
