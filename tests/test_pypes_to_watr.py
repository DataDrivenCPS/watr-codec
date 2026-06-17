# at the moment this is a test script, not a formal pytest file
from watr_codec.pypes_to_watr import PyPES2WaTr
from pype_schema.parse_json import JSONParser
import os

# add this file path to dir so that data folder is always accessible
current_dir = os.path.dirname(os.path.abspath(__file__))

# load PyPES network from JSON file
pypes_desal_system = JSONParser(current_dir + "/../watr_codec/data/desalination.json").initialize_network()
pypes2watr = PyPES2WaTr(pypes_desal_system, local_prefix="dsl")
pypes2watr.export_ttl(os.path.join(current_dir, "desal_test.ttl"))