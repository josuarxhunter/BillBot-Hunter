from dataclasses import dataclass, replace

from DBDofusUnity.dofus_unity_reader.data_center.world_graph_reader import WorldGraphReader
from DBDofusUnity.dofus_unity_reader.game_constants.map_id import DESTINATION_ACCESS_MAP_IDS
from DBDofusUnity.dofus_unity_reader.models.world_graph import Edge, Vertice

from src.core.engine.contexts import WorldPathContext
from src.core.engine.movements.map.path_finding.path_finding import Pathfinding
from src.core.engine.movements.world.astar_vertice import AstarWorld


@dataclass
class WorldPathFinder:
    path_finding: Pathfinding

    astar_world: AstarWorld

    def find_path(
        self,
        context: WorldPathContext,
        src_vertex: Vertice,
        dst_map_ids: set[int],
        linked_zone: int | None = None,
    ) -> list[Edge] | None:
        dst_vertexes: set[Vertice]
        if linked_zone is not None:
            dst_vertexes = {
                vertex
                for dst_map_id in dst_map_ids
                if (vertex := WorldGraphReader().get_vertex(dst_map_id, linked_zone)) is not None
            }
        else:
            dst_vertexes = {
                vertex for dst_map_id in dst_map_ids for vertex in WorldGraphReader().get_vertexes(dst_map_id)
            }

        if src_vertex in dst_vertexes:
            return []

        if len(dst_vertexes) == 0:
            return None
        access_map_ids = frozenset(
            map_id
            for destination in dst_map_ids
            for map_id in DESTINATION_ACCESS_MAP_IDS.get(destination, ())
        )
        context = replace(
            context,
            transition=replace(context.transition, allowed_map_ids=context.transition.allowed_map_ids | access_map_ids),
        )
        self.astar_world.set_context(context)
        return self.astar_world.find_path(start=src_vertex, ends=dst_vertexes)
