from pype_schema.tag import (Tag, VirtualTag, TagType)
from pype_schema.node import (Node, Network)
from pype_schema import (utils, connection)
import warnings
import pint
import json
import os

# add this file path to dir so that data folder is always accessible
WATR_CODEC_DIR = os.path.dirname(os.path.abspath(__file__))

# strings are stored as global variables to avoid hardcoding
TOP_LEVEL_KEY = "PyPES2WaTr"
UNITS_KEY = "units"
NAME_KEY = "name"
URI_KEY = "uri"
ENUM_KIND_STR = "EnumerationKind"
QUANT_KIND_STR = "QuantityKind"

# These attributes are handled by custom logic and not automatically
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

# TODO: implement conversion of the below attributes
NOT_YET_IMPLEMENTED_ATTRIBUTES = [
    "heating_values",
    "pressure",
    "flow_rate",
    "bidirectional",
    "pump_type",
    "pump_curve",
    "area",
    "selectivity",
    "settling_time",
]

# Define a custom warning category
class NotImplementedWarning(UserWarning):
    pass

class PyPES2WaTr:
    def __init__(
        self, 
        network: Network, 
        local_prefix: str,
        mapping_path=WATR_CODEC_DIR + "/data/pypes_watr_mapping.json",
        uri_mapping_path=WATR_CODEC_DIR + "/data/uri_mapping.json"
    ):
        self.world = network
        self.local_prefix = local_prefix
        with open(mapping_path, "r", encoding="utf-8") as file: 
            self.mapping = json.load(file)
        with open(uri_mapping_path, "r", encoding="utf-8") as file: 
            self.uri_mapping = json.load(file)
        self.property_dict = {}
        self.node_to_conn_ids = {}
        self.node_dict = {}
        self.conn_dict = {}
        self.conn_point_dict = {}

    def get_uri_prefix(self, uri: str):
        return self.uri_mapping[uri]

    def convert_units(self, units: pint.Unit):
        # Look up PyPES2WaTr mapping for Pint units to QUDT
        unit_dict = self.mapping[TOP_LEVEL_KEY][UNITS_KEY][str(units)]
        return unit_dict

    def convert_contents(self, contents: utils.ContentsType): 
        # Look up PyPES2WaTr mapping for PyPES ContentsType to WaTr properties
        contents_dict = self.mapping[TOP_LEVEL_KEY]["contents_types"][contents.name]
        return contents_dict

    def convert_attribute(self, attr_name: str):
        # Look up PyPES2WaTr mapping for PyPES TagType to WaTr properties
        # Also return true/false for quantity vs. enum kind
        prop_dict = self.mapping[TOP_LEVEL_KEY]["attributes"][attr_name]
        is_quant_kind = ENUM_KIND_STR not in prop_dict[NAME_KEY]
        
        return prop_dict, is_quant_kind

    def convert_tag_type(self, tag_type: TagType):
        # Look up PyPES2WaTr mapping for PyPES TagType to WaTr properties
        # Also return true/false for quantity vs. enum kind
        prop_dict = self.mapping[TOP_LEVEL_KEY]["tag_types"][tag_type.name]
        is_quant_kind = ENUM_KIND_STR not in prop_dict[NAME_KEY]
        
        return prop_dict, is_quant_kind

    def generate_conn_point_name(self, name: str):
        try:
            while self.conn_point_dict[name]:
                old_num = int(name[-1])
                name = name[:-2] + "-" + str(old_num + 1)
        except KeyError:
            pass
        return name

    # SAMPLE CONNECTION POINTS OUTPUT
    # wbs:Primary_Sedimentation_Junction-outlet-cp-2 a s223:OutletConnectionPoint ;
    #     s223:cnx wbs:conn-Primary_Sedimentation_Junction-to-AS_Aeration_Basin ;
    #     s223:connectsAt wbs:conn-Primary_Sedimentation_Junction-to-AS_Aeration_Basin ;
    #     s223:connectsThrough wbs:conn-Primary_Sedimentation_Junction-to-AS_Aeration_Basin ;
    #     s223:hasMedium s223:Medium-Water .
    #
    # wbs:AS_Aeration_Basin-in a s223:InletConnectionPoint ;
    #     s223:connectsAt wbs:conn-Primary_Sedimentation_Junction-to-AS_Aeration_Basin ;
    #     s223:connectsThrough wbs:conn-Primary_Sedimentation_Junction-to-AS_Aeration_Basin ;
    #     s223:hasMedium s223:Medium-Water .

    def create_conn_points(self, conn: connection.Connection):
        source_name = conn.source.id + "-cp-1"
        self.generate_conn_point_name(source_name)
        source_str = f"{self.local_prefix}:{source_name} a s223:OutletConnectionPoint ;\n"
        dest_name = conn.destination.id + "-cp-1"
        self.generate_conn_point_name(dest_name)
        dest_str = f"{self.local_prefix}:{dest_name} a s223:InletConnectionPoint ;\n"

        medium_dict = self.convert_contents(conn.contents)
        medium_name = medium_dict[NAME_KEY]
        medium_uri = medium_dict[URI_KEY]
        source_str += f"    s223:hasMedium {medium_uri}:{medium_name} ;\n"
        dest_str += f"    s223:hasMedium {medium_uri}:{medium_name} ;\n"
        role = medium_dict.get("role")
        if role:
            source_str += f"    s223:hasRole {medium_dict["role-uri"]}:{role} .\n"
        else: # if no role, change the closing `;` to `.`
            source_str = source_str[:-2] + ".\n"
            dest_str = dest_str[:-2] + ".\n"

        # NOTE: ignoring connectsAt and connectsThrough as those can be inferred 
        self.conn_point_dict[source_name] = {
            "node": conn.source.id,
            "connection": conn.id,
            "ttl_str": source_str,
        }
        self.conn_point_dict[dest_name] = {
            "node": conn.destination.id,
            "connection": conn.id,
            "ttl_str": dest_str,
        }
        return source_name, dest_name

    def translate_attribute(self, attr_name, value, parent_id, contents=None):
        """Converts an attribute from a PyPES node or connection to a WaTr property.
        
        Parameters
        ----------
        attr_name : str
            name of the attribute

        value : pint.Quantity, float, str, or dict
            value of the node or connection's attribute

        parent_id : str
            name of the parent node or connection

        contents : utils.ContentsType
            Optional PyPES contents to be converted to WaTr media. 
            Default is None, for cases where contents cannot be automatically determined.
        
        Returns
        -------
        dict
            A dictionary of the property details, including Turtle (.ttl) string representation
        """
        prop_id = parent_id + attr_name
        # TODO: handle dictionary attributes
        try: # if Pint object, there will be units and magnitude fields
            converted_units = self.convert_units(value.units)
            value = value.magnitude
        except AttributeError: # if no `units` attribute, assume value is directly stored
            converted_units = None
        prop_data, is_quant_kind = self.convert_attribute(attr_name)

        if is_quant_kind:
            prop_type = "QuantifiableProperty"
            prop_str = f"    qudt:hasQuantityKind {prop_data['uri']}:{prop_data['name']} ;\n"
        else:
            prop_type = "EnumerableProperty"
            prop_str = f"    S223:hasEnumerationKind {prop_data['uri']}:{prop_data['name']} ;\n"

        result_str = f"{self.local_prefix}:{prop_id} a s223:{prop_type} ;\n"
        
        # contents may be impossible to automatically discern for nodes, hence this check
        if contents is not None:
            # TODO: should Role be applied elsewhere or does it make sense in the property itself?
            medium_dict = self.convert_contents(contents)
            medium_name = medium_dict[NAME_KEY]
            medium_uri = medium_dict[URI_KEY]
            result_str += f"    s223:ofMedium {medium_uri}:{medium_name} ;\n"
            role = medium_dict.get("role")
            if role is not None:
                role_name = role
                role_uri = medium_dict["role-uri"]
                result_str += f"    s223:hasRole {medium_dict["role-uri"]}:{role} ;\n"
            else:
                role_name, role_uri = None, None
        else:
            medium_name, medium_uri, role_name, role_uri = None, None, None, None

        result_str += prop_str
        substance_name = prop_data.get("substance")
        if substance_name:
            result_str += f"    s223:ofSubstance s223:{substance} ;\n"
        else:
            substance_uri = None
        
        if converted_units:
            result_str += f"    s223:hasUnit s223:{converted_units} .\n"
        else: # if no units, change the closing `;` to `.`
            result_str = result_str[:-2] + ".\n"

        self.property_dict[prop_id] = {
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
            "source_unit_id": None, # TODO: use this downstream
            "dest_unit_id": None, # TODO: use this downstream
            "is_quant_kind": is_quant_kind,
            UNITS_KEY: converted_units,
            "ttl_str": result_str,
        }
        return self.property_dict[prop_id]

 
    def translate_tag(self, tag: Tag):
        # Tag attributes:
        # - id : str
        # - units : pint.Unit
        # - tag_type : TagType
        # - source_unit_id : int or str
        # - dest_unit_id : int or str
        # - parent_id : str
        # - totalized : bool
        # - contents : ContentsType
        # - manufacturer : str
        # - measure_freq : pint.Quantity
        # - report_freq : pint.Quantity
        # - downsample_method : DownsampleType
        # - calibration : Logbook
        # NOTE: totalized, manufacturer, measure_freq, report_freq, downsample_method, 
        # and calibration are all ignored
        tag_id = tag.id.replace(" ", "-")
        parent_id = tag.parent_id.replace(" ", "-")
        converted_units = self.convert_units(tag.units)
        prop_data, is_quant_kind = self.convert_tag_type(tag.tag_type)
        if is_quant_kind:
            prop_type = "QuantifiableObservableProperty"
            prop_str = f"    qudt:hasQuantityKind {prop_data[URI_KEY]}:{prop_data[NAME_KEY]} ;\n"
        else:
            prop_type = "EnumerableObservableProperty"
            prop_str = f"    S223:hasEnumerationKind {prop_data[URI_KEY]}:{prop_data[NAME_KEY]} ;\n"
        
        result_str = f"{self.local_prefix}:{tag_id} a s223:{prop_type} ;\n"
        if tag.contents:
            # TODO: should Role be applied elsewhere or does it make sense in the property itself?
            medium_dict = self.convert_contents(tag.contents)
            medium_name = medium_dict[NAME_KEY]
            medium_uri = medium_dict[URI_KEY]
            result_str += f"    s223:ofMedium {medium_uri}:{medium_name} ;\n"
            role = medium_dict.get("role")
            if role is not None:
                role_name = role
                role_uri = medium_dict["role-uri"]
                result_str += f"    s223:hasRole {medium_dict["role-uri"]}:{role} ;\n"
            else:
                role_name, role_uri = None, None
        else:
            medium_name, medium_uri, role_name, role_uri = None, None, None, None

        result_str += prop_str
        substance_name = prop_data.get("substance")
        if substance_name:
            result_str += f"    s223:ofSubstance s223:{substance} ;\n"
        else:
            substance_uri = None
        result_str += f"    s223:hasUnit s223:{converted_units} .\n"
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
            "source_unit_id": tag.source_unit_id, # TODO: use this downstream
            "dest_unit_id": tag.dest_unit_id, # TODO: use this downstream
            "is_quant_kind": is_quant_kind,
            UNITS_KEY: converted_units,
            "ttl_str": result_str,
        }
        return self.property_dict[tag_id]
        
    # SAMPLE NODE OUTPUT:
    # wbs:AS_Aeration_Basin a nawi:AerationBasin ;
    #     s223:cnx wbs:AS_Aeration_Basin-in,
    #         wbs:AS_Aeration_Basin-out ;
    #     s223:connected wbs:AS_Secondary_Sedimentation ;
    #     s223:connectedThrough wbs:conn-AS_Aeration_Basin-to-AS_Secondary_Sedimentation,
    #         wbs:conn-Primary_Sedimentation_Junction-to-AS_Aeration_Basin ;
    #     s223:connectedTo wbs:AS_Secondary_Sedimentation ;
    #     s223:hasConnectionPoint wbs:AS_Aeration_Basin-in,
    #         wbs:AS_Aeration_Basin-out ;
    #     s223:hasProperty wbs:AS_Aeration_Basin-mlss-concentration,
    #         wbs:AS_Aeration_Basin-volume .

    def translate_node(self, node: Node):
        pypes_class = type(node).__name__
        node_data = self.mapping[TOP_LEVEL_KEY]["nodes"][pypes_class]
        node_id = node.id.replace(" ", "-")
        node_str = f"{self.local_prefix}:{node_id} a {node_data[URI_KEY]}:{node_data[NAME_KEY]} ;\n"
        
        # TODO: add handling of source and destination unit IDs to below logic
        conn_point_list = []
        conn_from_list = []
        conn_to_list = []
        conn_point_in = None
        conn_point_out = None
        for conn_id in self.node_to_conn_ids[node.id]:
            # TODO: double check below logic
            if self.conn_dict[conn_id]["destination"] == node.id:
                conn_point_list.append(self.conn_dict[conn_id]["dest_conn_point"])
                conn_from_list.append(self.conn_dict[conn_id]["source"])
                conn_point_in = self.conn_dict[conn_id]["dest_conn_point"]
                # node_str += f"    s223:connectedFrom {self.local_prefix}:{self.conn_dict[conn_id]["source"]} ;\n"
            elif self.conn_dict[conn_id]["source"] == node.id:
                conn_point_list.append(self.conn_dict[conn_id]["source_conn_point"])
                conn_to_list.append(self.conn_dict[conn_id]["destination"])
                conn_point_out = self.conn_dict[conn_id]["source_conn_point"]
                # node_str += f"    s223:connectedTo {self.local_prefix}:{self.conn_dict[conn_id]["destination"]} ;\n"
            else:
                raise ValueError("Connection `source` or `destination` must match node `id`")
        
        # TODO: how to handle if there are three connection points?
        # TODO: is this `cnx` necessary? I saw it from the examples, but am not sure
        if conn_point_in and conn_point_out:
            node_str += f"    s223:cnx {self.local_prefix}:{conn_point_in} {self.local_prefix}:{conn_point_out} ;\n"
        conn_point_str = ""
        for conn_point in conn_point_list:
            if conn_point_str:
                conn_point_str += f" {self.local_prefix}:{conn_point}"
            else:
                conn_point_str += f"    s223:hasConnectionPoint {self.local_prefix}:{conn_point}"
        if conn_point_str:
            conn_point_str += " ;\n"
            node_str += conn_point_str

        media_added = []
        for contents in node.input_contents + node.output_contents:
            medium_dict = self.convert_contents(contents)
            medium_name = medium_dict[NAME_KEY]
            medium_uri = medium_dict[URI_KEY]
            if medium_name not in media_added:
                node_str += f"    s223:hasMedium {medium_uri}:{medium_name} ;\n"
                media_added.append(medium_name)

        for prop_name, prop_val in node.__dict__.items(): # get all attributes
            if prop_name in CUSTOM_HANDLED_ATTRIBUTES or prop_name[0] == "_":
                # ignore internal attributes starting with `_`
                # and those handled elsewhere (`CUSTOM_HANDLED_ATTRIBUTES`)
                pass
            elif prop_name in NOT_YET_IMPLEMENTED_ATTRIBUTES:
                warnings.warn(
                    f"The attribute {prop_name} for node {node_id} is not yet implemented in the WaTr codec!",
                    NotImplementedWarning,
                )
            else:
                # create property and add to property_dict
                # TODO: try to automatically determine contents
                self.translate_attribute(prop_name, prop_val, node_id, contents=None)

        # TODO: check that hasProperty can have unlimited entries      
        prop_str = None
        for prop_id, prop_attrs in self.property_dict.items():
            # NOTE: we have to use unmodified `node.id` NOT `node_id` to be consistent with `property_dict`
            if prop_attrs["parent_id"] == node.id:
                if prop_str is None:
                    prop_str = f"    s223:hasProperty {self.local_prefix}:{prop_id}"
                else:
                    prop_str += f" {self.local_prefix}:{prop_id}"
            if prop_str: # if not None, add the closing period
                prop_str += " .\n"
                node_str += prop_str
            else: # if no properties, change the closing `;` to `.`
                node_str = node_str[:-2] + ".\n"

        # TODO: add more attributes to below dictionary
        self.node_dict[node_id] = {
            "node": node_data[NAME_KEY],
            "conn_points": conn_point_list,
            "connected_from": conn_from_list,
            "connected_to": conn_to_list,
            "ttl_str": node_str,
        }
        return self.node_dict[node_id]

    # SAMPLE CONNECTION POINT AND CONNECTION OUTPUT:
    # wbs:conn-Primary_Sedimentation_Junction-to-AS_Aeration_Basin a s223:Connection,
    #     s223:Pipe ;
    #     s223:cnx wbs:AS_Aeration_Basin-in,
    #         wbs:Primary_Sedimentation_Junction-outlet-cp-2 ;
    #     s223:connectsFrom wbs:Primary_Sedimentation_Junction ;
    #     s223:connectsTo wbs:AS_Aeration_Basin .

    def translate_connection(self, conn: connection.Connection):
        pypes_class = type(conn).__name__
        conn_id = conn.id.replace(" ", "-")
        conn_data = self.mapping[TOP_LEVEL_KEY]["connections"][pypes_class]

        # This dictionary enables us to add the correct connections to each node
        try:
            self.node_to_conn_ids[conn.source.id].append(conn.id)
        except KeyError:
            self.node_to_conn_ids[conn.source.id] = [conn.id]
        try:
            self.node_to_conn_ids[conn.destination.id].append(conn.id)
        except KeyError:
            self.node_to_conn_ids[conn.destination.id] = [conn.id]

        conn_str = f"{self.local_prefix}:{conn_id} a {conn_data[URI_KEY]}:{conn_data[NAME_KEY]} ;\n"
        source_conn_point, dest_conn_point = self.create_conn_points(conn)
        conn_str += f"    s223:cnx {self.local_prefix}:{source_conn_point} {self.local_prefix}:{dest_conn_point} ;\n"

        # TODO: add logic to handle source and destination unit IDs
        # TODO: add logic for bidirectional connections
        for prop_name, prop_val in conn.__dict__.items(): # get all attributes
            if prop_name in CUSTOM_HANDLED_ATTRIBUTES or prop_name[0] == "_":
                # ignore internal attributes starting with `_`
                # and those handled elsewhere (`CUSTOM_HANDLED_ATTRIBUTES`)
                pass
            elif prop_name in NOT_YET_IMPLEMENTED_ATTRIBUTES:
                warnings.warn(
                    f"The attribute {prop_name} for connection {conn_id} is not yet implemented in the WaTr codec!",
                    NotImplementedWarning,
                )
            else:
                # create property and add to property_dict
                self.translate_attribute(prop_name, prop_val, conn_id, contents=conn.contents)

        # TODO: check that hasProperty can have unlimited entries      
        prop_str = None
        for prop_id, prop_attrs in self.property_dict.items():
            # NOTE: we have to use unmodified `conn.id` NOT `node_id` to be consistent with `property_dict`
            if prop_attrs["parent_id"] == conn.id:
                if prop_str is None:
                    prop_str = f"    s223:hasProperty {self.local_prefix}:{prop_id}"
                else:
                    prop_str += f" {self.local_prefix}:{prop_id}"
            if prop_str: # if not None, add the closing period
                prop_str += " .\n"
                conn_str += prop_str
            else: # if no properties, change the closing `;` to `.`
                conn_str = conn_str[:-2] + ".\n"

        self.conn_dict[conn_id] = {
            "connection": conn_data[NAME_KEY],
            "source": conn.source.id,
            "destination": conn.destination.id,
            "source_conn_point": source_conn_point,
            "dest_conn_point": dest_conn_point,
            "ttl_str": conn_str
        }

    # TODO: add contains and isContained logic to network hierarchy
    def translate_network(self, network: Network):
        for tag in network.get_all_tags():
            if isinstance(tag, VirtualTag):
                pass # TODO: implement VirtualTag to Acquirium soft sensor translator
            else:
                self.translate_tag(tag)
        for conn in network.get_all_connections():
            print(conn)
            self.translate_connection(conn)
        for node in network.get_all_nodes():
            if isinstance(node, Network):
                self.translate_network(node)
            else:
                self.translate_node(node)
        if self.world.id != network.id:
            self.translate_node(network)
    
    def generate_header(self):
        header = ""
        for key, val in self.uri_mapping.items():
            header += f"@prefix {key}:{val} .\n"
        header += f"@prefix {self.local_prefix}:<urn:ex/> .\n\n"
        header += f"{self.local_prefix}: a owl:Ontology .\n"
        return header

    def export_ttl(self, outpath):
        self.translate_network(self.world)
        result = self.generate_header()
        for prop_data in self.property_dict.values():
            result += "\n" + prop_data["ttl_str"]
        for conn_data in self.conn_dict.values():
            result += "\n" + conn_data["ttl_str"]
        for conn_point_data in self.conn_point_dict.values():
            result += "\n" + conn_point_data["ttl_str"]
        for node_data in self.conn_point_dict.values():
            result += "\n" + node_data["ttl_str"]

        with open(outpath, "w", encoding="utf-8") as file:
            file.write(result)