import json
import pandas as pd
import numpy as np

from otlang.sdk.syntax import Keyword, Positional, OTLType
from pp_exec_env.base_command import BaseCommand, Syntax


class KsPrepareCommand(BaseCommand):
    # define syntax of your command here
    syntax = Syntax(
        [
            Positional("id", required=False, otl_type=OTLType.TEXT),
        ],
    )
    use_timewindow = False  # Does not require time window arguments
    idempotent = True  # Does not invalidate cache

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:

        node_id = self.get_arg('id').value or None
        g = DataframeGraph(df, self.config['objects'])
        return g.get_ks_dataframe(node_id)


class DataframeGraph:
    def __init__(self, df, object_primitive_map: dict[str, str]):
        self.df = df.set_index('primitiveID')
        self.node_property = self._get_node_property_dict(self.df)
        
        # mapping between primitiveName and object type (pad, well, pipe ...)
        self.object_primitive_map = object_primitive_map
        self.primitive_object_map = {}
        for key, value in object_primitive_map.items():
            self.primitive_object_map[value] = key

    def _get_node_property_dict(self, df):
        """
        Проход по датафрейму и создание словаря пропертей
        """
        property_dct = {}
        for row_index, row in df.iterrows():
            node_id = row_index
            property_dct[node_id] = json.loads(row['properties'])

        return property_dct

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
        node_type_from_props = self._get_node_property(node_id, 'object_type')
        if node_type_from_props:
            return node_type_from_props

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

    def _get_node_property(self, node_id: str, prop_name: str):
        props = self._get_node_properties(node_id)
        if prop_name in props:
            return props[prop_name]['value']

        else:
            return None

    def _get_node_properties(self, node_id):
        return self.node_property[node_id]

    def _get_ksolver_row(self, pipe_node_id):
        start_node_id = next(self.adjacent_nodes_for_target(pipe_node_id))
        end_node_id = next(self.adjacent_nodes_for_source(pipe_node_id))

        start_node_type = self.get_node_type(start_node_id)
        end_node_type = self.get_node_type(end_node_id)

        start_node_properties = self._get_node_properties(start_node_id)
        end_node_properties = self._get_node_properties(end_node_id)
        ksolver_row = {
            'juncType': 'pipe',
            'node_name_start': None,
            'node_id_start': None,
            'node_id_end': None,
            'node_name_end': None,
            'X_start': None,
            'X_end': None,
            'Y_start': None,
            'Y_end': None,
            'startKind': None,
            'startValue': None,
            'startT': None,
            'endKind': None,
            'endValue': None,
            'endT': None,
            'startIsSource': None,
            'endIsOutlet': None,
            # Берем параметры с pipe
            'L': None,
            'd': None,
            's': None,
            'uphillM': None,
            'effectiveD': None,
            'intD': None,
            'roughness': None,
            # для скважины startNode
            'perforation': None,
            'pumpDepth': None,
            'model': None,
            'frequency': None,
            'productivity': None,
            'predict_mode': None,
            'shtr_debit': None,
            'K_pump': None,
            'VolumeWater': None,


        }

        # заполнение start аттрибутов
        start_attrs = set(filter(
            lambda attr_name: 'start' in attr_name,
            ksolver_row.keys()
        ))

        # этот атрибут определяется отдельно
        start_attrs.remove('startIsSource')

        for attr in start_attrs:
            # если префикс, то убираем префикс
            if attr.startswith('start'):
                json_attr_name = attr[5:]
            # если суффикс то убираем суффикс
            elif attr.endswith('_start'):
                json_attr_name = attr[0:-6]
            else:
                assert "start must be suffix or prefix"
            prop = self._get_node_property(start_node_id, json_attr_name)
            ksolver_row[attr] = prop

        end_attrs = set(
            filter(
                lambda attr_name: 'end' in attr_name,
                ksolver_row.keys()
            )
        )
        # это тоже аналогично определяется отдельно
        end_attrs.remove('endIsOutlet')

        # заполнение end аттрибутов
        for attr in end_attrs:
            if attr.startswith('end'):
                json_attr_name = attr[3:]
            elif attr.endswith('_end'):
                json_attr_name = attr[0:-4]
            else:
                assert "end must be suffix or prefix"
            prop = self._get_node_property(end_node_id, json_attr_name)
            ksolver_row[attr] = prop

        ksolver_row['startIsSource'] = self._get_node_property(start_node_id, 'IsSource')
        ksolver_row['endIsOutlet'] = self._get_node_property(end_node_id, 'IsOutlet')

        # заполнение атрибутов трубы
        for attr in ('L', 'd', 's', 'uphillM', 'effectiveD', 'intD', 'roughness'):
            ksolver_row[attr] = self._get_node_property(pipe_node_id, attr)

        # значение по умолчанию для roughness
        if ksolver_row['roughness'] is None:
            ksolver_row['roughness'] = 0.00001

        # заполнение значений скважины
        for attr in ('perforation', 'pumpDepth', 'model', 'frequency', 'productivity', 'predict_mode', 'shtr_debit', 'K_pump', 'VolumeWater'):
            ksolver_row[attr] = self._get_node_property(start_node_id, attr)

        # пустые строки VolumeWater заменяем на np.Nan иначе в Ksolver ошибка
        if ksolver_row['VolumeWater'] == '':
            ksolver_row['VolumeWater'] = np.NaN

        return ksolver_row

    def get_ks_dataframe(self, node_id=None):
        """
        Возвращает датафрейм пригодный для ksolver
        """

        # получаем часть датафрейма
        if node_id:
            selected_node_ids = self.get_part(node_id)

        else:  # весь датафрейм
            selected_node_ids = list(self.df.index)

        # из этой части получаем только трубы
        pipes_ids = self._get_pipes_ids(selected_node_ids)

        # для каждой трубы формируем строку для датафрейма ksolver
        ksolver_rows = list(map(
            lambda pipe_node_id: self._get_ksolver_row(pipe_node_id),
            pipes_ids
        ))
        return pd.DataFrame(ksolver_rows)
        # df_part = self.df.loc[self.df.index.isin(selected_node_ids)]
