from dataclasses import dataclass, field
from functools import cached_property

from DBDofusUnity.dofus_unity_reader.data_center.data_reader import DataReader
from DBDofusUnity.dofus_unity_reader.data_center.i18n import I18N
from DBDofusUnity.dofus_unity_reader.game_constants.npc import NpcDialogInfo, NpcInfo
from DBDofusUnity.dofus_unity_reader.models.datas.dungeons_root import DungeonsRootItem
from src.core.engine.npcs.dialog_turn import DialogTurn
from src.core.engine.npcs.reply_selector import ByText


@dataclass
class DungeonEntrancePlate:
    map_id: int
    cell_id: int
    reset_cell_id: int
    passage_cell_id: int


@dataclass
class DungeonInfo:
    dungeon_id: int
    key_name: str
    entrance_npc_info: NpcInfo
    keyring_entrance_turns: list[DialogTurn]
    key_entrance_turns: list[DialogTurn]
    exit_npc_info: NpcDialogInfo | None
    exit_turns: list[DialogTurn]
    exit_dialog_map_id: int
    room_transitions: dict[int, int] = field(default_factory=dict[int, int])
    room_waypoints: dict[int, tuple[int, ...]] = field(default_factory=dict[int, tuple[int, ...]])
    room_waypoint_variants: dict[int, tuple[tuple[int, ...], ...]] = field(default_factory=dict[int, tuple[tuple[int, ...], ...]])
    room_avoid_cells: dict[int, frozenset[int]] = field(default_factory=dict[int, frozenset[int]])
    additional_exit_map_ids: frozenset[int] = frozenset()
    blocked_reason: str | None = None
    access_note: str | None = None
    access_npc_info: NpcInfo | None = None
    access_turns: list[DialogTurn] = field(default_factory=list[DialogTurn])
    access_cost: int = 0
    protected_equipment_gids: frozenset[int] = frozenset()
    entrance_plate: DungeonEntrancePlate | None = None
    dungeon: DungeonsRootItem = field(init=False)

    def __post_init__(self) -> None:
        self.dungeon = DataReader().dungeon_by_id[self.dungeon_id]
        assert self.entrance_npc_info.npc_map_id == self.dungeon.entranceMapId
        assert self.exit_dialog_map_id in DataReader().map_info_by_map_id

    @cached_property
    def name(self) -> str:
        return I18N().name_by_id[self.dungeon.nameId]

    @property
    def exit_map_ids(self) -> frozenset[int]:
        return self.additional_exit_map_ids | {self.exit_dialog_map_id}

    @property
    def interior_map_ids(self) -> frozenset[int]:
        return frozenset(self.dungeon.mapIds) | self.exit_map_ids | frozenset(self.room_transitions)


def _turns(*patterns: str) -> list[DialogTurn]:
    return [DialogTurn(reply=ByText(pattern=pattern)) for pattern in patterns]


def _profile(
    dungeon_id: int,
    key_id: int | None,
    entrance_npc_id: int,
    exit_npc_id: int | None,
    *,
    key_pattern: str = r"^donner la clef et entrer\.$",
    exit_patterns: tuple[str, ...] = (r"^sortir\.$",),
    intro_patterns: tuple[str, ...] = (),
    keyring_patterns: tuple[str, ...] = (r"utiliser le trousseau de clefs",),
    key_confirmation: str = r"^oui\.$",
    keyring_confirmation: str = r"^oui\.$",
    exit_map_id: int | None = None,
    additional_exit_map_ids: frozenset[int] = frozenset(),
    room_transitions: dict[int, int] | None = None,
    room_waypoints: dict[int, tuple[int, ...]] | None = None,
    room_waypoint_variants: dict[int, tuple[tuple[int, ...], ...]] | None = None,
    room_avoid_cells: dict[int, frozenset[int]] | None = None,
    blocked_reason: str | None = None,
    access_note: str | None = None,
    protected_equipment_gids: frozenset[int] = frozenset(),
    entrance_plate: DungeonEntrancePlate | None = None,
) -> DungeonInfo:
    reader = DataReader()
    names = I18N().name_by_id
    dungeon = reader.dungeon_by_id[dungeon_id]
    if exit_map_id is None:
        worlds = {reader.map_info_by_map_id[map_id].worldMap for map_id in dungeon.mapIds}
        exits = [
            info.id
            for info in reader.map_info_by_map_id.values()
            if info.worldMap in worlds and names.get(info.nameId) == f"{names[dungeon.nameId]} - Sortie"
        ]
        assert len(exits) == 1, f"Dungeon {dungeon_id}: expected one normal exit map, got {exits}"
        exit_map_id = exits[0]
    key_name = ""
    if key_id is not None:
        key = reader.item_by_id[key_id]
        assert key.nameId is not None
        key_name = names[key.nameId]
    return DungeonInfo(
        dungeon_id=dungeon_id,
        key_name=key_name,
        entrance_npc_info=NpcInfo(
            npc_map_id=dungeon.entranceMapId, npc_name=names[reader.npc_by_id[entrance_npc_id].nameId]
        ),
        keyring_entrance_turns=_turns(*intro_patterns, *keyring_patterns, keyring_confirmation),
        key_entrance_turns=_turns(*intro_patterns, key_pattern, key_confirmation),
        exit_npc_info=(
            NpcDialogInfo(npc_name=names[reader.npc_by_id[exit_npc_id].nameId])
            if exit_npc_id is not None
            else None
        ),
        exit_turns=_turns(*exit_patterns) if exit_npc_id is not None else [],
        exit_dialog_map_id=exit_map_id,
        additional_exit_map_ids=additional_exit_map_ids,
        room_transitions=room_transitions or {},
        room_waypoints=room_waypoints or {},
        room_waypoint_variants=room_waypoint_variants or {},
        room_avoid_cells=room_avoid_cells or {},
        blocked_reason=blocked_reason,
        access_note=access_note,
        protected_equipment_gids=protected_equipment_gids,
        entrance_plate=entrance_plate,
    )


