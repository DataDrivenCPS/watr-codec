# test_conversion.py

import unittest
from conversion_script import convert_pype_to_watr, export_watr_to_ttl, WatrProcess, WatrEquipment, WatrStream
from sample_pype_input import sample_pype_nodes, sample_pype_connections

class TestPypeToWatrConversion(unittest.TestCase):

    def test_basic_conversion_entities_count(self):
        watr_entities = convert_pype_to_watr(sample_pype_nodes, sample_pype_connections)

        # chlorination_1 -> Process-Chlorination
        # mixer_1 -> Process-Mixing
        # media_filter_1 -> Process-MediaFiltration
        # ro_module_1 -> Process-ReverseOsmosis
        # ad_1 -> Process-AnaerobicDigestion
        # pump_1 -> Pump (Equipment)
        # Total processes: 5, Total equipment: 1, Total streams: 4
        
        self.assertEqual(len(watr_entities["processes"]), 5)
        self.assertEqual(len(watr_entities["equipment"]), 1)
        self.assertEqual(len(watr_entities["streams"]), 4)

    def test_process_types(self):
        watr_entities = convert_pype_to_watr(sample_pype_nodes, sample_pype_connections)

        ad_process = next((p for p in watr_entities["processes"] if p.id == "watr_ad_1"), None)
        self.assertIsNotNone(ad_process)
        self.assertEqual(ad_process.type, "Process-AnaerobicDigestion")

        ro_process = next((p for p in watr_entities["processes"] if p.id == "watr_ro_module_1"), None)
        self.assertIsNotNone(ro_process)
        self.assertEqual(ro_process.type, "Process-ReverseOsmosis")

    def test_equipment_types(self):
        watr_entities = convert_pype_to_watr(sample_pype_nodes, sample_pype_connections)

        pump_equipment = next((e for e in watr_entities["equipment"] if e.id == "watr_pump_1"), None)
        self.assertIsNotNone(pump_equipment)
        self.assertEqual(pump_equipment.type, "Pump")

    def test_properties_transfer(self):
        watr_entities = convert_pype_to_watr(sample_pype_nodes, sample_pype_connections)

        ad_process = next((p for p in watr_entities["processes"] if p.id == "watr_ad_1"), None)
        retention_prop = next((p for p in ad_process.properties if p.name == "retention_time_days"), None)
        self.assertEqual(retention_prop.value, 20)

    def test_connections_linkage(self):
        watr_entities = convert_pype_to_watr(sample_pype_nodes, sample_pype_connections)

        chlor_process = next((p for p in watr_entities["processes"] if p.id == "watr_chlorination_1"), None)
        mixer_process = next((p for p in watr_entities["processes"] if p.id == "watr_mixer_1"), None)
        
        stream_id = "watr_stream_conn_chlor_to_mixer"
        self.assertIn(stream_id, chlor_process.outputs)
        self.assertIn(stream_id, mixer_process.inputs)

    def test_ttl_export(self):
        watr_entities = convert_pype_to_watr(sample_pype_nodes, sample_pype_connections)
        ttl_output = export_watr_to_ttl(watr_entities)

        self.assertIn("@prefix watr:", ttl_output)
        self.assertIn("watr:watr_ad_1 rdf:type watr:Process-AnaerobicDigestion", ttl_output)
        self.assertIn("watr:watr_pump_1 rdf:type watr:Pump", ttl_output)
        self.assertIn("watr:watr_stream_conn_chlor_to_mixer rdf:type watr:WaterStream", ttl_output)

if __name__ == '__main__':
    unittest.main()
