import pype_schema as pypes
import pint
import json

class PyPES2WaTr:
    def __init__(
        self, 
        node: pypes.node.Node, 
        mapping_path="data/pypes_watr_mapping.json",
        uri_mapping_path="data/uri_mapping.json"
    ):
        self.world = network
        self.mapping = json.load(mapping_path)
        self.uri_mapping = json.load(uri_mapping_path)
        self.property_dict = {}

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
        prop_dict = self.mapping["PyPES2WaTr"]["tag_types"][tag_type.name]
        is_quant_kind = "EnumerationKind" not in prop_dict["name"]
        
        return prop_dict, is_quant_kind
 
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
        prop_dict, is_quant_kind = self.convert_tag_type(tag.tag_type)
        if is_quant_kind:
            prop_type = "QuantifiableObservableProperty"
            prop_str = f"    qudt:hasQuantityKind {prop_dict["uri"]}:{prop_dict["name"]} ;\n"
        else:
            prop_type = "EnumerableObservableProperty"
            medium_str = f"    S223:hasEnumerationKind {prop_dict["uri"]}:{prop_dict["name"]} ;\n"
        result_str = f"wbs:{tag_id} a s223:{prop_type} ;\n"
        contents_dict = self.convert_contents(tag.contents)
        results_str += f"    s223:ofMedium {contents_dict["uri"]}:{contents_dict["name"]} ;\n"
        result_str += prop_str
        substance = prop_dict.get("substance")
        if substance:
            result_str += f"    s223:ofSubstance s223:{substance} ;\n"
        result_str += f"    s223:hasUnit s223:{converted_units} ."
        self.property_dict[tag_id] = {
            "prop_type": prop_type,
            "parent_id": parent_id,
            "medium": contents_dict["name"],
            "substance": substance,
            "source_unit_id": tag.source_unit_id,
            "dest_unit_id": tag.dest_unit_id,
            "is_quant_kind": is_quant_kind,
            "units": converted_units,
            "ttl_str": result_str,
        }
        return self.property_dict[tag_id]
        
    def translate_node(self, node: pypes.Node):
        # TODO: check if node is in mapping file
        pypes_class = type(node).__name__

    def translate_connection(self, conn: pypes.Connection):
        # TODO: check if connection is in mapping file
        pypes_class = type(connection).__name__

    def translate_network(self, network: pypes.Network):
        for node in network.get_all_nodes():
            if isinstance(node, pypes.Network):
                self.translate_network(node)
            else:
                self.translate_node(node)
        for conn in network.get_all_connections():
            self.translate_connection(conn)
        for tag in network.get_all_tags():
            if isinstance(tag, pypes.VirtualTag):
                pass # TODO: implement VirtualTag to Acquirium soft sensor translator
            else:
                self.translate_tag(tag)
    
    def export_ttl(self):
        result = translate_network(self.world)
        # export resulting string or other data structure to `.ttl` file

    # TODO: figure out to handle outputs from each translation