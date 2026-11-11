from dataclasses import dataclass, field, replace
from functools import partial

from DBDofusUnity.datas.protos.non_obf.game.gamemap_pb2 import MapComplementaryInformationEvent, MapObstacle
from DBDofusUnity.dofus_unity_reader.data_center.world_graph_reader import WorldGraphReader
from DBDofusUnity.dofus_unity_reader.game_constants.transition_type import TransitionTypeEnum
from DBDofusUnity.dofus_unity_reader.grid.map_point import MapPoint
from DBDofusUnity.dofus_unity_reader.models.world_graph import Edge
from src.core.behaviors.behavior import Behavior, BehaviorState
from src.core.behaviors.movements.edge_behavior import EdgeBehavior
from src.core.behaviors.movements.map_change_behavior import MapChangeError
from src.core.behaviors.movements.map_move_behavior import MapMoveBehavior
from src.core.engine.movements.map.path_finding.path_finding import Pathfinding
from src.core.engine.movements.world.edge import get_valid_transition


@dataclass
class DungeonTraversalBehavior(Behavior):
    edge_behavior: EdgeBehavior
    map_move_behavior: MapMoveBehavior
    path_finding: Pathfinding

    _target_map_id: int = field(init=False, default=0)
    _map_loaded: bool = field(init=False, default=False)
    _edge_finished: bool = field(init=False, default=False)

    def run(self, target_map_id: int) -> None:
        self._target_map_id = target_map_id
        self._map_loaded = False
        self._edge_finished = False
        edges = WorldGraphReader().get_outgoing_edges_from_vertex(self.game_state.map.curr_vertex)
        context = self.game_state.get_world_transition_context()
        edge = next(
            (
                edge
                for edge in edges
                if edge.m_to.m_mapId == target_map_id
                and get_valid_transition(edge, edge.m_transitions, context) is not None
            ),
            None,
        )
        if edge is None:
            return self.finish("DUNGEON_PASSAGE_UNAVAILABLE")
        transition = get_valid_transition(edge, edge.m_transitions, context)
        assert transition is not None
        self.wait_for_map()
        trap_cells = {
            candidate.m_cellId
            for other in edges
            if other.m_to.m_mapId != target_map_id
            for candidate in other.m_transitions
            if candidate.m_type == TransitionTypeEnum.MAP_ACTION and candidate.m_cellId >= 0
        }
        if not trap_cells or transition.m_type != TransitionTypeEnum.INTERACTIVE:
            return self.follow_edge(edge)

        movement_context = self.game_state.get_map_movement_context()
        movement_context = replace(
            movement_context,
            obstacle_on_cell_id={
                **movement_context.obstacle_on_cell_id,
                **{
                    cell_id: MapObstacle(cell_id=cell_id, state=MapObstacle.OBSTACLE_CLOSED)
                    for cell_id in trap_cells
                },
            },
        )
        path = self.path_finding.get_interactive_near_path(
            movement_context,
            self.game_state.map.map_point,
            MapPoint.from_cell_id(transition.m_cellId),
            [transition.m_skillId],
        )
        if path is None:
            return self.finish("DUNGEON_PASSAGE_UNREACHABLE")
        if path.start == path.end:
            return self.follow_edge(edge)
        self.map_move_behavior.start(
            move_path=path,
            callback=partial(self.on_approach_finished, edge=edge),
            parent=self,
        )

    def on_approach_finished(self, error_code: str | None, edge: Edge) -> None:
        if error_code is not None:
            return self.finish(error_code)
        self.follow_edge(edge)

    def wait_for_map(self) -> None:
        self.event_manager.on(
            MapComplementaryInformationEvent, self.on_map_loaded, originator=self,
            once=True, override_on_self=True, timeout=45, on_timeout=self.on_map_timeout,
        )

    def on_map_timeout(self) -> None:
        if self.game_state.fight.in_fight or self.edge_behavior.fight_behavior.state is BehaviorState.RUNNING:
            return self.wait_for_map()
        self.finish(MapChangeError.TIMEOUT)

    def follow_edge(self, edge: Edge) -> None:
        self.edge_behavior.start(edge=edge, callback=self.on_edge_finished, parent=self)

    def on_edge_finished(self, error_code: str | None) -> None:
        if error_code is not None:
            return self.finish(error_code)
        self._edge_finished = True
        if self._map_loaded:
            self.finish()

    def on_map_loaded(self, msg: MapComplementaryInformationEvent) -> None:
        if msg.map_id != self._target_map_id:
            if self.edge_behavior.fight_behavior.state is BehaviorState.RUNNING:
                return self.wait_for_map()
            return self.finish(MapChangeError.UNEXPECTED_NEW_MAP)
        self._map_loaded = True
        if self._edge_finished:
            self.finish()
