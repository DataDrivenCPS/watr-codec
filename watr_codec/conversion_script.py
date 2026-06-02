import json
import os
from typing import List, Dict, Any, Optional, Union

class PypeTag:
    def __init__(self, key: str, value: Any):
        self.key = key
        self.value = value

class PypeNode:
    def __init__(self, id: str, type: str, input_contents: Optional[List[str]] = None, output_contents: Optional[List[str]] = None, tags: Optional[Dict[str, PypeTag]] = None, **kwargs):
        self.id = id
        self.type = type
        self.input_contents = input_contents if input_contents is not None else []
        self.output_contents = output_contents if output_contents is not None else []
        self.tags = tags if tags is not None else {}
        self.properties = kwargs # To capture specialized node attributes

class PypeConnection:
    def __init__(self, id: str, source_node_id: str, target_node_id: str, type: str = "generic_connection", **kwargs):
        self.id = id
        self.source_node_id = source_node_id
        self.target_node_id = target_node_id
        self.type = type
        self.properties = kwargs # To capture specialized connection attributes

# WaTr Ontology Classes (Simplified)

class WatrProperty:
    def __init__(self, id: str, name: Optional[str] = None, value: Optional[Any] = None, unit: Optional[str] = None, refers_to: Optional[str] = None, type: Optional[str] = None):
        self.id = id # Unique identifier for the property instance
        self.name = name # Corresponds to hasName for generic properties
        self.value = value # Corresponds to hasValue for WaterQualityParameter
        self.unit = unit # Corresponds to hasMeasuringUnit for WaterQualityParameter
        self.refers_to = refers_to # Corresponds to refersTo for WaterQualityParameter (Substance ID)
        self.type = type # Corresponds to hasType for WaterQualityParameter (EnumerationKind ID)

class WatrEntity: # Base class for entities that can have properties and a name
    def __init__(self, id: str, name: Optional[str] = None):
        self.id = id
        self.name = name
        self.properties: List[WatrProperty] = []

class WatrEquipment(WatrEntity):
    def __init__(self, id: str, name: Optional[str] = None, type: Optional[str] = None):
        super().__init__(id, name)
        self.type = type

class WatrProcess(WatrEntity):
    def __init__(self, id: str, name: Optional[str] = None, type: Optional[str] = None):
        super().__init__(id, name)
        self.type = type # e.g., Process-Aeration, Process-Filtration
        self.has_parts: List[str] = [] # List of WatrEquipment IDs
        self.inputs: List[str] = [] # List of WaterStream IDs
        self.outputs: List[str] = [] # List of WaterStream IDs

class WatrStream(WatrEntity):
    def __init__(self, id: str, name: Optional[str] = None):
        super().__init__(id, name)

class WatrSubstance:
    def __init__(self, id: str, name: Optional[str] = None, type: Optional[str] = None):
        self.id = id
        self.name = name
        self.type = type # e.g., Ammonia, Chloride

