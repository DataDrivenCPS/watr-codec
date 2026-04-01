# test_conversion.py

import unittest
from conversion_script import convert_pype_to_watr, WatrProcess, WatrEquipment, WatrStream
from sample_pype_input import sample_pype_nodes, sample_pype_connections

class TestPypeToWatrConversion(unittest.TestCase):

    def test_basic_conversion_entities_count(self):
        watr_entities = convert_pype_to_watr(sample_pype_nodes, sample_pype_connections)

        # Expected: 1 Process (Tank might be mapped as Process if its a sedimentation tank), 1 Component (Pump)
        # However, in TYPE_MAPPING, Pump maps to "Pump" (which is a Component) and Tank maps to "SedimentationTank" (which is a Component)
        # So we expect 2 Components and 0 Process based on current mapping
        # Let's adjust TYPE_MAPPING for testing: Make Tank a Process for example
        # For current mapping, expected is 2 components, 1 water stream
        self.assertEqual(len(watr_entities["processes"]), 0) # Based on current mapping
        self.assertEqual(len(watr_entities["equipment"]), 2) # pump_1 and tank_1
        self.assertEqual(len(watr_entities["streams"]), 1) # conn_pump_to_tank

    def test_entity_ids_and_names(self):
        watr_entities = convert_pype_to_watr(sample_pype_nodes, sample_pype_connections)

        # Check pump (component)
        pump_watr_component = next((c for c in watr_entities["equipment"] if c.id == "watr_pump_1"), None)
        self.assertIsNotNone(pump_watr_component)
        self.assertEqual(pump_watr_component.name, "pump_1")

        # Check tank (component)
        tank_watr_component = next((c for c in watr_entities["equipment"] if c.id == "watr_tank_1"), None)
        self.assertIsNotNone(tank_watr_component)
        self.assertEqual(tank_watr_component.name, "tank_1")

        # Check water stream
        water_stream = next((ws for ws in watr_entities["streams"] if ws.id == "watr_stream_conn_pump_to_tank"), None)
        self.assertIsNotNone(water_stream)
        self.assertEqual(water_stream.name, "conn_pump_to_tank")

    def test_properties_transfer(self):
        watr_entities = convert_pype_to_watr(sample_pype_nodes, sample_pype_connections)

        pump_watr_component = next((c for c in watr_entities["equipment"] if c.id == "watr_pump_1"), None)
        self.assertIsNotNone(pump_watr_component)

        # Check tags
        capacity_prop = next((p for p in pump_watr_component.properties if p.name == "capacity_gpm"), None)
        self.assertIsNotNone(capacity_prop)
        self.assertEqual(capacity_prop.value, 100)

        manufacturer_prop = next((p for p in pump_watr_component.properties if p.name == "manufacturer"), None)
        self.assertIsNotNone(manufacturer_prop)
        self.assertEqual(manufacturer_prop.value, "AcmePumps")

        # Check kwargs
        power_kw_prop = next((p for p in pump_watr_component.properties if p.name == "power_kw"), None)
        self.assertIsNotNone(power_kw_prop)
        self.assertEqual(power_kw_prop.value, 5)

    def test_connections_to_water_streams(self):
        watr_entities = convert_pype_to_watr(sample_pype_nodes, sample_pype_connections)

        # For this test, we need at least one Process to have inputs/outputs set.
        # Currently, both pump and tank map to Components, which don't have inputs/outputs in WatrComponent class.
        # This test will pass vacuously or fail if logic changes.
        # To properly test, let's temporarily modify TYPE_MAPPING in conversion_script for testing.
        # Or, we make the test assert that NO Process have inputs/outputs if they are not Process.

        # Let's adjust conversion_script's TYPE_MAPPING for Tank to be a Process temporarily for this test
        # to ensure water stream linkage.
        from conversion_script import PypeToWatrConverter
        original_type_mapping = PypeToWatrConverter.TYPE_MAPPING.copy()
        original_watr_process_types = PypeToWatrConverter.WATR_PROCESS_TYPES.copy()

        PypeToWatrConverter.TYPE_MAPPING["Tank"] = "SedimentationProcess" # Map to a Process
        PypeToWatrConverter.WATR_PROCESS_TYPES.append("SedimentationProcess") # Ensure it's recognized as one

        watr_entities_with_process = convert_pype_to_watr(sample_pype_nodes, sample_pype_connections)

        tank_watr_process = next((pu for pu in watr_entities_with_process["processes"] if pu.id == "watr_tank_1"), None)
        self.assertIsNotNone(tank_watr_process)
        self.assertIn("watr_stream_conn_pump_to_tank", tank_watr_process.inputs)
        
        # Reset mapping
        PypeToWatrConverter.TYPE_MAPPING = original_type_mapping
        PypeToWatrConverter.WATR_PROCESS_TYPES = original_watr_process_types
        # Re-run conversion to check the pump, which remains a component
        watr_entities_original_mapping = convert_pype_to_watr(sample_pype_nodes, sample_pype_connections)

        pump_watr_component = next((c for c in watr_entities_original_mapping["equipment"] if c.id == "watr_pump_1"), None)
        self.assertIsNotNone(pump_watr_component)
        # Components do not have inputs/outputs in the current WatrComponent class
        self.assertFalse(hasattr(pump_watr_component, 'inputs'))
        self.assertFalse(hasattr(pump_watr_component, 'outputs'))

if __name__ == '__main__':
    unittest.main()
