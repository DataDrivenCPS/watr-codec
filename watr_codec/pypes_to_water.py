import pype_schema as pypes
import pint
import json

class PyPES2WaTr:
    def __init__(self, node: pypes.node.Node, mapping_path="data/pypes_watr_mapping.json"):
        self.world = network
        self.mapping = json.load(mapping_path)
        self.property_dict = {}

    def convert_units(self, units: pint.Unit):
        # TODO: implement function for converting units from Pint to QUDT
        pass

    def convert_tag_type(self, tag_type: pypes.tag.TagType):
        # TODO: implement function for converting units from PyPES to QUDT
        # also return true/false for quantity vs. enum kind
        # This should rely on a PyPES2WaTr mapping that is for tags not nodes
        # TODO: nest PyPES2WaTr JSON
        pass

    def translate_tag(self, tag: pypes.Tag):
        try:
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
            converted_units = convert_units(tag.units)
            quant_or_enum_kind, is_quant_kind = convert_tag_type(tag.tag_type)
            result_str = f"wbs:{tag_id} a s223:QuantifiableObservableProperty ;\n"
            result_str += "    s223:ofMedium s223:Fluid-Water ;"
            if is_quant_kind:
                result_str += f"    s223:hasQuantityKind s223:{quant_or_enum_kind} ;"
            else:
                result_str += f"    s223:hasEnumerationKind s223:{quant_or_enum_kind} ;"
            result_str += f"    s223:hasUnit s223:{converted_units} ."
            self.property_dict[tag_id] = {
                "parent_id": parent_id,
                "source_unit_id": tag.source_unit_id,
                "dest_unit_id": tag.dest_unit_id,
                "is_quant_kind": is_quant_kind,
                "ttl_str": result_str,
            }
        except:
            pass
        
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