class PypeToWatrConverter:
    # A mapping from Pype-schema Node types to WaTr Process or Component types
    TYPE_MAPPING = {
        "Aeration": "Process-Aeration",
        "AnaerobicDigestion": "Process-AnaerobicDigestion",
        "MembraneBioreactor": "Process-MembraneBioreactor",
        "ChlorinationBasin": "Process-Chlorination",
        "StaticMixer": "Process-Mixing",
        "MediaFilter": "Process-MediaFiltration",
        "CartridgeFilter": "Process-Filtration",
        "ROModule": "Process-ReverseOsmosis",
        "UV-AOPReactor": "Process-AdvancedOxidation",
        "Pump": "Pump",
        "Tank": "SedimentationTank",
        "Digester": "AnaerobicDigester",
        "Basin": "AerationBasin",
    }

    # Define which WaTr types are Process and which are Equipment for clarity
    WATR_PROCESS_TYPES = [
        "Process-Separation", "Process-Elutriation", "Process-Screening", "Process-Sedimentation",
        "Process-Filtration", "Process-MediaFiltration", "Process-SlowSandFiltration",
        "Process-RapidSandFiltration", "Process-Flotation", "Process-GasTransfer",
        "Process-Aeration", "Process-Mixing", "Process-Equalization", "Process-Dewatering",
        "Process-Centrifugation", "Process-Solidification", "Process-Crystallization",
        "Process-Evaporation", "Process-Condensation", "Process-Adsorption",
        "Process-GranularActivatedCarbon", "Process-MembraneProcess", "Process-ReverseOsmosis",
        "Process-ClosedCircuitReverseOsmosis", "Process-OsmoticallyAssistedReverseOsmosis",
        "Process-FeedReversalReverseOsmosis", "Process-MembraneDistillation",
        "Process-Electrodialysis", "Process-ElectroDialyticCrystallization",
        "Process-Comminution", "Process-BiosolidsDisposal", "Process-ChemicalAddition",
        "Process-Coagulation", "Process-Electrocoagulation", "Process-Flocculation",
        "Process-UVDisinfection", "Process-Disinfection", "Process-Chlorination",
        "Process-Dechlorination", "Process-pHAdjustment", "Process-Neutralization",
        "Process-Oxidation", "Process-AdvancedOxidation", "Process-Electrooxidation",
        "Process-Ozonation", "Process-Softening", "Process-ChemicalPrecipitation",
        "Process-Reduction", "Process-SolventExtraction", "Process-HighDensitySludge",
        "Process-IonExchange", "Process-Electrolysis", "Process-Incineration",
        "Process-FluidizedBedIncineration", "Process-Cogeneration", "Process-Nitrification",
        "Process-Denitrification", "Process-Bardenpho", "Process-ActivatedSludge",
        "Process-Biofiltration", "Process-TricklingFiltration",
        "Process-BiologicallyActiveFiltration", "Process-MembraneBioreactor",
        "Process-Digestion", "Process-AnaerobicDigestion", "Process-AerobicDigestion"
    ]
    
    WATR_EQUIPMENT_TYPES = [
        "AerationBasin", "AerobicDigester", "AnaerobicDigester", "CoagulationBasin",
        "FlocculationBasin", "SedimentationTank", "Filter", "MicrofiltrationUnit",
        "UltrafiltrationUnit", "NanofiltrationUnit", "ReverseOsmosisMembrane", "Screen",
        "GritChamber", "BeltThickener", "GravityThickener", "CentrifugalThickener",
        "DewateringUnit", "DisinfectionUnit", "ChlorinationUnit", "UltravioletLightUnit",
        "Pump", "Condenser", "Crystallizer", "Evaporator", "StaticMixer",
        "Aerator", "ChlorineDosingSystem", "CoagulantDosingSystem", "Ozonator", "Softener", "UVReactor"
    ]

    def __init__(self, mapping_path: Optional[str] = None):
        self.watr_processes: Dict[str, WatrProcess] = {}
        self.watr_equipment: Dict[str, WatrEquipment] = {}
        self.watr_streams: Dict[str, WatrStream] = {}
        self.watr_substances: Dict[str, WatrSubstance] = {}
        
        if mapping_path and os.path.exists(mapping_path):
            self._load_mapping(mapping_path)

    def _load_mapping(self, mapping_path: str):
        try:
            with open(mapping_path, 'r') as f:
                mapping_data = json.load(f)
            pypes_to_watr = mapping_data.get("PyPES2WaTr", {})
            for pype_type, watr_info in pypes_to_watr.items():
                watr_name = watr_info.get("name")
                if watr_name:
                    self.TYPE_MAPPING[pype_type] = watr_name
                    # Try to infer if it's a process or equipment
                    if watr_name.startswith("Process-") and watr_name not in self.WATR_PROCESS_TYPES:
                        self.WATR_PROCESS_TYPES.append(watr_name)
                    elif watr_name not in self.WATR_EQUIPMENT_TYPES and watr_name not in self.WATR_PROCESS_TYPES:
                        self.WATR_EQUIPMENT_TYPES.append(watr_name)
        except Exception as e:
            print(f"Error loading mapping: {e}")

    def _convert_pype_tag_to_watr_property(self, pype_tag: PypeTag, entity_id: str) -> WatrProperty:
        prop_id = f"{entity_id}_prop_{pype_tag.key}"
        return WatrProperty(id=prop_id, name=pype_tag.key, value=pype_tag.value)

    def _convert_pype_node_to_watr_entity(self, pype_node: PypeNode) -> Optional[Union[WatrProcess, WatrEquipment]]:
        watr_id = f"watr_{pype_node.id}"
        watr_name = pype_node.id

        watr_type_str = self.TYPE_MAPPING.get(pype_node.type, pype_node.type)

        watr_entity = None
        if watr_type_str in self.WATR_PROCESS_TYPES:
            watr_entity = WatrProcess(id=watr_id, name=watr_name, type=watr_type_str)
        elif watr_type_str in self.WATR_EQUIPMENT_TYPES:
            watr_entity = WatrEquipment(id=watr_id, name=watr_name, type=watr_type_str)
        else:
            print(f"Warning: PypeNode type '{pype_node.type}' (mapped to '{watr_type_str}') not found in known types. Defaulting to Equipment.")
            watr_entity = WatrEquipment(id=watr_id, name=watr_name, type=watr_type_str if watr_type_str else "Equipment")

        if watr_entity:
            for key, pype_tag in pype_node.tags.items():
                watr_entity.properties.append(self._convert_pype_tag_to_watr_property(pype_tag, watr_id))
            for key, value in pype_node.properties.items():
                prop_id = f"{watr_id}_prop_{key}"
                watr_entity.properties.append(WatrProperty(id=prop_id, name=key, value=value))

        return watr_entity

    def convert(self, pype_nodes: List[PypeNode], pype_connections: List[PypeConnection]) -> Dict[str, Any]:
        for node in pype_nodes:
            watr_entity = self._convert_pype_node_to_watr_entity(node)
            if watr_entity:
                if isinstance(watr_entity, WatrProcess):
                    self.watr_processes[watr_entity.id] = watr_entity
                elif isinstance(watr_entity, WatrEquipment):
                    self.watr_equipment[watr_entity.id] = watr_entity
        
        for conn in pype_connections:
            stream_id = f"watr_stream_{conn.id}"
            self.watr_streams[stream_id] = WatrStream(id=stream_id, name=conn.id)
            source_watr_id, target_watr_id = f"watr_{conn.source_node_id}", f"watr_{conn.target_node_id}"
            source_entity = self.watr_processes.get(source_watr_id) or self.watr_equipment.get(source_watr_id)
            target_entity = self.watr_processes.get(target_watr_id) or self.watr_equipment.get(target_watr_id)

            if isinstance(source_entity, WatrProcess):
                source_entity.outputs.append(stream_id)
            if isinstance(target_entity, WatrProcess):
                target_entity.inputs.append(stream_id)

        return {
            "processes": list(self.watr_processes.values()),
            "equipment": list(self.watr_equipment.values()),
            "streams": list(self.watr_streams.values()),
            "substances": list(self.watr_substances.values()),
        }

