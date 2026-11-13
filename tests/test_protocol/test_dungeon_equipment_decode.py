from unittest.mock import Mock

import pytest

from DBDofusUnity.datas.protos.non_obf.game.common_pb2 import InteractiveElement
from DBDofusUnity.datas.protos.non_obf.game.interactive_element_pb2 import InteractiveUseRequest, InteractiveUsedEvent
from DBDofusUnity.datas.protos.non_obf.game.gamemap_pb2 import MapCurrentEvent
from DBDofusUnity.dofus_unity_reader.grid.map_point import MapPoint
from src.core.engine.movements.map.path_finding.movement_path import MovementPath
from google.protobuf.json_format import ParseDict

from DBDofusUnity.datas.protos.non_obf.game.common_pb2 import ObjectItem, ObjectItemInventory
from DBDofusUnity.datas.protos.non_obf.game.inventory_pb2 import ObjectMovementEvent
from DBDofusUnity.dofus_unity_reader.data_center.world_graph_reader import WorldGraphReader
from src.core.bot.bot import Bot
from src.core.engine.movements.world.edge import get_valid_transition
from src.protocol.protocol_game import get_clear_msg_from_obf
from DBDofusUnity.datas.protos.obf.game.game_messages_pb2 import iqn
from src.core.engine.movements.world.transition_ban import BannedTransition, TransitionBanScope


@pytest.mark.parametrize("equip_map", [103549440, 191105026])
def test_recorded_weapon_changes_update_the_miniature_passage_access(runtime_bot: Bot, equip_map: int) -> None:
    state = runtime_bot.game_state
    state.map.map_id = 103549440
    state.inventory.objects_by_uid.clear()
    state.inventory.objects_by_uid[5411984] = ObjectItemInventory(
        item=ObjectItem(uid=5411984, gid=15990, quantity=1), position=1
    )
    state.inventory.objects_by_uid[3800665] = ObjectItemInventory(
        item=ObjectItem(uid=3800665, gid=1, quantity=1), position=63
    )
    source = next(iter(WorldGraphReader().get_vertexes(103549440)))
    edge = next(edge for edge in WorldGraphReader().get_outgoing_edges_from_vertex(source) if edge.m_to.m_mapId == 146676736)
    message_class = iqn

    def apply(uid: int, position: int) -> None:
        # Captured wire field names, independent of the mapping under test.
        event = get_clear_msg_from_obf(ParseDict({"fsmv": uid, "fsmx": position, "fsmw": 0}, message_class()))
        assert isinstance(event, ObjectMovementEvent)
        assert event.object_uid == uid
        assert event.position == position
        runtime_bot.event_manager.process_msg(event)
        assert state.inventory.objects_by_uid[uid].position == position

    def passage_is_open() -> bool:
        return get_valid_transition(edge, edge.m_transitions, state.get_world_transition_context()) is not None

    assert passage_is_open()
    apply(5411984, 63)
    apply(3800665, 1)
    assert not passage_is_open()
    blocked = BannedTransition(edge.m_from, edge.m_to, edge.m_transitions[0], TransitionBanScope.SESSION)
    state.map.banned_edge_transitions.add(blocked)
    state.map.excluded_element_ids.add(487849)
    apply(3800665, 63)
    assert blocked in state.map.banned_edge_transitions
    state.map.map_id = equip_map
    apply(5411984, 1)
    assert blocked not in state.map.banned_edge_transitions
    assert 487849 not in state.map.excluded_element_ids
    assert passage_is_open()



def test_miniature_passage_uses_the_wall_hole_and_waits_for_the_next_map(
    runtime_bot: Bot, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = runtime_bot.game_state
    state.map.map_id = 103549440
    state.inventory.objects_by_uid[5411984] = ObjectItemInventory(
        item=ObjectItem(uid=5411984, gid=15990, quantity=1), position=1
    )
    state.interactive.interactive_element_by_id[487849] = InteractiveElement(
        element_id=487849, on_current_map=True,
        enabled_skills=[InteractiveElement.InteractiveElementSkill(skill_id=184, skill_instance_uid=17551)],
    )
    position = MapPoint.from_cell_id(257)
    monkeypatch.setattr(type(state.map), "map_point", property(lambda _map: position))
    behavior = runtime_bot.dungeon_behavior.auto_trip_smart_behavior.auto_trip_explorator_behavior.auto_trip_zaap_behavior.auto_trip_behavior.edge_behavior
    monkeypatch.setattr(behavior.path_finding, "get_interactive_near_path", Mock(return_value=MovementPath(start=position, end=position, path=[])))
    send = Mock()
    monkeypatch.setattr(behavior.event_manager, "send", send)
    source = next(iter(WorldGraphReader().get_vertexes(103549440)))
    edge = next(edge for edge in WorldGraphReader().get_outgoing_edges_from_vertex(source) if edge.m_to.m_mapId == 146676736)
    finished = Mock()
    try:
        behavior.start(callback=finished, parent=None, edge=edge)
        request = send.call_args.args[0]
        assert isinstance(request, InteractiveUseRequest)
        assert request.element_id == 487849
        assert request.skill_instance_uid == 17551
        finished.assert_not_called()
        behavior.event_manager.process_msg(InteractiveUsedEvent(element_id=487849, skill_id=184))
        finished.assert_not_called()
        behavior.event_manager.process_msg(MapCurrentEvent(map_id=146676736))
        finished.assert_called_once_with(None)
    finally:
        behavior.stop()
