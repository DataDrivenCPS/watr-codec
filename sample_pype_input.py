# sample_pype_input.py

from conversion_script import PypeNode, PypeConnection, PypeTag

# Define a sample Pype-schema input
# A simple system: a pump connected to a tank

sample_pype_nodes_data = [
    {
        "id": "pump_1",
        "type": "Pump",
        "input_contents": ["raw_water"],
        "output_contents": ["treated_water"],
        "tags": {
            "capacity_gpm": PypeTag(key="capacity_gpm", value=100),
            "manufacturer": PypeTag(key="manufacturer", value="AcmePumps")
        },
        "power_kw": 5
    },
    {
        "id": "tank_1",
        "type": "Tank",
        "input_contents": ["treated_water"],
        "output_contents": ["filtered_water"],
        "tags": {
            "volume_m3": PypeTag(key="volume_m3", value=500),
            "material": PypeTag(key="material", value="StainlessSteel")
        },
        "height_m": 10
    }
]

sample_pype_connections_data = [
    {
        "id": "conn_pump_to_tank",
        "source_node_id": "pump_1",
        "target_node_id": "tank_1",
        "flow_rate_lps": 6.3
    }
]

# Convert raw data to PypeNode and PypeConnection objects
sample_pype_nodes = [
    PypeNode(
        id=node_data["id"],
        type=node_data["type"],
        input_contents=node_data.get("input_contents"),
        output_contents=node_data.get("output_contents"),
        tags=node_data.get("tags"),
        **{k: v for k, v in node_data.items() if k not in ["id", "type", "input_contents", "output_contents", "tags"]}
    )
    for node_data in sample_pype_nodes_data
]

sample_pype_connections = [
    PypeConnection(
        id=conn_data["id"],
        source_node_id=conn_data["source_node_id"],
        target_node_id=conn_data["target_node_id"],
        **{k: v for k, v in conn_data.items() if k not in ["id", "source_node_id", "target_node_id"]}
    )
    for conn_data in sample_pype_connections_data
]
