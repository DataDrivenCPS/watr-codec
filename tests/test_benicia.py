import sys
import os
import json

# Add the project root to sys.path to import water_codec
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from water_codec.conversion_script import WatrToPypeConverter

if __name__ == "__main__":
    data_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../data'))
    ttl_path = os.path.join(data_dir, 'benicia-model.ttl')
    mapping_path = os.path.join(data_dir, 'pypes_watr_mapping.json')
    
    converter = WatrToPypeConverter(mapping_path)
    pype_data = converter.convert_ttl_to_pype(ttl_path)
    
    print("--- PyPES Data from WaTr TTL ---")
    print(f"Nodes found: {len(pype_data['nodes'])}")
    print(f"Connections found: {len(pype_data['connections'])}")
    
    # Print some nodes
    print("\nSample Nodes:")
    for node_id in pype_data['nodes'][:5]:
        print(f"  {node_id}: {pype_data['data'][node_id]['type']}")
        
    # Print some connections
    print("\nSample Connections:")
    for conn_id in pype_data['connections'][:5]:
        conn = pype_data['connection_data'][conn_id]
        print(f"  {conn_id}: {conn['source']} -> {conn['destination']}")

    # Save to JSON for verification
    output_path = 'tests/benicia_pype.json'
    # Combine data for saving
    save_data = {
        "nodes": pype_data["nodes"],
        "connections": pype_data["connections"]
    }
    for node_id, node_info in pype_data["data"].items():
        save_data[node_id] = node_info
    for conn_id, conn_info in pype_data["connection_data"].items():
        save_data[conn_id] = conn_info
        
    with open(output_path, 'w') as f:
        json.dump(save_data, f, indent=2)
    print(f"\nSaved PyPES mapping to {output_path}")
