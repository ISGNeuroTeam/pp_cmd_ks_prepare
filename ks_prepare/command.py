import json
import pandas as pd
import numpy as np

from collections import defaultdict
from itertools import chain

from otlang.sdk.syntax import Keyword, Positional, OTLType
from pp_exec_env.base_command import BaseCommand, Syntax


class KsPrepareCommand(BaseCommand):
    # define syntax of your command here
    syntax = Syntax(
        [
            Positional("id", required=False, otl_type=OTLType.TEXT),
            Keyword("tag", required=False, otl_type=OTLType.TEXT)
        ],
    )
    use_timewindow = False  # Does not require time window arguments
    idempotent = True  # Does not invalidate cache

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:

        node_id = self.get_arg('id').value or None
        tag = self.get_arg('tag').value or None
        if tag and tag not in ('dns', 'kns'):
            raise ValueError('Tag must be dns or kns')
        g = DataframeGraph(df, self.config['objects'])
        g.delete_disabled_nodes()
        if tag:
            g.delete_nodes('_pp_tag', tag, equal=False)
        return g.get_ks_dataframe(node_id)


class DataframeGraph:
    def __init__(self, df, object_primitive_map: dict[str, str]):
        self.df = df.set_index('primitiveID', drop=False)
        self.node_property = self._get_node_property_dict(self.df)
        
        # mapping between primitiveName and object type (pad, well, pipe ...)
        self.object_primitive_map = object_primitive_map
        self.primitive_object_map = {}
        for key, value in object_primitive_map.items():
            self.primitive_object_map[value] = key

    def delete_disabled_nodes(self):
        """
        Removes all nodes in graph with property disabled = True
        If rm_edges=True removes all source and target edges
        """
        self.delete_nodes('disabled', True)

    def delete_nodes(self, property_name, value, equal=True):
        """
        Removes all nodes in graph with property == value or != value
        """
        disabled_node_was_source = defaultdict(list)
        disabled_node_was_target = defaultdict(list)

        def filter_by_condition(row):
            property_value = self._get_node_property(row['primitiveID'], property_name)
            if property_value is not None and (
               (equal and property_value == value) or
               (not equal and property_value != value)
            ):
                # сохраняем ид узлов для которых данный узел был target
                disabled_node_was_target[row['primitiveID']] = [
                    node_id for node_id in self.adjacent_nodes_for_target(row['primitiveID'])
                ]
                # сохраняем ид узлов для которых данный узел был source
                disabled_node_was_source[row['primitiveID']] = [
                    node_id for node_id in self.adjacent_nodes_for_source(row['primitiveID'])
                ]
                return False
            else:
                return True

        # удаление узлов помеченных как disabled
        self.df = self.df[self.df.apply(filter_by_condition, axis=1)]
        # self.df = self.df.set_index('primitiveID', drop=False)
        # удаление ребер для которых удаленный узел был source
        for disabled_node_id, target_node_is_list in disabled_node_was_source.items():
            # remove from target edges
            for target_node_id in target_node_is_list:
                if target_node_id not in self.df.index:
                    continue
                target_edges_list = json.loads(self.df.at[target_node_id, 'target_edges'])
                target_edges_list = list(
                    filter(
                        lambda edge: edge['sourceNode'] != disabled_node_id,
                        target_edges_list
                    )
                )
                self.df.at[target_node_id, 'target_edges'] = json.dumps(target_edges_list)

        # удаление ребер для которых удаленный узел был target
        for disabled_node_id, source_node_id_list in disabled_node_was_target.items():
            # remove from source edges
            for source_node_id in source_node_id_list:
                if source_node_id not in self.df.index:
                    continue
                source_edges_list = json.loads(self.df.at[source_node_id, 'source_edges'])
                source_edges_list = list(
                    filter(
                        lambda edge: edge['targetNode'] != disabled_node_id,
                        source_edges_list
                    )
                )
                self.df.at[source_node_id, 'source_edges'] = json.dumps(source_edges_list)

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
        return self._filter_node_ids_by_node_type(node_ids_list, 'pipe')

    def _get_injection_well_ids(self, node_ids_list: list):
        return self._filter_node_ids_by_node_type(node_ids_list, 'injection_well')

    def _get_well_ids(self, node_ids_list: list):
        """
        Из переданного списка id оставляет только id скважин
        """
        return self._filter_node_ids_by_node_type(node_ids_list, 'well')

    def _filter_node_ids_by_node_type(self, node_ids_list: list, node_type: str):
        return filter(
            lambda node_id: self.get_node_type(node_id) == node_type,
            node_ids_list
        )

    def _get_node_property(self, node_id: str, prop_name: str):
        props = self._get_node_properties(node_id)
        if prop_name in props and 'value' in props[prop_name]:
            return props[prop_name]['value']
        else:
            return None

    def _get_node_properties(self, node_id):
        return self.node_property[node_id]

    def _get_ksolver_row(self, pipe_node_id, constant_properties=None):
        if constant_properties is None:
            constant_properties = dict()

        start_node_id = next(self.adjacent_nodes_for_target(pipe_node_id))
        end_node_id = next(self.adjacent_nodes_for_source(pipe_node_id))

        start_node_type = self.get_node_type(start_node_id)
        end_node_type = self.get_node_type(end_node_id)

        start_node_properties = self._get_node_properties(start_node_id)
        end_node_properties = self._get_node_properties(end_node_id)
        ksolver_row = {
            'row_type': 'pipe',
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
            'startIsOutlet': None,
            'endIsSource': None,
            'endIsOutlet': None,
            'altitude_start': None,
            'altitude_end': None,
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
            # для injection_well endNode
            'choke_diam': None

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
        # for attr in ('perforation', 'pumpDepth', 'model', 'frequency', 'productivity', 'predict_mode', 'shtr_debit', 'K_pump', 'VolumeWater'):
        #     ksolver_row[attr] = self._get_node_property(start_node_id, attr)
        if self._get_node_property(start_node_id, 'object_type') == 'well':
            ksolver_row['startKind'] = None
            ksolver_row['startIsSource'] = False

        # если конечный атрибут injection_well
        if self._get_node_property(end_node_id, 'object_type') == 'injection_well':
            # заполнение атрибутов для injection_well
            for attr in ('choke_diam', ):
                ksolver_row[attr] = self._get_node_property(end_node_id, attr)
            ksolver_row['row_type'] = 'injection_well'

        # пустые строки  заменяем на np.Nan иначе в Ksolver ошибка
        for attr in ('VolumeWater', 'altitude_start', 'altitude_end', 'intD'):
            if ksolver_row[attr] == '':
                ksolver_row[attr] = np.NaN
        ksolver_row.update(constant_properties)
        return ksolver_row

    def _get_ksolver_row_for_well(self, well_node_id, constant_properties):

        ks_graph_column_name_mapping = {
            'perforation': 'perforation',
            'pumpDepth': 'pumpDepth',
            'model': 'model',
            'frequency': 'frequency',
            'productivity': 'productivity',
            'predict_mode': 'predict_mode',
            'shtr_debit': 'shtr_debit',
            'K_pump': 'K_pump',
            'VolumeWater': 'VolumeWater',
            'startT': 'T',
            'startValue': 'Plastovoe_davlenie_atm',
            'wellNum': 'node_id',
            'node_id_end': 'node_id',
            'node_name_end': 'node_name',
        }

        columns_with_constants = {
            'row_type': 'oilwell',
            'startKind': 'P',
            'startIsSource': True,
            'endIsOutlet': False,
            'node_name_start': None,
            'node_id_start': 0,
            'endKind': None,
            'endValue': None,
            'endIsSource': False
        }

        default_values = {
            'startT': 60
        }


        well_row = {key: None
            for key in chain([
                'wellNum',
                'padNum',
                'node_id_end'],
                ks_graph_column_name_mapping.keys(),
                columns_with_constants.keys(),
                default_values
            )
        }

        # Добавляем константные значения
        well_row.update(columns_with_constants)

        # Добавляем значения из графа
        for ks_df_col_name, graph_vaule_name in ks_graph_column_name_mapping.items():
            well_row[ks_df_col_name] = self._get_node_property(well_node_id, graph_vaule_name)

        # Добавляем дефолтные значения если их нет
        for key, value in default_values.items():
            if not well_row[key]:
                well_row[key] = value

        # node_name format к.43__скв.4308
        node_name = self._get_node_property(well_node_id, 'node_name')
        padNum = node_name.split('__')[0].split('.')[1]
        well_row['padNum'] = padNum

        well_row['node_name_start'] = f'plast_{node_name}'

        well_row.update(constant_properties)

        return well_row

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

        # находим gas factor
        gas_factor = None
        for row_index, row in self.df.iterrows():
            obj_type = self._get_node_property(row_index, 'object_type')
            if obj_type == 'dns':
                gas_factor = self._get_node_property(row_index, 'gas_factor_m3_m3')
                break
        constant_properties = {
            'Gas_factor_m3_m3': gas_factor,
            'Oildensity_kg_m3': 826,
            'Waterdensity_kg_m3': 1015,
            'Formation_pressure_bar': 66.7
        }
        # для каждой трубы формируем строку для датафрейма ksolver
        ksolver_rows = list(map(
            lambda pipe_node_id: self._get_ksolver_row(pipe_node_id, constant_properties),
            pipes_ids
        ))
        wells_ids = self._get_well_ids(selected_node_ids)

        ksolver_rows_well = list(map(
            lambda well_node_id: self._get_ksolver_row_for_well(well_node_id, constant_properties),
            wells_ids
            )
        )
        return pd.DataFrame(ksolver_rows + ksolver_rows_well)
