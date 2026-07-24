"""End-to-end tests for watr_codec.pypes_to_watr.PyPES2WaTr.

These run the full PyPES -> WaTr pipeline against the checked-in
desalination.json facility (parsed the same way a real user would, via
pype_schema's JSONParser) and check the resulting RDF graph itself, not the
converter's internal bookkeeping dictionaries. Fine-grained, method-by-method
coverage lives in test_pypes_to_watr_unit.py.
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

# Expected WaTr quantity kind + unit for every tag in desalination.json,
# hand-verified against pypes_watr_mapping.json. These are independent of
# PyPES2WaTr.convert_tag_type()/convert_units() (not derived by calling
# them), so a bug in that conversion logic will actually cause a mismatch
# here instead of the test just re-confirming its own inputs.
EXPECTED_TAG_TRANSLATIONS = {
    "P_400_002A_P.RPM_MV": ("qudtqk", "Speed", "unit", "HZ"),
    "PIT_400_003A_P.PV": ("qudtqk", "Pressure", "unit", "PSI"),
    "P_400_001A_P.RPM_MV": ("qudtqk", "Speed", "unit", "HZ"),
    "PDIT_400_002A_P.PV": ("qudtqk", "Pressure", "unit", "PSI"),
    "FIT_400_001A_P.PV": ("qudtqk", "VolumeFlowRate", "unit", "GAL_US-PER-MIN"),
    "AIT_400_001A_P.PV": ("qudtqk", "ElectricConductivity", "unit", "MicroS-PER-CentiM"),
    "FIT_400_002A_P.PV": ("qudtqk", "VolumeFlowRate", "unit", "GAL_US-PER-MIN"),
}

# NotImplementedWarning is expected for every one of these PyPES attributes
# present on the desalination.json facility (pump_type/pump_curve on the
# Pump nodes, area/selectivity/settling_time on the ROMembrane, and
# heating_values/bidirectional on every Pipe).
EXPECTED_NOT_IMPLEMENTED_ATTRIBUTES = {
    "pump_type",
    "pump_curve",
    "area",
    "selectivity",
    "settling_time",
    "heating_values",
    "bidirectional",
}


@pytest.fixture
def desal_network():
    """Parse the checked-in desalination.json fixture into a PyPES network.

    Returns
    -------
    pype_schema.node.Network
        The desalination facility, as built by pype_schema's `JSONParser`.
    """
    return JSONParser(DESAL_JSON_PATH).initialize_network()


@pytest.fixture
def converter(desal_network):
    """Build a PyPES2WaTr converter for the desalination fixture.

    Parameters
    ----------
    desal_network : pype_schema.node.Network
        The parsed desalination facility (see `desal_network` fixture).

    Returns
    -------
    watr_codec.pypes_to_watr.PyPES2WaTr
        A converter ready to translate `desal_network`, using the local
        prefix `"dsl"`.
    """
    return PyPES2WaTr(desal_network, local_prefix="dsl")


def test_desalination_facility_translates_into_a_consistent_graph(converter, desal_network):
    """The full pipeline should run to completion and the resulting graph
    should contain every node/connection from the source facility, with no
    dangling property references, and translating twice should be a no-op.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        graph = converter.to_graph()

    assert len(graph) > 0

    local = converter.model.namespaces[converter.local_prefix]
    s223 = converter.model.namespaces["s223"]

    # Expected IDs are derived straight from the parsed fixture rather than
    # hardcoded here, so this test keeps working if desalination.json's
    # topology changes without anyone needing to remember to update it.
    expected_node_ids = {converter._sanitize_id(node_id) for node_id in desal_network.nodes}
    expected_conn_ids = {converter._sanitize_id(conn_id) for conn_id in desal_network.connections}

    # Every node and connection in the source facility should be a typed
    # subject in the graph itself (not just a key in the converter's
    # internal node_dict/conn_dict bookkeeping).
    for node_id in expected_node_ids:
        assert any(graph.triples((local[node_id], RDF.type, None))), f"{node_id} missing from graph"
    for conn_id in expected_conn_ids:
        assert any(graph.triples((local[conn_id], RDF.type, None))), f"{conn_id} missing from graph"

    # Every connection creates exactly one outlet and one inlet connection
    # point, i.e. exactly two connection points "connectThrough" it - even
    # though some nodes (e.g. ERI, which sources/receives several pipes)
    # cause generate_conn_point_name() to rename later points from
    # "ERI-cp-1" to "ERI-cp-2", "ERI-cp-3", etc. to keep every name unique.
    # That renaming changes point *names*, not the total point *count*.
    connects_through = s223["connectsThrough"]
    conn_points = {subject for subject, _, _ in graph.triples((None, connects_through, None))}
    assert len(conn_points) == 2 * len(expected_conn_ids)

    # Every subject that has properties attached must itself be a real,
    # translated entity in the graph - i.e. no property's parent_id points
    # at something that was never actually translated.
    has_property = s223["hasProperty"]
    parents_with_properties = {subject for subject, _, _ in graph.triples((None, has_property, None))}
    typed_subjects = {subject for subject, _, _ in graph.triples((None, RDF.type, None))}
    assert parents_with_properties <= typed_subjects

    # to_graph() should be idempotent: calling it again must not re-run the
    # translation or grow the graph.
    graph_again = converter.to_graph()
    assert graph_again is graph
    assert len(graph_again) == len(graph)


def test_desalination_ttl_export_matches_expected_entities(converter, desal_network, tmp_path):
    """Exporting to TTL should round-trip losslessly through rdflib, raise
    the expected "not yet implemented" warnings, and produce specific
    triples for every node type and every tag - not just a single example.
    """
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        outpath = tmp_path / "desal.ttl"
        converter.export_ttl(str(outpath))

    warning_text = " ".join(
        str(w.message) for w in caught if issubclass(w.category, NotImplementedWarning)
    )
    for attribute in EXPECTED_NOT_IMPLEMENTED_ATTRIBUTES:
        assert attribute in warning_text, f"expected a NotImplementedWarning mentioning {attribute!r}"

    assert outpath.exists()
    reparsed = Graph().parse(str(outpath), format="turtle")
    assert len(reparsed) == len(converter.model.graph)

    ns = converter.model.namespaces
    local, s223, watr, qudt = ns["dsl"], ns["s223"], ns["watr"], ns["qudt"]

    # Node types, including a node whose mapping entry declares a `process`.
    assert (local["HPPump"], RDF.type, watr["Pump"]) in reparsed
    assert (local["SWRO"], RDF.type, watr["ReverseOsmosisMembrane"]) in reparsed
    assert (local["SWRO"], watr["hasProcess"], watr["Process-ReverseOsmosis"]) in reparsed
    assert (local["Output"], RDF.type, watr["Tank"]) in reparsed

    # Every pipe in the facility should show up as an s223:Pipe.
    pipe_count = sum(1 for _ in reparsed.triples((None, RDF.type, s223["Pipe"])))
    assert pipe_count == len(desal_network.connections)

    # Every tag in the facility - not just one - should carry its expected
    # quantity kind and unit.
    for tag_id, (qk_uri, qk_name, unit_uri, unit_name) in EXPECTED_TAG_TRANSLATIONS.items():
        term = local[tag_id]
        assert (term, qudt["hasQuantityKind"], ns[qk_uri][qk_name]) in reparsed, tag_id
        assert (term, s223["hasUnit"], ns[unit_uri][unit_name]) in reparsed, tag_id
