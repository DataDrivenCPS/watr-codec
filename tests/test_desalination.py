import json
import sys
import os

# Add the project root to sys.path to import water_codec
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from water_codec.conversion_script import PypeNode, PypeConnection, PypeTag, convert_pype_to_watr, export_watr_to_ttl

def load_desalination_data(filepath):
    with open(filepath, 'r') as f:
        data = json.load(f)
    
    pype_nodes = []
    for node_id in data['nodes']:
        node_info = data[node_id]
        tags = {}
        for tag_id, tag_data in node_info.get('tags', {}).items():
            tags[tag_id] = PypeTag(key=tag_id, value=tag_data)
        
        # Mapping desalination.json structure to PypeNode
        pype_nodes.append(PypeNode(
            id=node_id,
            type=node_info['type'],
            input_contents=[node_info.get('contents')] if node_info.get('contents') else [],
            output_contents=[node_info.get('contents')] if node_info.get('contents') else [],
            tags=tags,
            **{k: v for k, v in node_info.items() if k not in ['type', 'tags', 'contents']}
        ))
    
    pype_connections = []
    for conn_id in data['connections']:
        conn_info = data[conn_id]
        pype_connections.append(PypeConnection(
            id=conn_id,
            source_node_id=conn_info['source'],
            target_node_id=conn_info['destination'],
            type=conn_info.get('type', 'Pipe'),
            **{k: v for k, v in conn_info.items() if k not in ['type', 'source', 'destination']}
        ))
        
    return pype_nodes, pype_connections

if __name__ == "__main__":
    data_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../data'))
    data_path = os.path.join(data_dir, 'desalination.json')
    mapping_path = os.path.join(data_dir, 'pypes_watr_mapping.json')
    
    pype_nodes, pype_connections = load_desalination_data(data_path)
    watr_entities = convert_pype_to_watr(pype_nodes, pype_connections, mapping_path=mapping_path)
    ttl_output = export_watr_to_ttl(watr_entities)
    
    print("--- WaTr TTL Output ---")
    print(ttl_output)
    
    print("--- Summary ---")
    print(f"Nodes: {len(pype_nodes)}")
    print(f"Connections: {len(pype_connections)}")
    print(f"WaTr Processes: {len(watr_entities['processes'])}")
    print(f"WaTr Equipment: {len(watr_entities['equipment'])}")
    print(f"WaTr Streams: {len(watr_entities['streams'])}")
