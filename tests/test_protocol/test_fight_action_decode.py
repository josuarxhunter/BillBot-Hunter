from google.protobuf.json_format import ParseDict
from google.protobuf.message_factory import GetMessageClass

from DBDofusUnity.datas.protos.non_obf.game.game_action_pb2 import GameActionFightEvent
from src.protocol.protocol_game import POOL, get_clear_msg_from_obf, get_mapping_proto_to_obf


def test_shared_fight_payload_uses_action_to_distinguish_heal_from_detection() -> None:
    mappings = get_mapping_proto_to_obf()
    event_type, event_fields = mappings[GameActionFightEvent.DESCRIPTOR.full_name]
    _, detection_fields = mappings[GameActionFightEvent.InvisibleDetected.DESCRIPTOR.full_name]
    descriptor = POOL.FindMessageTypeByName(event_type)
    payload_name = event_fields["invisible_detected"]
    payload = descriptor.fields_by_name[payload_name].message_type
    assert payload is not None
    event_class = GetMessageClass(descriptor)
    shared_values = {
        detection_fields["target_id"]: -5,
        detection_fields["cell"]: 0,
        payload.fields_by_number[4].name: 39,
    }

    def decode(action_id: int) -> GameActionFightEvent:
        obfuscated = ParseDict(
            {event_fields["action_id"]: action_id, payload_name: shared_values}, event_class()
        )
        event = get_clear_msg_from_obf(obfuscated)
        assert isinstance(event, GameActionFightEvent)
        return event

    heal = decode(108)
    assert heal.life_points_gain.target_id == -5
    assert heal.life_points_gain.delta == 39
    assert not heal.HasField("invisible_detected")

    other_action = decode(3001)
    assert other_action.invisible_detected.target_id == -5
    assert other_action.invisible_detected.cell == 0
    assert not other_action.HasField("life_points_gain")
