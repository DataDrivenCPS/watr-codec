"""End-to-end tests for watr_codec.pypes_to_watr.PyPES2WaTr.

These run the full PyPES -> WaTr pipeline against the checked-in
desalination.json facility (parsed the same way a real user would, via
pype_schema's JSONParser) and check the resulting semantic graph as a whole.
Fine-grained, method-by-method coverage lives in test_pypes_to_watr_unit.py.
"""

import os
import warnings

import pytest
from pype_schema.parse_json import JSONParser
from rdflib import Graph
from rdflib.namespace import RDF

from watr_codec.pypes_to_watr import NotImplementedWarning, PyPES2WaTr

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
DESAL_JSON_PATH = os.path.join(CURRENT_DIR, "..", "watr_codec", "data", "desalination.json")

# Node/connection topology of desalination.json, kept here so the tests can
# assert against it without re-reading the fixture file by hand.
DESAL_NODE_IDS = {"Input", "HPPump", "SWRO", "ERI", "CirculationPump", "WasteWaterSump", "Output"}
DESAL_CONNECTION_IDS = {
    "InputToHPPump",
    "InputToERI",
    "HPPumpToSWRO",
    "ERIToCirculationPump",
    "ERIToWasewaterSump",
    "SWROToERI",
    "CirculationPumpToSWRO",
    "SWROToOutput",
}


@pytest.fixture
def desal_network():
    return JSONParser(DESAL_JSON_PATH).initialize_network()


@pytest.fixture
def converter(desal_network):
    return PyPES2WaTr(desal_network, local_prefix="dsl")


def test_desalination_facility_translates_into_a_consistent_graph(converter, desal_network):
    """The full pipeline should run to completion and produce a graph whose
    bookkeeping dictionaries line up with the source PyPES facility."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        graph = converter.to_graph()

    assert len(graph) > 0

    # Every node and connection in the source facility should have been
    # translated exactly once.
    assert set(converter.node_dict) == DESAL_NODE_IDS
    assert set(converter.conn_dict) == DESAL_CONNECTION_IDS

    # Each connection contributes exactly two connection points, regardless
    # of any name collisions resolved by generate_conn_point_name.
    assert len(converter.conn_point_dict) == 2 * len(DESAL_CONNECTION_IDS)

    # Every translated property must point back to a node or connection that
    # was actually translated (no dangling parent references).
    known_parents = set(converter.node_dict) | set(converter.conn_dict)
    for prop_id, prop_attrs in converter.property_dict.items():
        assert prop_attrs["parent_id"] in known_parents, (
            f"property {prop_id!r} points at untranslated parent "
            f"{prop_attrs['parent_id']!r}"
        )

    # to_graph() should be idempotent - calling it again must not re-run the
    # translation or grow the graph.
    graph_again = converter.to_graph()
    assert graph_again is graph
    assert len(graph_again) == len(graph)


def test_desalination_ttl_export_matches_expected_entities(converter, tmp_path):
    """Spot-check specific triples end users would depend on, and confirm the
    exported TTL file round-trips losslessly through rdflib."""
    expected_warning_fragments = {
        "pump_type",
        "pump_curve",
        "area",
        "selectivity",
        "settling_time",
        "heating_values",
        "bidirectional",
    }

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        outpath = tmp_path / "desal.ttl"
        converter.export_ttl(str(outpath))

    not_implemented_messages = [
        str(w.message) for w in caught if issubclass(w.category, NotImplementedWarning)
    ]
    seen_fragments = {
        fragment
        for fragment in expected_warning_fragments
        if any(fragment in msg for msg in not_implemented_messages)
    }
    assert seen_fragments == expected_warning_fragments

    assert outpath.exists()
    reparsed = Graph().parse(str(outpath), format="turtle")
    assert len(reparsed) == len(converter.model.graph)

    local = converter.model.namespaces["dsl"]
    s223 = converter.model.namespaces["s223"]
    watr = converter.model.namespaces["watr"]
    qudt = converter.model.namespaces["qudt"]
    qudtqk = converter.model.namespaces["qudtqk"]

    # Node types, including a node whose mapping entry declares a `process`.
    assert (local["HPPump"], RDF.type, watr["Pump"]) in reparsed
    assert (local["SWRO"], RDF.type, watr["ReverseOsmosisMembrane"]) in reparsed
    assert (local["SWRO"], watr["hasProcess"], watr["Process-ReverseOsmosis"]) in reparsed
    assert (local["Output"], RDF.type, watr["Tank"]) in reparsed

    # Every pipe in the facility should show up as an s223:Pipe.
    pipe_count = sum(1 for _ in reparsed.triples((None, RDF.type, s223["Pipe"])))
    assert pipe_count == len(DESAL_CONNECTION_IDS)

    # A representative tag should carry its quantity kind and unit.
    conductivity_tag = local["AIT_400_001A_P.PV"]
    assert (conductivity_tag, qudt["hasQuantityKind"], qudtqk["ElectricConductivity"]) in reparsed
    assert (conductivity_tag, s223["hasUnit"], converter.model.namespaces["unit"]["MicroS-PER-CentiM"]) in reparsed
