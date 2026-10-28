"""End-to-end tests for watr_codec.pypes_to_watr.PyPES2WaTr.

These run the full PyPES -> WaTr pipeline against the checked-in
desalination.json facility (parsed the same way a real user would, via
pype_schema's JSONParser) and check the resulting RDF graph itself, not the
converter's internal bookkeeping dictionaries. Fine-grained, method-by-method
coverage lives in test_pypes_to_watr_unit.py.
"""

import os
import shutil
import warnings

import pytest
from pype_schema.parse_json import JSONParser
from rdflib import Graph, Namespace
from rdflib.compare import graph_diff, to_isomorphic
from rdflib.namespace import RDF

from watr_codec.pypes_to_watr import NotImplementedWarning, PyPES2WaTr

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
DESAL_JSON_PATH = os.path.join(CURRENT_DIR, "..", "watr_codec", "data", "desalination.json")
# The reviewed translation of desalination.json. After an intended change to
# the output, regenerate it with `UPDATE_EXPECTED_TTL=1 pytest`, then review
# its diff before committing.
DESAL_EXPECTED_TTL_PATH = os.path.join(CURRENT_DIR, "desal_expected.ttl")

LOCAL = Namespace("urn:ex/")
S223 = Namespace("http://data.ashrae.org/standard223#")
WATR = Namespace("https://watermetadata.org/ontology/watr#")
QUDT = Namespace("http://qudt.org/schema/qudt/")
QK = Namespace("http://qudt.org/vocab/quantitykind/")
UNIT = Namespace("http://qudt.org/vocab/unit/")

# The expectations below are hand-verified against pypes_watr_mapping.json and
# must cover every node, pipe, and tag in desalination.json (see
# test_expectations_cover_the_whole_fixture). They are independent of
# PyPES2WaTr's lookups (not derived by calling them), so a bug in that logic
# will actually cause a mismatch here instead of the test just re-confirming
# its own inputs.

# Expected WaTr class and processes of every node.
EXPECTED_NODE_TYPES = {
    "Input": WATR["Tank"],
    "HPPump": WATR["Pump"],
    "SWRO": WATR["ReverseOsmosisMembrane"],
    "ERI": WATR["Pump"],
    "CirculationPump": WATR["Pump"],
    "WasteWaterSump": WATR["Tank"],
    "Output": WATR["Tank"],
}
EXPECTED_PROCESSES = {"SWRO": {WATR["Process-ReverseOsmosis"]}}

# Expected medium and role (if any) of every pipe: Brine is WaTr's brine, and
# ProductWater is 223P water in WaTr's permeate role.
EXPECTED_PIPE_MEDIA = {
    "InputToHPPump": (WATR["Water-Brine"], None),
    "InputToERI": (WATR["Water-Brine"], None),
    "HPPumpToSWRO": (WATR["Water-Brine"], None),
    "ERIToCirculationPump": (WATR["Water-Brine"], None),
    "ERIToWasewaterSump": (WATR["Water-Brine"], None),
    "SWROToERI": (WATR["Water-Brine"], None),
    "CirculationPumpToSWRO": (WATR["Water-Brine"], None),
    "SWROToOutput": (S223["Fluid-Water"], WATR["Role-Permeate"]),
}

# Expected WaTr quantity kind + unit for every tag.
# NOTE: the two pump-speed tags are typed Speed with Hz units in
# desalination.json; Hz has the dimensions of a rotational speed, so they
# translate as RotationalVelocity
EXPECTED_TAG_TRANSLATIONS = {
    "P_400_002A_P.RPM_MV": ("RotationalVelocity", "HZ"),
    "PIT_400_003A_P.PV": ("Pressure", "PSI"),
    "P_400_001A_P.RPM_MV": ("RotationalVelocity", "HZ"),
    "PDIT_400_002A_P.PV": ("Pressure", "PSI"),
    "FIT_400_001A_P.PV": ("VolumeFlowRate", "GAL_US-PER-MIN"),
    "AIT_400_001A_P.PV": ("ElectricConductivity", "MicroS-PER-CentiM"),
    "FIT_400_002A_P.PV": ("VolumeFlowRate", "GAL_US-PER-MIN"),
}

