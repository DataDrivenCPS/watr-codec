import pype_schema as pypes
import pint
import json

# TODO: add hardcoded strings as global variables

class PyPES2WaTr:
    def __init__(
        self, 
        network: pypes.node.Network, 
        local_prefix: str,
        mapping_path="data/pypes_watr_mapping.json",
        uri_mapping_path="data/uri_mapping.json"
    ):
        self.world = network
        self.local_prefix = local_prefix
        self.mapping = json.load(mapping_path)
        self.uri_mapping = json.load(uri_mapping_path)
        self.property_dict = {}
        self.node_to_conn_ids = {}
        self.node_dict = {}
        self.conn_dict = {}
        self.conn_point_dict = {}

    def get_uri_prefix(self, uri: str):
        return self.uri_mapping[uri]

    def convert_units(self, units: pint.Unit):
        # Look up PyPES2WaTr mapping for Pint units to QUDT
        unit_dict = self.mapping["PyPES2WaTr"]["units"][str(units)]
        return unit_dict

    def convert_contents(self, contents: pypes.utils.ContentsType): 
        # Look up PyPES2WaTr mapping for PyPES ContentsType to WaTr properties
        contents_dict = self.mapping["PyPES2WaTr"]["contents_types"][str(contents)]
        return contents_dict

    def convert_tag_type(self, tag_type: pypes.tag.TagType):
        # Look up PyPES2WaTr mapping for PyPES TagType to WaTr properties
        # Also return true/false for quantity vs. enum kind
        prop_dict = self.mapping["PyPES2WaTr"]["properties"][tag_type.name]
        is_quant_kind = "EnumerationKind" not in prop_dict["name"]
        
        return prop_dict, is_quant_kind

    def generate_conn_point_name(self, name: str):
        try:
            while self.conn_point_dict[name]:
                old_num = int(name[:-1])
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

    def create_conn_points(self, conn: pypes.connection.Connection):
        source_name = conn.source.id + "-cp-1"
        self.generate_conn_point_name(source_name)
        source_str = f"{self.local_prefix}:{source_name} a s223:OutletConnectionPoint ;\n"
        dest_name = conn.destination.id + "-cp-1"
        self.generate_conn_point_name(dest_name)
        dest_str = f"{self.local_prefix}:{dest_name} a s223:InletConnectionPoint ;\n"

        medium_dict = self.convert_contents(conn.contents)
        medium_name = medium_dict["name"]
        medium_uri = medium_dict["uri"]
        source_str += f"    s223:hasMedium {medium_uri}:{medium_name} ;\n"
        dest_str += f"    s223:hasMedium {medium_uri}:{medium_name} ;\n"
        role = medium_dict.get("role")
        if role:
            source_str += f"    s223:hasRole {medium_dict["role-uri"]}:{role} .\n"
        else: # if no role, change the closing `;` to `.`
            source_str = source_str[:-2] + ".\n"
            dest_str = dest_str[:-2] + ".\n"

        # NOTE: ignoring connectsAt and connectsThrough as those can be inferred 
        self.conn_point_dict[source_cp_name] = {
            "node": conn.source.id,
            "connection": conn.id,
            "ttl_str": source_str,
        }
        self.conn_point_dict[dest_cp_name] = {
            "node": conn.destination.id,
            "connection": conn.id,
            "ttl_str": dest_str,
        }
        return source_cp_name, dest_cp_name
 
    def translate_tag(self, tag: pypes.Tag):
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
        # - calibration : pypes.Logbook
        # NOTE: totalized, manufacturer, measure_freq, report_freq, downsample_method, 
        # and calibration are all ignored
        tag_id = tag.id.replace(" ", "-")
        parent_id = tag.parent_id.replace(" ", "-")
        converted_units = self.convert_units(tag.units)
        prop_data, is_quant_kind = self.convert_tag_type(tag.tag_type)
        if is_quant_kind:
            prop_type = "QuantifiableObservableProperty"
            prop_str = f"    qudt:hasQuantityKind {prop_data["uri"]}:{prop_data["name"]} ;\n"
        else:
            prop_type = "EnumerableObservableProperty"
            prop_str = f"    S223:hasEnumerationKind {prop_data["uri"]}:{prop_data["name"]} ;\n"
        result_str = f"{self.local_prefix}:{tag_id} a s223:{prop_type} ;\n"
        if tag.contents:
            # TODO: should Role be applied elsewhere or does it make sense in the property itself?
            medium_dict = self.convert_contents(tag.contents)
            medium_name = medium_dict["name"]
            medium_uri = medium_dict["uri"]
            results_str += f"    s223:ofMedium {medium_uri}:{medium_name} ;\n"
            role = medium_dict.get("role")
            if role:
                results_str += f"    s223:hasRole {medium_dict["role-uri"]}:{role} ;\n"
        else:
            medium_name = None
            medium_uri = None
            role_name = None
            role_uri = None

        result_str += prop_str
        substance_name = prop_data.get("substance")
        if substance_name:
            result_str += f"    s223:ofSubstance s223:{substance} ;\n"
        else:
            substance_uri = None
        result_str += f"    s223:hasUnit s223:{converted_units} .\n"
        self.property_dict[tag_id] = {
            "property": prop_data["name"],
            "prop_type": prop_type,
            "prop_uri": prop_data["uri"],
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
            "units": converted_units,
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

    def translate_node(self, node: pypes.Node):
        pypes_class = type(node).__name__
        node_data = self.mapping["PyPES2WaTr"]["nodes"][pypes_class]
        node_id = node.id.replace(" ", "-")
        result_str = f"{self.local_prefix}:{node_id} a {node_data["uri"]}:{node_data["name"]} ;\n"
        
        # TODO: add handling of source and destination unit IDs to below logic
        conn_point_list = []
        conn_from_list = []
        conn_to_list = []
        for conn_id in self.node_to_conn_ids[node.id]:
            # TODO: double check below logic
            if self.conn_dict[conn_id]["destination"] == node.id:
                conn_point_list.append(self.conn_dict[conn_id]["dest_conn_point"])
                conn_from_list.append(self.conn_dict[conn_id]["source"])
                # result_str += f"    s223:connectedFrom {self.local_prefix}:{self.conn_dict[conn_id]["source"]} ;\n"
            elif self.conn_dict[conn_id]["source"] == node.id:
                conn_point_list.append(self.conn_dict[conn_id]["source_conn_point"])
                conn_to_list.append(self.conn_dict[conn_id]["destination"])
                # result_str += f"    s223:connectedTo {self.local_prefix}:{self.conn_dict[conn_id]["destination"]} ;\n"
            else:
                raise ValueError("Connection `source` or `destination` must match node `id`")
        
        result_str += f"    s223:cnx {self.local_prefix}:{conn_point_in} {self.local_prefix}:{conn_point_out} ;\n"
        conn_point_str = ""
        for conn_point in conn_point_list:
            if conn_point_str:
                conn_point_str += f" {self.local_prefix}:{conn_point}"
            else:
                conn_point_str += f"    s223:hasConnectionPoint {self.local_prefix}:{conn_point}"
        if conn_point_str:
            conn_point_str += " ;\n"
            result_str += conn_point_str

        medium_dict = self.convert_contents(node.contents)
        medium_name = medium_dict["name"]
        medium_uri = medium_dict["uri"]
        source_str += f"    s223:hasMedium {medium_uri}:{medium_name} ;\n"

        # TODO: check that hasProperty can have unlimited entries
        for prop_id, prop_attrs in self.property_dict.items():
            # NOTE: we have to use unmodified `node.id` NOT `node_id` to be consistent with `property_dict`
            prop_str = None
            if prop_attrs["parent_id"] == node.id:
                if prop_str is None:
                    prop_str = f"    s223:hasProperty {self.local_prefix}:{prop_id}"
                else:
                    prop_str += f" {self.local_prefix}:{prop_id}"
            if prop_str: # if not None, add the closing period
                prop_str += " .\n"
                result_str += prop_str
            else: # if no properties, change the closing `;` to `.`
                result_str = result_str[:-2] + ".\n"

        # TODO: how to track all the attributes of PyPES nodes (e.g., flow rate)?
        # TODO: add more attributes to below dictionary
        self.node_dict[node_id] = {
            "node": node_data["name"],
            "conn_points": conn_point_list,
            "connected_from": conn_from_list,
            "connected_to": conn_to_list,
            "ttl_str": result_str,
        }
        return self.node_dict[node_id]

    # SAMPLE CONNECTION POINT AND CONNECTION OUTPUT:
    # wbs:conn-Primary_Sedimentation_Junction-to-AS_Aeration_Basin a s223:Connection,
    #     s223:Pipe ;
    #     s223:cnx wbs:AS_Aeration_Basin-in,
    #         wbs:Primary_Sedimentation_Junction-outlet-cp-2 ;
    #     s223:connectsFrom wbs:Primary_Sedimentation_Junction ;
    #     s223:connectsTo wbs:AS_Aeration_Basin .

    def translate_connection(self, conn: pypes.Connection):
        pypes_class = type(connection).__name__
        conn_id = node.id.replace(" ", "-")
        conn_data = self.mapping["PyPES2WaTr"]["connections"][pypes_class]

        # This dictionary enables us to add the correct connections to each node
        try:
            self.node_to_conn_ids[conn.source.id].append(connection.id)
        except KeyError:
            self.node_to_conn_ids[conn.source.id] = [connection.id]
        try:
            self.node_to_conn_ids[conn.destination.id].append(connection.id)
        except KeyError:
            self.node_to_conn_ids[conn.destination.id] = [connection.id]

        conn_str = f"{self.local_prefix}:{conn_id} a {conn_data["uri"]}:{conn_data["name"]} ;\n"
        source_conn_point, dest_conn_point = self.create_conn_points(conn)
        conn_str += f"    s223:cnx {self.local_prefix}:{outlet_conn_point} {self.local_prefix}:{inlet_conn_point} ;\n"

        # TODO: add logic to handle source and destination unit IDs
        # TODO: add logic for bidirectional connections
        # TODO: how to track all the attributes of PyPES connections (e.g., diameter)?
        for prop_name, prop_value in vars(conn).items():
            prop_data = self.mapping["PyPES2WaTr"]["properties"][prop_name]

        self.conn_dict[conn_id] = {
            "connection": conn_data["name"],
            "source_conn_point": source_conn_point,
            "dest_conn_point": dest_conn_point,
            "ttl_str": conn_str
        }

    # TODO: add contains and isContained logic to network hierarchy
    def translate_network(self, network: pypes.Network):
        for tag in network.get_all_tags():
            if isinstance(tag, pypes.VirtualTag):
                pass # TODO: implement VirtualTag to Acquirium soft sensor translator
            else:
                self.translate_tag(tag)
        for conn in network.get_all_connections():
            self.translate_connection(conn)
        for node in network.get_all_nodes():
            if isinstance(node, pypes.Network):
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
        translate_network(self.world)
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