KARDORIM_DUNGEON = _profile(
    90,
    8545,
    2907,
    2936,
    exit_patterns=(r"^quitter la crypte de kardorim\.$",),
    access_note="Requires access to Incarnam. Return travel from Astrub is not automated.",
)
GRANGE_TOURNESOL_DUNGEON = _profile(8, 8143, 780, 780)
SANDCASTLE_DUNGEON = _profile(
    19,
    8437,
    798,
    798,
    intro_patterns=(r"^preciser que vous voulez entrer dans le chateau ensable\.$",),
    exit_patterns=(r"^se sauver en courant\.$", r"^se laisser faire\.$"),
    room_transitions={193727490: 193727488},
)
BOUFTOU_ROYAL_DUNGEON = _profile(
    1,
    1568,
    173,
    173,
    key_pattern=r"^donner la clef des bouftous\.$",
    exit_patterns=(r"^quitter la cour du bouftou royal\.$",),
)
GHOST_HOUSE_DUNGEON = _profile(34, 11799, 1387, 1387, key_pattern=r"^(utiliser|donner) la clef\.$")
SCARAFLEAF_DUNGEON = _profile(
    45,
    8139,
    781,
    None,
    room_transitions={94109696: 94110720, 94111744: 94112768, 94111746: 94111744},
    room_waypoints={94111744: (486, 374, 287, 283)},
    # Recorded falls; the world graph only exposes the trap at cell 384.
    room_avoid_cells={94111744: frozenset({384, 441, 429})},
)
SKELETON_DUNGEON = _profile(
    47,
    1570,
    1163,
    6459,
    key_confirmation=r"^(confirmer l'utilisation d'une clef|oui)\.$",
    keyring_confirmation=r"^(confirmer l'utilisation du trousseau de clefs|oui)\.$",
    exit_patterns=(
        r"^demander son secret\.$",
        r"^repondre que vous voulez juste quitter cet endroit\.$",
        r"^accepter pour sortir d'ici\.$",
        r"^dire bonjour\.$",
    ),
    room_transitions={87035394: 87032322},
    entrance_plate=DungeonEntrancePlate(map_id=82314497, cell_id=99, reset_cell_id=114, passage_cell_id=259),
    access_note="Opens the cemetery tomb by stepping on cell 99, then walks into the crypt.",
)
TOFU_DUNGEON = _profile(
    48,
    7918,
    777,
    777,
    key_pattern=r"^donner la clef du tofulailler\.$",
    room_transitions={96206852: 96206850, 96206850: 96206848},
    room_waypoints={96206850: (452, 396, 301, 273, 260, 289, 262)},
    # Yellow holes and green route supplied by the user for room two.
    room_avoid_cells={96206850: frozenset({261, 288, 330, 367, 371, 381, 385, 423, 466})},
    intro_patterns=(r"^continuer la discussion\.$",),
)
KANKREBLATH_DUNGEON = _profile(
    88,
    15991,
    2766,
    2767,
    key_pattern=r"^utiliser la clef et monter\.$",
    keyring_patterns=(r"^montrer le trousseau de clefs\.$", r"^utiliser le trousseau de clefs\.$"),
    exit_patterns=(r"^quitter la cache de kankreblath( en courant)?\.$",),
    room_transitions={146672640: 146671616, 146672898: 146672640},
    protected_equipment_gids=frozenset({15990}),
    access_note="Requires a Rikiki Wand equipped or an Automatic Dimensional Reducer to pass through Kerubim's house. The dungeon key alone does not open this passage.",
)
GOB_ACADEMY_DUNGEON = _profile(
    138,
    26680,
    6674,
    6673,
    key_pattern=r"^donner la clef\.$",
    exit_map_id=221778434,
    additional_exit_map_ids=frozenset({205785118}),
    exit_patterns=(r"^quitter l'akademie\.$",),
    room_transitions={221777410: 221774336},
)
BWORK_DUNGEON = _profile(
    13,
    8135,
    775,
    776,
    key_pattern=r"^donner la clef du donjon des bworks\.$",
    exit_patterns=(r"^quitter le donjon des bworks\.$",),
    room_transitions={104599041: 104595971, 104599043: 104599041},
    room_waypoint_variants={104599041: (
        (395, 381, 367, 353, 340, 326, 313, 299, 300, 287, 301, 316),
        (456, 442, 429, 415, 401, 387, 374, 359, 345, 330, 316),
    )},
    # Linked zone 16 contains trigger 372 and the recorded fall at 386.
    room_avoid_cells={104599041: frozenset({
        328, 329,
        342, 343, 344,
        355, 356, 357, 358,
        369, 370, 371, 372,
        383, 384, 385, 386,
        397, 398, 399, 400,
        411, 412, 413,
        426, 427,
    })},
)
BLACKSMITH_DUNGEON = _profile(
    21,
    1569,
    1162,
    2030,
    exit_map_id=87297539,
    room_transitions={
        87294465: 87295489,
        87297537: 87294467,
        87294469: 87295493,
        87296517: 87294471,
        87297541: 87296517,
    },
    room_avoid_cells={87297537: frozenset({174}), 87296517: frozenset({178})},
)
HESQUE_DUNGEON = _profile(
    25,
    8917,
    941,
    941,
    exit_patterns=(r"^sortir de la grotte hesque\.$",),
    access_note="Requires completed Otomai access quests. Uses a known route or waypoint, otherwise Captain Kradoc's boat.",
)
HESQUE_DUNGEON.access_npc_info = NpcInfo(npc_map_id=95424516, npc_name="Capitaine Kradoc")
HESQUE_DUNGEON.access_turns = _turns(r"^partir vers l'ile d'otomai\.?$")
KWAKWA_DUNGEON = _profile(
    32,
    12017,
    1404,
    1404,
    key_pattern=r"^utiliser la clef\.$",
    exit_patterns=(r"^quitter le nid du kwakwa\.$",),
)
LARVA_DUNGEON = _profile(
    33,
    None,
    1438,
    None,
    blocked_reason="This dungeon requires two coordinated characters and is not automated yet.",
)
KWISMAS_DUNGEON = _profile(
    36,
    12150,
    795,
    795,
    exit_patterns=(r"^(sortir|prendre l'etoile du sapik et sortir)\.$",),
    access_note="Requires Kwismas Island to be open. Uses Hector Kwismas's boat when no direct route is available.",
)
KWISMAS_DUNGEON.access_npc_info = NpcInfo(npc_map_id=68420097, npc_name="Hector Nowel")
KWISMAS_DUNGEON.access_turns = _turns(
    r"^demander de quelle ile il parle\.$",
    r"^douter que l'on puisse trouver des tresors rien qu'en se baissant\.$",
    r"^accepter de partir pour l'ile de nowel\.$",
    r"^repondre que vos parents sont d'accord\.$",
    r"^le suivre\.$",
    r"^(embarquer( pour l'ile de nowel)?|partir pour l'ile de nowel)\.$",
)
SYLVAN_DUNGEON = _profile(
    142,
    27374,
    6809,
    6807,
    access_note="Uses a known Valonia waypoint or Captain Isabello Tissier's boat for 100 kamas.",
    key_pattern=r"^donner la clef\.$",
    exit_patterns=(r"^quitter le refuge sylvestre\.$",),
)
SYLVAN_DUNGEON.access_npc_info = NpcInfo(npc_map_id=68421124, npc_name="Capitaine Isabello Tissier")
SYLVAN_DUNGEON.access_turns = _turns(r"^payer 100 kamas et embarquer\.$")
SYLVAN_DUNGEON.access_cost = 100

ALL_DUNGEONS = sorted(
    [
        KARDORIM_DUNGEON,
        GRANGE_TOURNESOL_DUNGEON,
        SANDCASTLE_DUNGEON,
        BOUFTOU_ROYAL_DUNGEON,
        GHOST_HOUSE_DUNGEON,
        SCARAFLEAF_DUNGEON,
        SKELETON_DUNGEON,
        TOFU_DUNGEON,
        KANKREBLATH_DUNGEON,
        GOB_ACADEMY_DUNGEON,
        BWORK_DUNGEON,
        BLACKSMITH_DUNGEON,
        HESQUE_DUNGEON,
        KWAKWA_DUNGEON,
        LARVA_DUNGEON,
        KWISMAS_DUNGEON,
        SYLVAN_DUNGEON,
    ],
    key=lambda info: (info.dungeon.optimalPlayerLevel, info.dungeon.id),
)
PLAYABLE_DUNGEONS = [info for info in ALL_DUNGEONS if info.blocked_reason is None]


def get_dungeon_info_for_map_id(map_id: int) -> DungeonInfo | None:
    return next((info for info in ALL_DUNGEONS if map_id in info.interior_map_ids), None)
