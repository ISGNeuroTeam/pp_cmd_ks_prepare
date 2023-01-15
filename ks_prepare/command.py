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

        node_id = self.get_arg('id').value
        g = DataframeGraph(df, self.config['objects'])
        print(df)
        return g.get_ks_dataframe(node_id)


class DataframeGraph:
    def __init__(self, df, object_primitive_map: dict[str, str]):
        self.df = df.set_index('primitiveID')
        
        # mapping between primitiveName and object type (pad, well, pipe ...)
        self.object_primitive_map = object_primitive_map
        self.primitive_object_map = {}
        for key, value in object_primitive_map.items():
            self.primitive_object_map[value] = key

    def adjacent_nodes(self, node_id):
        """
        Generator of adjacent nodes, using out ports and in ports
        """
        for source_node_id in self.adjacent_nodes_for_source(node_id):
            yield source_node_id
        for target_node_id in self.adjacent_nodes_for_target(node_id):
            yield target_node_id

    def adjacent_nodes_for_source(self, node_id):
        """
        Возвращает id соседниx узлов графа для которых переданный узел явялется source
        """
        edges_list = json.loads(self.df.loc[node_id]['source_edges'])
        for edge in edges_list:
            yield edge['targetNode']

    def adjacent_nodes_for_target(self, node_id):
        """
        Возвращает id соседних узлов графа для которых переданный узел является target
        """
        edges_list = json.loads(self.df.loc[node_id]['target_edges'])
        for edge in edges_list:
            yield edge['sourceNode']

    def get_part(self, node_id):
        """
        Traverse graph broadwise from node with <id> and gets part of it
        """

        # Обход графа в ширину до DNS и pad
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
                    # если дошли до Днс или pad остальные узлы не берем
                    node_type = self.get_node_type(node_id)
                    if not (node_type == 'pad' or node_type == 'dns'):
                        queue.append(adjacent_node_id)
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

    def _get_pipes_ids(self, node_ids_list: list):
        """
        Из переданного списка id оставляет только id труб
        """
        return filter(
            lambda node_id: self.get_node_type(node_id) == 'pipe',
            node_ids_list
        )

    def _get_node_properties(self, node_id):
        return json.loads(self.df.loc[node_id]['properties'])

    def _get_ksolver_row(self, pipe_node_id):
        start_node_id = next(self.adjacent_nodes_for_target(pipe_node_id))
        end_node_id = next(self.adjacent_nodes_for_source(pipe_node_id))

        start_node_type = self.get_node_type(start_node_id)
        end_node_type = self.get_node_type(end_node_id)

        start_node_properties = self._get_node_properties(start_node_id)
        end_node_properties = self._get_node_properties(end_node_id)
        return {
            'juncType': 'pipe',
            'startKind': 'P' if start_node_type == 'dns' else 'Q',
            'startValue': None,
            'endKind': 'P' if end_node_type == 'dns' else 'Q',
            'endValue': None,
        }


    def get_ks_dataframe(self, node_id):
        """
        Возвращает датафрейм пригодный для ksolver
        """

        # получаем часть датафрейма
        selected_node_ids = self.get_part(node_id)

        # из этой части получаем только трубы
        pipes_ids = self._get_pipes_ids(selected_node_ids)

        # для каждой трубы формируем строку для датафрейма ksolver
        ksolver_rows = list(map(
            lambda pipe_node_id: self._get_ksolver_row(pipe_node_id),
            pipes_ids
        ))
        return pd.DataFrame(ksolver_rows)
        # df_part = self.df.loc[self.df.index.isin(selected_node_ids)]
