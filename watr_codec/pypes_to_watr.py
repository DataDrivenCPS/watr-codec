import json
import os
import warnings

import pint
from pype_schema import connection, utils
from pype_schema.node import Network, Node
from pype_schema.tag import Tag, TagType, VirtualTag

from watr_codec.semantic_backend import SemanticModel, SemanticTerm


WATR_CODEC_DIR = os.path.dirname(os.path.abspath(__file__))

TOP_LEVEL_KEY = "PyPES2WaTr"
PROCESS_KEY = "process"
UNITS_KEY = "units"
NAME_KEY = "name"
URI_KEY = "uri"
ENUM_KIND_STR = "EnumerationKind"
S223_URI = "s223"
WATR_URI = "watr"
QUDT_URI = "qudt"
OWL_URI = "owl"

CUSTOM_HANDLED_ATTRIBUTES = [
    "nodes",
    "connections",
    "contents",
    "input_contents",
    "output_contents",
    "tags",
    "num_units",
    "id",
    "source",
    "destination",
    "exit_point",
    "entry_point",
]

NOT_YET_IMPLEMENTED_ATTRIBUTES = [
    "heating_values",
    "pressure",
    "flow_rate",
    "flowrate",
    "bidirectional",
    "pump_type",
    "pump_curve",
    "area",
    "selectivity",
    "settling_time",
]


class NotImplementedWarning(UserWarning):
    pass