class WatrTTLExporter:
    PREFIXES = """
@prefix watr: <https://datadrivencps.org/water-ontology#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix nawi: <urn:nawi-water-ontology#> .
@prefix s223: <http://data.ashrae.org/standard223#> .
"""

    def export(self, watr_entities: Dict[str, Any]) -> str:
        ttl = self.PREFIXES + "\n"
        for proc in watr_entities["processes"]:
            ttl += f"watr:{proc.id} rdf:type watr:{proc.type} ;\n"
            ttl += f"    rdfs:label \"{proc.name}\" ;\n"
            for inp in proc.inputs: ttl += f"    watr:hasInput watr:{inp} ;\n"
            for outp in proc.outputs: ttl += f"    watr:hasOutput watr:{outp} ;\n"
            for part in proc.has_parts: ttl += f"    watr:hasPart watr:{part} ;\n"
            ttl = ttl.rstrip(" ;\n") + " .\n\n"
        for eqp in watr_entities["equipment"]:
            ttl += f"watr:{eqp.id} rdf:type watr:{eqp.type} ;\n"
            ttl += f"    rdfs:label \"{eqp.name}\" .\n\n"
        for strm in watr_entities["streams"]:
            ttl += f"watr:{strm.id} rdf:type watr:WaterStream ;\n"
            ttl += f"    rdfs:label \"{strm.name}\" .\n\n"
        return ttl

def convert_pype_to_watr(pype_nodes: List[PypeNode], pype_connections: List[PypeConnection], mapping_path: Optional[str] = None) -> Dict[str, Any]:
    converter = PypeToWatrConverter(mapping_path)
    return converter.convert(pype_nodes, pype_connections)

