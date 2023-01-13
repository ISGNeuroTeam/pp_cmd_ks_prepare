import json
import pandas as pd
from otlang.sdk.syntax import Keyword, Positional, OTLType
from pp_exec_env.base_command import BaseCommand, Syntax



class KsPrepareCommand(BaseCommand):
    # define syntax of your command here
    syntax = Syntax(
        [
            Positional("id", required=True, otl_type=OTLType.TEXT),
        ],
    )
    use_timewindow = False  # Does not require time window arguments
    idempotent = True  # Does not invalidate cache

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        print('==============================!')
        print('prepare for ks')

        print('config')
        print(self.config)
        print(self.config['objects'])
        print(df.columns)

        node_id = self.get_arg('id').value
        g = DataframeGraph(df, self.config['objects'])
        selected_node_ids = g.get_part(node_id)
        print(selected_node_ids)

        return df


class DataframeGraph:
    def __init__(self, df, object_primitive_map: dict[str, str]):
        self.df = df.set_index('primitiveID')
        
        # mapping between primitiveName and object type (pad, well, pipe ...)
        self.object_primitive_map = object_primitive_map
        self.primitive_object_map = {}
        for key, value in object_primitive_map.items():
            self.primitive_object_map[value] = key

    def adjacent_nodes(self, node_id) -> list[str]:
        """
        Generator of adjacent nodes, using out ports and in ports
        """
        for edge in self.adjacent_nodes_source(node_id):
            yield edge
        for edge in self.adjacent_nodes_target(node_id):
            yield edge

    def adjacent_nodes_source(self, node_id):
        edges_list = json.loads(self.df.loc[node_id]['source_edges'])
        for edge in edges_list:
            yield edge['targetNode']

    def adjacent_nodes_target(self, node_id):
        edges_list = json.loads(self.df.loc[node_id]['target_edges'])
        for edge in edges_list:
            yield edge['sourceNode']

    def get_part(self, node_id):
        """
        Traverse graph broadwise from node with <id> and gets part of it
        """
        print(self.df.loc[node_id]['primitiveName'])

        # typical broadwise traverse
        visited = []
        queue = []
        visited.append(node_id)
        queue.append(node_id)

        while queue:
            node_id = queue.pop(0)
            for adjacent_node_id in self.adjacent_nodes(node_id):
                # проверка на DNS и PAD
                if adjacent_node_id not in visited:
                    visited.append(adjacent_node_id)
                    queue.append(adjacent_node_id)
                    print('Node:')
                    print(adjacent_node_id)
                    print('Type:')
                    print(self.get_node_type(adjacent_node_id))
                    
        return visited

    def get_node_type(self, node_id: str) -> str:
        """
        Returns node type by primitive name
        """
        primitive_name = self.df.loc[node_id]['primitiveName']
        if primitive_name in self.primitive_object_map:
            return self.primitive_object_map[primitive_name]
        else:
            return 'UnknownNodeType'
        