class PyPES2WaTr:
    def __init__(
        self,
        network: Network,
        local_prefix: str,
        mapping_path=WATR_CODEC_DIR + "/data/pypes_watr_mapping.json",
        uri_mapping_path=WATR_CODEC_DIR + "/data/uri_mapping.json",
    ):
        self.world = network
        self.local_prefix = local_prefix
        with open(mapping_path, "r", encoding="utf-8") as file:
            self.mapping = json.load(file)
        with open(uri_mapping_path, "r", encoding="utf-8") as file:
            self.uri_mapping = json.load(file)

        self.model = SemanticModel(local_prefix, self.uri_mapping)
        self.property_dict = {}
        self.node_to_conn_ids = {}
        self.node_dict = {}
        self.conn_dict = {}
        self.conn_point_dict = {}
        self._translated = False

    def _sanitize_id(self, value: str) -> str:
        return value.replace(" ", "-")

    def _local(self, name: str = "") -> SemanticTerm:
        return self.model.local(name)

    def _term(self, data: dict) -> SemanticTerm:
        return self.model.term(data[URI_KEY], data[NAME_KEY])

    def _predicate(self, prefix: str, name: str) -> SemanticTerm:
        return self.model.predicate(prefix, name)

    def _add_relation(
        self, subject: SemanticTerm, prefix: str, name: str, obj: SemanticTerm
    ):
        self.model.add(subject, self._predicate(prefix, name), obj)

    def get_uri_prefix(self, uri: str):
        return self.uri_mapping[uri]

    def convert_units(self, units: pint.Unit):
        return self.mapping[TOP_LEVEL_KEY][UNITS_KEY][str(units)]

    def convert_contents(self, contents: utils.ContentsType):
        return self.mapping[TOP_LEVEL_KEY]["contents_types"][contents.name]

    def convert_attribute(self, attr_name: str):
        prop_dict = self.mapping[TOP_LEVEL_KEY]["attributes"][attr_name]
        is_quant_kind = ENUM_KIND_STR not in prop_dict[NAME_KEY]
        return prop_dict, is_quant_kind

    def convert_tag_type(self, tag_type: TagType):
        prop_dict = self.mapping[TOP_LEVEL_KEY]["tag_types"][tag_type.name]
        is_quant_kind = ENUM_KIND_STR not in prop_dict[NAME_KEY]
        return prop_dict, is_quant_kind

    def generate_conn_point_name(self, name: str):
        if name not in self.conn_point_dict:
            return name

        prefix, _, suffix = name.rpartition("-")
        next_num = int(suffix) + 1 if suffix.isdigit() else 2
        while f"{prefix}-{next_num}" in self.conn_point_dict:
            next_num += 1
        return f"{prefix}-{next_num}"

    def _add_medium_and_role(
        self, subject: SemanticTerm, medium_dict: dict, medium_predicate: str
    ):
        medium = self._term(medium_dict)
        self._add_relation(subject, S223_URI, medium_predicate, medium)

        role = medium_dict.get("role")
        if role:
            self._add_relation(
                subject,
                S223_URI,
                "hasRole",
                self.model.term(medium_dict["role-uri"], role),
            )

    def create_conn_points(self, conn: connection.Connection):
        source_name = self.generate_conn_point_name(f"{conn.source.id}-cp-1")
        dest_name = self.generate_conn_point_name(f"{conn.destination.id}-cp-1")
        source = self._local(source_name)
        dest = self._local(dest_name)
        conn_term = self._local(self._sanitize_id(conn.id))
        medium_dict = self.convert_contents(conn.contents)

        self.model.add_type(source, self.model.term(S223_URI, "OutletConnectionPoint"))
        self.model.add_type(dest, self.model.term(S223_URI, "InletConnectionPoint"))
        self._add_relation(
            source,
            S223_URI,
            "isConnectionPointOf",
            self._local(self._sanitize_id(conn.source.id)),
        )
        self._add_relation(
            dest,
            S223_URI,
            "isConnectionPointOf",
            self._local(self._sanitize_id(conn.destination.id)),
        )
        self._add_relation(source, S223_URI, "connectsThrough", conn_term)
        self._add_relation(dest, S223_URI, "connectsThrough", conn_term)
        self._add_medium_and_role(source, medium_dict, "hasMedium")
        self._add_medium_and_role(dest, medium_dict, "hasMedium")

        self.conn_point_dict[source_name] = {
            "node": conn.source.id,
            "connection": conn.id,
            "term": source,
        }
        self.conn_point_dict[dest_name] = {
            "node": conn.destination.id,
            "connection": conn.id,
            "term": dest,
        }
        return source_name, dest_name

    def translate_attribute(self, attr_name, value, parent_id, contents=None):
        prop_id = self._sanitize_id(parent_id) + attr_name
        unit_dict = {}
        converted_units = None
        unit_uri = None

        try:
            unit_dict = self.convert_units(value.units)
            converted_units = unit_dict.get(NAME_KEY)
            unit_uri = unit_dict.get(URI_KEY)
            value = value.magnitude
        except AttributeError:
            pass

        prop_data, is_quant_kind = self.convert_attribute(attr_name)
        prop_type = "QuantifiableProperty" if is_quant_kind else "EnumerableProperty"
        prop_term = self._local(prop_id)

        self.model.add_type(prop_term, self.model.term(S223_URI, prop_type))
        if value is not None:
            self.model.add(
                prop_term,
                self._predicate(S223_URI, "hasValue"),
                self.model.literal(value),
            )

        if contents is not None:
            medium_dict = self.convert_contents(contents)
            medium_name = medium_dict[NAME_KEY]
            medium_uri = medium_dict[URI_KEY]
            self._add_medium_and_role(prop_term, medium_dict, "ofMedium")
            role_name = medium_dict.get("role")
            role_uri = medium_dict.get("role-uri") if role_name is not None else None
        else:
            medium_name, medium_uri, role_name, role_uri = None, None, None, None

        if is_quant_kind:
            self._add_relation(
                prop_term, QUDT_URI, "hasQuantityKind", self._term(prop_data)
            )
        else:
            self._add_relation(
                prop_term, S223_URI, "hasEnumerationKind", self._term(prop_data)
            )

        substance_name = prop_data.get("substance")
        substance_uri = prop_data.get("substance-uri")
        if substance_name:
            self._add_relation(
                prop_term,
                S223_URI,
                "ofSubstance",
                self.model.term(substance_uri or S223_URI, substance_name),
            )

        if converted_units:
            self._add_relation(
                prop_term,
                S223_URI,
                "hasUnit",
                self.model.term(unit_uri, converted_units),
            )

        self.property_dict[prop_id] = {
            "property": prop_data[NAME_KEY],
            "prop_type": prop_type,
            "prop_uri": prop_data[URI_KEY],
            "parent_id": self._sanitize_id(parent_id),
            "medium": medium_name,
            "medium_uri": medium_uri,
            "role": role_name,
            "role_uri": role_uri,
            "substance": substance_name,
            "substance_uri": substance_uri,
            "source_unit_id": None,
            "dest_unit_id": None,
            "is_quant_kind": is_quant_kind,
            UNITS_KEY: unit_dict,
            "term": prop_term,
        }
        return self.property_dict[prop_id]

    def translate_tag(self, tag: Tag):
        tag_id = self._sanitize_id(tag.id)
        parent_id = self._sanitize_id(tag.parent_id)
        unit_dict = {}
        converted_units = None
        unit_uri = None

        try:
            unit_dict = self.convert_units(tag.units)
            converted_units = unit_dict.get(NAME_KEY)
            unit_uri = unit_dict.get(URI_KEY)
        except AttributeError:
            pass

        prop_data, is_quant_kind = self.convert_tag_type(tag.tag_type)
        prop_type = (
            "QuantifiableObservableProperty"
            if is_quant_kind
            else "EnumeratedObservableProperty"
        )
        tag_term = self._local(tag_id)

        self.model.add_type(tag_term, self.model.term(S223_URI, prop_type))
        if tag.contents:
            medium_dict = self.convert_contents(tag.contents)
            medium_name = medium_dict[NAME_KEY]
            medium_uri = medium_dict[URI_KEY]
            self._add_medium_and_role(tag_term, medium_dict, "ofMedium")
            role_name = medium_dict.get("role")
            role_uri = medium_dict.get("role-uri") if role_name is not None else None
        else:
            medium_name, medium_uri, role_name, role_uri = None, None, None, None

        if is_quant_kind:
            self._add_relation(
                tag_term, QUDT_URI, "hasQuantityKind", self._term(prop_data)
            )
        else:
            self._add_relation(
                tag_term, S223_URI, "hasEnumerationKind", self._term(prop_data)
            )

        substance_name = prop_data.get("substance")
        substance_uri = prop_data.get("substance-uri")
        if substance_name:
            self._add_relation(
                tag_term,
                S223_URI,
                "ofSubstance",
                self.model.term(substance_uri or S223_URI, substance_name),
            )

        if converted_units:
            self._add_relation(
                tag_term,
                S223_URI,
                "hasUnit",
                self.model.term(unit_uri, converted_units),
            )

        self.property_dict[tag_id] = {
            "property": prop_data[NAME_KEY],
            "prop_type": prop_type,
            "prop_uri": prop_data[URI_KEY],
            "parent_id": parent_id,
            "medium": medium_name,
            "medium_uri": medium_uri,
            "role": role_name,
            "role_uri": role_uri,
            "substance": substance_name,
            "substance_uri": substance_uri,
            "source_unit_id": tag.source_unit_id,
            "dest_unit_id": tag.dest_unit_id,
            "is_quant_kind": is_quant_kind,
            UNITS_KEY: unit_dict,
            "term": tag_term,
        }
        return self.property_dict[tag_id]

    def _properties_for_parent(self, parent_id: str):
        parent_id = self._sanitize_id(parent_id)
        return [
            prop_attrs["term"]
            for prop_attrs in self.property_dict.values()
            if prop_attrs["parent_id"] == parent_id
        ]

    def _add_parent_properties(self, parent: SemanticTerm, parent_id: str):
        for prop_term in self._properties_for_parent(parent_id):
            self._add_relation(parent, S223_URI, "hasProperty", prop_term)

    def translate_node(self, node: Node):
        pypes_class = type(node).__name__
        node_data = self.mapping[TOP_LEVEL_KEY]["nodes"][pypes_class]
        node_id = self._sanitize_id(node.id)
        node_term = self._local(node_id)

        self.model.add_type(node_term, self._term(node_data))
        if node_data.get(PROCESS_KEY):
            self._add_relation(
                node_term,
                WATR_URI,
                "hasProcess",
                self.model.term(WATR_URI, node_data[PROCESS_KEY]),
            )

        conn_point_list = []
        conn_from_list = []
        conn_to_list = []
        conn_point_in = None
        conn_point_out = None

        for conn_id in self.node_to_conn_ids.get(node.id, []):
            conn_data = self.conn_dict[conn_id]
            if conn_data["destination"] == node.id:
                conn_point_list.append(conn_data["dest_conn_point"])
                conn_from_list.append(conn_data["source"])
                conn_point_in = conn_data["dest_conn_point"]
            elif conn_data["source"] == node.id:
                conn_point_list.append(conn_data["source_conn_point"])
                conn_to_list.append(conn_data["destination"])
                conn_point_out = conn_data["source_conn_point"]
            else:
                raise ValueError(
                    "Connection `source` or `destination` must match node `id`"
                )

            if conn_point_in and conn_point_out:
                self._add_relation(
                    node_term, S223_URI, "cnx", self._local(conn_point_in)
                )
                self._add_relation(
                    node_term, S223_URI, "cnx", self._local(conn_point_out)
                )
                conn_point_in = None
                conn_point_out = None

        for conn_point in conn_point_list:
            self._add_relation(
                node_term, S223_URI, "hasConnectionPoint", self._local(conn_point)
            )

        media_added = set()
        for contents in node.input_contents + node.output_contents:
            medium_dict = self.convert_contents(contents)
            medium_name = medium_dict[NAME_KEY]
            if medium_name not in media_added:
                self._add_relation(
                    node_term, S223_URI, "hasMedium", self._term(medium_dict)
                )
                media_added.add(medium_name)

        for prop_name, prop_val in node.__dict__.items():
            if prop_name in CUSTOM_HANDLED_ATTRIBUTES or prop_name.startswith("_"):
                continue
            if prop_name in NOT_YET_IMPLEMENTED_ATTRIBUTES:
                warnings.warn(
                    f"The attribute {prop_name} for node {node_id} is not yet implemented in the WaTr codec!",
                    NotImplementedWarning,
                )
                continue
            self.translate_attribute(prop_name, prop_val, node_id, contents=None)

        self._add_parent_properties(node_term, node_id)
        self.node_dict[node_id] = {
            "node": node_data[NAME_KEY],
            "conn_points": conn_point_list,
            "connected_from": conn_from_list,
            "connected_to": conn_to_list,
            "term": node_term,
        }
        return self.node_dict[node_id]

    def translate_connection(self, conn: connection.Connection):
        pypes_class = type(conn).__name__
        conn_id = self._sanitize_id(conn.id)
        conn_data = self.mapping[TOP_LEVEL_KEY]["connections"][pypes_class]
        conn_term = self._local(conn_id)

        self.node_to_conn_ids.setdefault(conn.source.id, []).append(conn.id)
        self.node_to_conn_ids.setdefault(conn.destination.id, []).append(conn.id)

        self.model.add_type(conn_term, self._term(conn_data))
        source_conn_point, dest_conn_point = self.create_conn_points(conn)
        self._add_relation(conn_term, S223_URI, "cnx", self._local(source_conn_point))
        self._add_relation(conn_term, S223_URI, "cnx", self._local(dest_conn_point))

        medium_dict = self.convert_contents(conn.contents)
        medium_name = medium_dict[NAME_KEY]
        medium_uri = medium_dict[URI_KEY]
        self._add_medium_and_role(conn_term, medium_dict, "hasMedium")
        role_name = medium_dict.get("role")
        role_uri = medium_dict.get("role-uri") if role_name is not None else None

        for prop_name, prop_val in conn.__dict__.items():
            if prop_name in CUSTOM_HANDLED_ATTRIBUTES or prop_name.startswith("_"):
                continue
            if prop_name in NOT_YET_IMPLEMENTED_ATTRIBUTES:
                warnings.warn(
                    f"The attribute {prop_name} for connection {conn_id} is not yet implemented in the WaTr codec!",
                    NotImplementedWarning,
                )
                continue
            self.translate_attribute(
                prop_name, prop_val, conn_id, contents=conn.contents
            )

        self._add_parent_properties(conn_term, conn_id)
        self.conn_dict[conn.id] = {
            "connection": conn_data[NAME_KEY],
            "source": conn.source.id,
            "destination": conn.destination.id,
            "source_conn_point": source_conn_point,
            "dest_conn_point": dest_conn_point,
            "medium": medium_name,
            "medium_uri": medium_uri,
            "role": role_name,
            "role_uri": role_uri,
            "term": conn_term,
        }
        return self.conn_dict[conn.id]

    def translate_network(self, network: Network):
        for tag in network.get_all_tags():
            if isinstance(tag, VirtualTag):
                continue
            self.translate_tag(tag)

        for conn in network.get_all_connections():
            self.translate_connection(conn)

        for node in network.get_all_nodes():
            if isinstance(node, Network):
                self.translate_network(node)
            else:
                self.translate_node(node)

        if self.world.id != network.id:
            self.translate_node(network)

    def to_graph(self):
        if not self._translated:
            self.model.add_type(self._local(), self.model.term(OWL_URI, "Ontology"))
            self.translate_network(self.world)
            self._translated = True
        return self.model.graph

    def export_ttl(self, outpath):
        graph = self.to_graph()
        with open(outpath, "w", encoding="utf-8") as file:
            file.write(graph.serialize(format="turtle"))