def export_watr_to_ttl(watr_entities: Dict[str, Any]) -> str:
    exporter = WatrTTLExporter()
    return exporter.export(watr_entities)

try:
    import rdflib
    from rdflib import Graph, Namespace, URIRef, Literal, RDF, RDFS
except ImportError:
    rdflib = None

class WatrToPypeConverter:
    def __init__(self, mapping_path: Optional[str] = None):
        self.mapping_path = mapping_path
        self.reverse_mapping = {}
        if mapping_path and os.path.exists(mapping_path):
            self._load_reverse_mapping(mapping_path)

    def _load_reverse_mapping(self, mapping_path: str):
        try:
            with open(mapping_path, 'r') as f:
                mapping_data = json.load(f)
            pypes_to_watr = mapping_data.get("PyPES2WaTr", {})
            for pype_type, watr_info in pypes_to_watr.items():
                watr_name = watr_info.get("name")
                if watr_name:
                    self.reverse_mapping[watr_name] = pype_type
                # Also try to map from URI if present
                uri = watr_info.get("uri")
                if uri:
                    # uri is usually "<uri>", strip <>
                    uri_stripped = uri.strip("<>")
                    self.reverse_mapping[uri_stripped] = pype_type
        except Exception as e:
            print(f"Error loading reverse mapping: {e}")

    def convert_ttl_to_pype(self, ttl_filepath: str) -> Dict[str, Any]:
        if rdflib is None:
            print("Error: rdflib is not installed. Cannot parse TTL.")
            return {"nodes": [], "connections": []}

        g = Graph()
        g.parse(ttl_filepath, format="turtle")

        # Define namespaces seen in benicia-model.ttl
        NAWI = Namespace("urn:nawi-water-ontology#")
        S223 = Namespace("http://data.ashrae.org/standard223#")
        WATR = Namespace("https://datadrivencps.org/water-ontology#")
        WBS = Namespace("urn:ex/")

        nodes = []
        connections = []
        node_ids = []
        conn_ids = []

        # Find all subjects that have a type
        for s, p, o in g.triples((None, RDF.type, None)):
            # Ignore prefixes themselves
            if isinstance(s, URIRef) and s == WBS[""]:
                continue
            
            # Map type to PyPES type
            watr_type = None
            if isinstance(o, URIRef):
                # Try full URI or just local name
                if str(o) in self.reverse_mapping:
                    watr_type = self.reverse_mapping[str(o)]
                elif str(o).split("#")[-1] in self.reverse_mapping:
                    watr_type = self.reverse_mapping[str(o).split("#")[-1]]
                elif str(o).split("/")[-1] in self.reverse_mapping:
                    watr_type = self.reverse_mapping[str(o).split("/")[-1]]

            if watr_type:
                node_id = str(s).split("#")[-1].split("/")[-1]
                if node_id not in node_ids:
                    node_ids.append(node_id)
                    
                    # Basic node extraction
                    node_data = {
                        "id": node_id,
                        "type": watr_type,
                        "tags": {}
                    }
                    
                    # Try to find label
                    label = g.value(s, RDFS.label)
                    if label:
                        node_data["name"] = str(label)
                        
                    nodes.append(node_data)

        # Basic connection extraction from s223 properties
        connection_predicates = [S223.connectedTo, S223.connected, S223.connectedThrough]
        for pred in connection_predicates:
            for s, p, o in g.triples((None, pred, None)):
                src_id = str(s).split("#")[-1].split("/")[-1]
                dst_id = str(o).split("#")[-1].split("/")[-1]
                
                # Check if they are valid node IDs we found
                if src_id in node_ids and dst_id in node_ids:
                    conn_id = f"conn_{src_id}_to_{dst_id}"
                    if conn_id not in conn_ids:
                        conn_ids.append(conn_id)
                        connections.append({
                            "id": conn_id,
                            "source": src_id,
                            "destination": dst_id,
                            "type": "Pipe"
                        })
                # If o is a connection object (connectedThrough), we might need more logic
                # but for now we just try to link subjects and objects directly if they are nodes.

        return {"nodes": node_ids, "connections": conn_ids, "data": {node["id"]: node for node in nodes}, "connection_data": {conn["id"]: conn for conn in connections}}
