# sample_pype_input.py

from conversion_script import PypeNode, PypeConnection, PypeTag

# Define a more realistic sample input from pype-schema (desal_sample.json)
# Nodes for a seawater reverse osmosis (SWRO) process and sludge treatment

sample_pype_nodes_data = [
    {
        "id": "chlorination_1",
        "type": "ChlorinationBasin",
        "input_contents": ["seawater"],
        "output_contents": ["chlorinated_seawater"],
        "tags": {
            "dosing_rate_mg_l": PypeTag(key="dosing_rate_mg_l", value=2.5)
        }
    },
    {
        "id": "mixer_1",
        "type": "StaticMixer",
        "input_contents": ["chlorinated_seawater", "coagulant"],
        "output_contents": ["mixed_seawater"],
        "tags": {
            "mixing_speed_rpm": PypeTag(key="mixing_speed_rpm", value=150)
        }
    },
    {
        "id": "media_filter_1",
        "type": "MediaFilter",
        "input_contents": ["mixed_seawater"],
        "output_contents": ["filtered_seawater"],
        "tags": {
            "filter_medium": PypeTag(key="filter_medium", value="Sand/Anthracite")
        }
    },
    {
        "id": "ro_module_1",
        "type": "ROModule",
        "input_contents": ["filtered_seawater"],
        "output_contents": ["permeate", "brine"],
        "tags": {
            "recovery_ratio": PypeTag(key="recovery_ratio", value=0.45)
        }
    },
    {
        "id": "ad_1",
        "type": "AnaerobicDigestion",
        "input_contents": ["sludge"],
        "output_contents": ["biogas", "digested_sludge"],
        "tags": {
            "retention_time_days": PypeTag(key="retention_time_days", value=20)
        }
    },
    {
        "id": "pump_1",
        "type": "Pump",
        "input_contents": ["seawater"],
        "output_contents": ["seawater"],
        "tags": {
            "capacity_m3_h": PypeTag(key="capacity_m3_h", value=100)
        }
    }
]

sample_pype_connections_data = [
    {
        "id": "conn_pump_to_chlor",
        "source_node_id": "pump_1",
        "target_node_id": "chlorination_1",
        "flow_rate_lps": 10.0
    },
    {
        "id": "conn_chlor_to_mixer",
        "source_node_id": "chlorination_1",
        "target_node_id": "mixer_1",
        "flow_rate_lps": 10.0
    },
    {
        "id": "conn_mixer_to_media",
        "source_node_id": "mixer_1",
        "target_node_id": "media_filter_1",
        "flow_rate_lps": 10.0
    },
    {
        "id": "conn_media_to_ro",
        "source_node_id": "media_filter_1",
        "target_node_id": "ro_module_1",
        "flow_rate_lps": 9.5
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