# NotImplementedWarning is expected for every one of these PyPES attributes
# that has data on the desalination.json facility (pump_type/pump_curve on
# the Pump nodes, settling_time on the ROMembrane, and bidirectional on every
# Pipe)...
EXPECTED_NOT_IMPLEMENTED_ATTRIBUTES = {
    "pump_type",
    "pump_curve",
    "settling_time",
    "bidirectional",
}
# ...but not for those without data (area/selectivity on the ROMembrane are
# None, and heating_values on every Pipe is (None, None)).
NOT_IMPLEMENTED_ATTRIBUTES_WITHOUT_DATA = {
    "area",
    "selectivity",
    "heating_values",
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


def test_expectations_cover_the_whole_fixture(desal_network):
    """The hand-verified expectations must list every node, pipe, and tag in
    desalination.json, so editing the fixture without updating them fails."""
    assert set(EXPECTED_NODE_TYPES) == set(desal_network.nodes)
    assert set(EXPECTED_PIPE_MEDIA) == set(desal_network.connections)
    assert set(EXPECTED_TAG_TRANSLATIONS) == {
        tag.id for tag in desal_network.get_all_tags(virtual=False, recurse=True)
    }


def test_desalination_facility_translates_into_a_consistent_graph(converter, desal_network):
    """The full pipeline should run to completion and the resulting graph
    should contain every node/connection from the source facility, with no
    dangling property references, and translating twice should be a no-op.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        graph = converter.to_graph()

    assert len(graph) > 0

    # Expected IDs are derived straight from the parsed fixture rather than
    # hardcoded here, so this test keeps working if desalination.json's
    # topology changes without anyone needing to remember to update it.
    expected_node_ids = {converter._sanitize_id(node_id) for node_id in desal_network.nodes}
    expected_conn_ids = {converter._sanitize_id(conn_id) for conn_id in desal_network.connections}

    # Every node and connection in the source facility should be a typed
    # subject in the graph itself.
    for node_id in expected_node_ids:
        assert any(graph.triples((LOCAL[node_id], RDF.type, None))), f"{node_id} missing from graph"
    for conn_id in expected_conn_ids:
        assert any(graph.triples((LOCAL[conn_id], RDF.type, None))), f"{conn_id} missing from graph"

    # Every connection joins exactly one outlet and one inlet connection
    # point, named after the connection, even for nodes such as ERI that
    # source or receive several pipes.
    for conn_id in expected_conn_ids:
        points = set(graph.subjects(S223["connectsThrough"], LOCAL[conn_id]))
        assert points == {LOCAL[conn_id + "-out"], LOCAL[conn_id + "-in"]}, conn_id

    # Every subject that has properties attached must itself be a real,
    # translated entity in the graph - i.e. no property points at something
    # that was never actually translated.
    parents_with_properties = set(graph.subjects(S223["hasProperty"], None))
    typed_subjects = set(graph.subjects(RDF.type, None))
    assert parents_with_properties <= typed_subjects

    # to_graph() should be idempotent: calling it again must not re-run the
    # translation or grow the graph.
    graph_again = converter.to_graph()
    assert graph_again is graph
    assert len(graph_again) == len(graph)


def test_desalination_facility_conforms_to_watr_and_223p(converter):
    """The translated facility should pass SHACL validation against the
    WaTr, 223P, and QUDT shapes."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        report = converter.validate()
    assert report, str(report)


def test_desalination_ttl_export_matches_expected_entities(converter, desal_network, tmp_path):
    """Exporting to TTL should round-trip losslessly through rdflib, raise
    the expected "not yet implemented" warnings, and produce the expected
    triples for every node, every pipe, and every tag - not just examples.
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
    for attribute in NOT_IMPLEMENTED_ATTRIBUTES_WITHOUT_DATA:
        assert attribute not in warning_text, f"{attribute!r} has no data, so it should not warn"

    assert outpath.exists()
    reparsed = Graph().parse(str(outpath), format="turtle")
    assert len(reparsed) == len(converter.to_graph())

    # Every node should be its expected WaTr class, with exactly its expected processes.
    for node_id, node_class in EXPECTED_NODE_TYPES.items():
        assert (LOCAL[node_id], RDF.type, node_class) in reparsed, node_id
        processes = set(reparsed.objects(LOCAL[node_id], WATR["hasProcess"]))
        assert processes == EXPECTED_PROCESSES.get(node_id, set()), node_id

    # Every pipe should be an s223:Pipe with its expected medium and role,
    # leaving its source node and entering its destination node.
    for conn_id, (medium, role) in EXPECTED_PIPE_MEDIA.items():
        conn = desal_network.connections[conn_id]
        assert (LOCAL[conn_id], RDF.type, S223["Pipe"]) in reparsed, conn_id
        assert (LOCAL[conn_id], S223["hasMedium"], medium) in reparsed, conn_id
        assert set(reparsed.objects(LOCAL[conn_id], S223["hasRole"])) == ({role} if role else set()), conn_id
        assert (LOCAL[conn_id + "-out"], S223["isConnectionPointOf"], LOCAL[conn.source.id]) in reparsed, conn_id
        assert (LOCAL[conn_id + "-in"], S223["isConnectionPointOf"], LOCAL[conn.destination.id]) in reparsed, conn_id

    # Every tag in the facility - not just one - should be a sensor whose
    # observed property carries its expected quantity kind and unit.
    for tag_id, (kind, unit) in EXPECTED_TAG_TRANSLATIONS.items():
        value = LOCAL[tag_id + "-value"]
        assert (LOCAL[tag_id], S223["observes"], value) in reparsed, tag_id
        assert (value, QUDT["hasQuantityKind"], QK[kind]) in reparsed, tag_id
        assert (value, QUDT["hasUnit"], UNIT[unit]) in reparsed, tag_id


def test_desalination_output_matches_reviewed_translation(converter, tmp_path):
    """The translated facility should be exactly the reviewed graph in
    desal_expected.ttl, so any change to the codec's output is caught.

    If UPDATE_EXPECTED_TTL is set, the file is written from the current output
    instead and the test is skipped.
    """
    outpath = tmp_path / "desal.ttl"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        converter.export_ttl(str(outpath))

    if os.environ.get("UPDATE_EXPECTED_TTL"):
        shutil.copyfile(outpath, DESAL_EXPECTED_TTL_PATH)
        pytest.skip(f"wrote {DESAL_EXPECTED_TTL_PATH}; review it before committing")
    assert os.path.exists(DESAL_EXPECTED_TTL_PATH), (
        "desal_expected.ttl is missing; create it with UPDATE_EXPECTED_TTL=1, review it, and commit it"
    )

    # parse both files so each side goes through the same Turtle round trip
    actual = to_isomorphic(Graph().parse(str(outpath), format="turtle"))
    expected = to_isomorphic(Graph().parse(DESAL_EXPECTED_TTL_PATH, format="turtle"))
    _, only_actual, only_expected = graph_diff(actual, expected)
    assert actual == expected, (
        "output differs from desal_expected.ttl (if the change is intended, rerun with "
        "UPDATE_EXPECTED_TTL=1 and review the file's diff)\n"
        f"new triples:\n{only_actual.serialize(format='nt')}\n"
        f"missing triples:\n{only_expected.serialize(format='nt')}"
    )
