# conversion_script.py

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
    def __init__(self, id: str, name: Optional[str] = None):
        super().__init__(id, name)

class WatrProcess(WatrEntity):
    def __init__(self, id: str, name: Optional[str] = None, type: Optional[str] = None):
        super().__init__(id, name)
        self.type = type # e.g., AerationProcess, FiltrationProcess
        self.has_parts: List[WatrEquipment] = []
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
    # This will be expanded as we get more detailed
    TYPE_MAPPING = {
        "Aeration": "AerationProcess",
        "Pump": "Pump", # WaTr has Pump as Component
        "Tank": "SedimentationTank", # Example mapping, might need more specific logic
        # Add more Pype-schema types to WaTr types here
        # For simplicity, if a PypeNode type maps to a WaTr Process, its value here
        # should be a string representing the WaTr Process type.
        # If it maps to a WatrEquipment, its value should be the WatrEquipment type.
    }

    # Define which WaTr types are Process and which are Equipment for clarity
    WATR_PROCESS_TYPES = [
        "AerationProcess", "ChlorinationProcess", "CoagulationProcess", "DisinfectionProcess",
        "FiltrationProcess", "FlocculationProcess", "IonExchangeProcess", "MembraneFiltrationProcess",
        "OzonationProcess", "ReverseOsmosisProcess", "SedimentationProcess", "SludgeTreatmentProcess",
        "SofteningProcess", "UltravioletDisinfectionProcess"
    ]
    WATR_EQUIPMENT_TYPES = [
        "Aerator", "ChlorineDosingSystem", "CoagulantDosingSystem", "Filter", "Flocculator",
        "IonExchangeUnit", "MembraneModule", "Ozonator", "Pump", "SedimentationTank",
        "SludgeDewateringUnit", "Softener", "UVReactor"
    ]


    def __init__(self):
        self.watr_processes: Dict[str, WatrProcess] = {}
        self.watr_equipment: Dict[str, WatrEquipment] = {}
        self.watr_streams: Dict[str, WatrStream] = {}
        self.watr_substances: Dict[str, WatrSubstance] = {} # For any explicit substance mapping

    def _convert_pype_tag_to_watr_property(self, pype_tag: PypeTag, entity_id: str) -> WatrProperty:
        # Simple conversion for now, can be expanded for WaterQualityParameter
        prop_id = f"{entity_id}_prop_{pype_tag.key}"
        return WatrProperty(id=prop_id, name=pype_tag.key, value=pype_tag.value)

    def _convert_pype_node_to_watr_entity(self, pype_node: PypeNode) -> Optional[Union[WatrProcess, WatrEquipment]]:
        watr_id = f"watr_{pype_node.id}"
        watr_name = pype_node.id # Using PypeNode id as name for now

        watr_type_str = self.TYPE_MAPPING.get(pype_node.type, pype_node.type)

        watr_entity = None
        if watr_type_str in self.WATR_PROCESS_TYPES:
            watr_entity = WatrProcess(id=watr_id, name=watr_name, type=watr_type_str)
        elif watr_type_str in self.WATR_EQUIPMENT_TYPES:
            watr_entity = WatrEquipment(id=watr_id, name=watr_name)
        else:
            print(f"Warning: PypeNode type '{pype_node.type}' (mapped to '{watr_type_str}') does not have a direct WaTr Process or Equipment mapping. Defaulting to generic WatrComponent.")
            watr_entity = WatrEquipment(id=watr_id, name=watr_name)

        if watr_entity:
            # Convert PypeTags to WatrProperties
            for key, pype_tag in pype_node.tags.items():
                watr_entity.properties.append(self._convert_pype_tag_to_watr_property(pype_tag, watr_id))
            
            # Convert additional properties captured in kwargs
            for key, value in pype_node.properties.items():
                prop_id = f"{watr_id}_prop_{key}"
                watr_entity.properties.append(WatrProperty(id=prop_id, name=key, value=value))

        return watr_entity

    def convert(self, pype_nodes: List[PypeNode], pype_connections: List[PypeConnection]) -> Dict[str, Any]:
        # First pass: Convert all PypeNodes to WatrProcess or WatrEquipment
        for node in pype_nodes:
            watr_entity = self._convert_pype_node_to_watr_entity(node)
            if watr_entity:
                if isinstance(watr_entity, WatrProcess):
                    self.watr_processes[watr_entity.id] = watr_entity
                elif isinstance(watr_entity, WatrEquipment):
                    self.watr_equipment[watr_entity.id] = watr_entity
        
        # Second pass: Handle connections and link components to process units
        for conn in pype_connections:
            # Create a WaterStream for each connection
            stream_id = f"watr_stream_{conn.id}"
            watr_stream = WatrStream(id=stream_id, name=conn.id)
            self.watr_streams[stream_id] = watr_stream

            source_pype_node_id = conn.source_node_id
            target_pype_node_id = conn.target_node_id

            # Find the corresponding WaTr entities
            source_watr_id = f"watr_{source_pype_node_id}"
            target_watr_id = f"watr_{target_pype_node_id}"

            source_watr_entity: Optional[Union[WatrProcess, WatrEquipment]] = \
                self.watr_processes.get(source_watr_id) or self.watr_equipment.get(source_watr_id)
            target_watr_entity: Optional[Union[WatrProcess, WatrEquipment]] = \
                self.watr_processes.get(target_watr_id) or self.watr_equipment.get(target_watr_id)

            if source_watr_entity and isinstance(source_watr_entity, WatrProcess):
                source_watr_entity.outputs.append(stream_id)
            elif source_watr_entity and isinstance(source_watr_entity, WatrEquipment):
                # If a component is a source, we might need a dummy process unit or direct link if WaTr model allows
                # For now, let's assume components act as part of a process unit that handles the input/output
                pass # This requires more sophisticated mapping
            
            if target_watr_entity and isinstance(target_watr_entity, WatrProcess):
                target_watr_entity.inputs.append(stream_id)
            elif target_watr_entity and isinstance(target_watr_entity, WatrEquipment):
                pass # Requires more sophisticated mapping

        # Collect all generated WaTr entities
        all_watr_entities = {
            "processes": list(self.watr_processes.values()),
            "equipment": list(self.watr_equipment.values()),
            "streams": list(self.watr_streams.values()),
            "substances": list(self.watr_substances.values()),
        }
        return all_watr_entities

def convert_pype_to_watr(pype_nodes: List[PypeNode], pype_connections: List[PypeConnection]) -> Dict[str, Any]:
    converter = PypeToWatrConverter()
    return converter.convert(pype_nodes, pype_connections)