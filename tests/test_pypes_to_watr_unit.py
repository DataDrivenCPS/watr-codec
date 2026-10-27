"""Unit tests for watr_codec.pypes_to_watr.PyPES2WaTr.

These tests exercise the individual translation helpers in isolation using
small, hand-built pype_schema objects rather than a full facility, so that
each piece of translation logic (unit conversion, medium/role handling,
connection-point naming, attribute skipping, etc.) can be verified on its
own. The two end-to-end tests that exercise the full desalination.json
pipeline live in test_pypes_to_watr_e2e.py.
"""

import warnings

import pytest
from rdflib import Graph
from rdflib.namespace import RDF

from pype_schema.connection import Pipe
from pype_schema.node import Digestion, Junction, Network, Pump, Tank
from pype_schema.tag import Tag, TagType
from pype_schema.units import u
from pype_schema.utils import ContentsType, DigesterType, PumpType, parse_units

from watr_codec.pypes_to_watr import NotImplementedWarning, PyPES2WaTr


# --------- Fixtures ---------
@pytest.fixture
def converter():
    """A new PyPES2WaTr instance configured by the project's mapping files.

    Returns
    -------
    watr_codec.pypes_to_watr.PyPES2WaTr
        A converter wrapping an empty `Network` named `"World"`, using the
        local prefix `"test"`.
    """
    empty_world = Network("World", ContentsType.Brine, ContentsType.Brine, nodes={}, connections={})
    return PyPES2WaTr(empty_world, local_prefix="test")


@pytest.fixture
def source_tank():
    """A brine `Tank` named `"Source"` with no elevation or volume data."""
    return Tank("Source", ContentsType.Brine, ContentsType.Brine, elevation=None, volume=None)


@pytest.fixture
def dest_tank():
    """A brine `Tank` named `"Dest"` with no elevation or volume data."""
    return Tank("Dest", ContentsType.Brine, ContentsType.Brine, elevation=None, volume=None)


@pytest.fixture
def pipe(source_tank, dest_tank):
    """A brine `Pipe` named `"Pipe1"` from `source_tank` to `dest_tank`."""
    return Pipe(
        "Pipe1",
        ContentsType.Brine,
        source_tank,
        dest_tank,
        min_flow=None,
        max_flow=None,
        design_flow=None,
        diameter=2.0,
        friction=0.5,
    )


@pytest.fixture
def run_status_tag():
    """A pump `RunStatus` tag, which in PyPES is both unitless and contentless."""
    return Tag(
        "PumpStatus",
        units=None,
        tag_type=TagType.RunStatus,
        source_unit_id="total",
        dest_unit_id="total",
        parent_id="Pump1",
        contents=None,
    )


# --------- _sanitize_id ---------
class TestSanitizeId:
    """Tests for `PyPES2WaTr._sanitize_id`."""

    def test_replaces_spaces_with_dashes(self, converter):
        """Spaces in an ID should be replaced with dashes."""
        assert converter._sanitize_id("Pump 400 A") == "Pump-400-A"

    def test_leaves_ids_without_spaces_unchanged(self, converter):
        """An ID with no spaces should be returned unchanged."""
        assert converter._sanitize_id("HPPump") == "HPPump"


# --------- convert_units / convert_contents / convert_attribute / convert_tag_type ---------
class TestConvertUnits:
    """Tests for `PyPES2WaTr.convert_units`."""

    def test_known_unit_returns_mapping_entry(self, converter):
        """A unit present in the mapping should return its full entry."""
        unit_dict = converter.convert_units(parse_units("psi"))
        assert unit_dict == {
            "name": "PSI",
            "uri": "unit",
            "reference": "https://qudt.org/vocab/unit/PSI",
        }

    def test_meter_maps_to_qudt_meter(self, converter):
        """`meter` should map to QUDT's `unit:M`."""
        assert converter.convert_units(parse_units("meter"))["name"] == "M"

    def test_unit_mapped_to_empty_dict_returns_empty_dict(self, converter):
        """A unit intentionally left unmapped in the mapping file returns {}."""
        # "MGD" is present in the mapping but intentionally left unmapped ({}).
        assert converter.convert_units(parse_units("MGD")) == {}

    def test_unmapped_unit_raises_key_error(self, converter):
        """A unit absent from the mapping entirely should raise KeyError."""
        with pytest.raises(KeyError):
            converter.convert_units(parse_units("kW"))


class TestConvertContents:
    """Tests for `PyPES2WaTr.convert_contents`."""

    def test_contents_without_role(self, converter):
        """Contents with no associated role should omit the "role" key."""
        medium_dict = converter.convert_contents(ContentsType.Brine)
        assert medium_dict["name"] == "Water-Brine"
        assert medium_dict["uri"] == "watr"
        assert "role" not in medium_dict

    def test_contents_with_role(self, converter):
        """Contents with an associated role should include role/role-uri."""
        medium_dict = converter.convert_contents(ContentsType.ProductWater)
        assert medium_dict["role"] == "Role-Permeate"
        assert medium_dict["role-uri"] == "watr"


class TestConvertAttribute:
    """Tests for `PyPES2WaTr.convert_attribute`."""

    def test_known_quantifiable_attribute(self, converter):
        """A normal attribute should be detected as a quantifiable kind."""
        prop_data, is_quant_kind = converter.convert_attribute("diameter")
        assert is_quant_kind is True
        assert prop_data["name"] == "Diameter"

    def test_unmapped_attribute_raises_key_error(self, converter):
        """An attribute absent from the mapping should raise KeyError."""
        with pytest.raises(KeyError):
            converter.convert_attribute("not_a_real_attribute")

    def test_enumeration_kind_attribute_is_detected(self, converter):
        """An attribute whose mapping entry has kind "EnumerationKind" should
        be detected as an enumeration kind rather than a quantity kind."""
        # TODO: replace with a real attribute once one with an EnumerationKind
        # is added to the mapping (none exists yet)
        converter.mapping["PyPES2WaTr"]["attributes"]["fake_enum_attr"] = {
            "name": "Binary-OnOff",
            "uri": "s223",
            "kind": "EnumerationKind",
        }
        prop_data, is_quant_kind = converter.convert_attribute("fake_enum_attr")
        assert is_quant_kind is False
        assert prop_data["name"] == "Binary-OnOff"


class TestConvertTagType:
    """Tests for `PyPES2WaTr.convert_tag_type`."""

    def test_known_quantifiable_tag_type(self, converter):
        """A normal tag type should be detected as a quantifiable kind."""
        prop_data, is_quant_kind = converter.convert_tag_type(TagType.Flow)
        assert is_quant_kind is True
        assert prop_data["name"] == "VolumeFlowRate"

    def test_run_status_is_enumeration_kind(self, converter):
        """RunStatus maps to s223:Binary-OnOff, which is an enumeration kind."""
        prop_data, is_quant_kind = converter.convert_tag_type(TagType.RunStatus)
        assert is_quant_kind is False
        assert prop_data["name"] == "Binary-OnOff"

    def test_unmapped_tag_type_raises_key_error(self, converter):
        """A tag type mapped to an empty placeholder should raise KeyError.

        TDS is listed in the mapping but only as an empty placeholder ({}),
        so looking up its "kind" key fails. This documents a real gap:
        translate_tag() has no equivalent of NOT_YET_IMPLEMENTED_ATTRIBUTES
        to skip these gracefully, so a TDS/COD/BOD/InFlow/OutFlow/NetFlow/
        SetPoint tag currently crashes translation instead of warning.
        """
        with pytest.raises(KeyError):
            converter.convert_tag_type(TagType.TDS)

    def test_unknown_kind_raises_value_error(self, converter):
        """A mapping entry whose kind is misspelled should raise ValueError
        rather than silently being treated as an enumeration kind."""
        converter.mapping["PyPES2WaTr"]["tag_types"]["Flow"]["kind"] = "QuantKind"
        with pytest.raises(ValueError):
            converter.convert_tag_type(TagType.Flow)


# --------- generate_conn_point_name ---------
class TestGenerateConnPointName:
    """Tests for `PyPES2WaTr.generate_conn_point_name`."""

    def test_returns_name_unchanged_when_unused(self, converter):
        """A name with no existing collision should be returned unchanged."""
        assert converter.generate_conn_point_name("Tank1-cp-1") == "Tank1-cp-1"

    def test_increments_suffix_on_collision(self, converter):
        """A single collision should bump the numeric suffix by one."""
        converter.conn_point_dict["Tank1-cp-1"] = {}
        assert converter.generate_conn_point_name("Tank1-cp-1") == "Tank1-cp-2"

    def test_keeps_incrementing_past_multiple_collisions(self, converter):
        """Repeated collisions should keep incrementing the suffix, including
        past single digits."""
        for num in range(1, 10):
            converter.conn_point_dict[f"Tank1-cp-{num}"] = {}
        assert converter.generate_conn_point_name("Tank1-cp-1") == "Tank1-cp-10"

    def test_collision_without_numeric_suffix_raises_value_error(self, converter):
        """A taken name with no numeric suffix should raise rather than guess."""
        converter.conn_point_dict["Tank1-cp"] = {}
        with pytest.raises(ValueError):
            converter.generate_conn_point_name("Tank1-cp")


# --------- create_conn_points ---------
class TestCreateConnPoints:
    """Tests for `PyPES2WaTr.create_conn_points`."""

    def test_creates_source_and_dest_points_with_medium_and_role(self, converter, source_tank, dest_tank):
        """Both connection points should be typed and carry medium/role."""
        permeate_pipe = Pipe(
            "Pipe1", ContentsType.ProductWater, source_tank, dest_tank,
            min_flow=None, max_flow=None, design_flow=None,
        )

        source_name, dest_name = converter.create_conn_points(permeate_pipe)

        assert source_name == "Source-cp-1"
        assert dest_name == "Dest-cp-1"
        assert set(converter.conn_point_dict) == {"Source-cp-1", "Dest-cp-1"}

        ns = converter.model.namespaces
        s223, watr, local = ns["s223"], ns["watr"], ns["test"]
        graph = converter.model.graph

        assert (local["Source-cp-1"], RDF.type, s223["OutletConnectionPoint"]) in graph
        assert (local["Dest-cp-1"], RDF.type, s223["InletConnectionPoint"]) in graph
        assert (local["Source-cp-1"], s223["isConnectionPointOf"], local["Source"]) in graph
        assert (local["Dest-cp-1"], s223["isConnectionPointOf"], local["Dest"]) in graph
        assert (local["Source-cp-1"], s223["connectsThrough"], local["Pipe1"]) in graph
        assert (local["Dest-cp-1"], s223["connectsThrough"], local["Pipe1"]) in graph

        # ProductWater carries a role, so both connection points should get it.
        assert (local["Source-cp-1"], s223["hasRole"], watr["Role-Permeate"]) in graph
        assert (local["Dest-cp-1"], s223["hasRole"], watr["Role-Permeate"]) in graph

    def test_repeated_node_id_gets_disambiguated_name(self, converter, source_tank, dest_tank, pipe):
        """A node used as source in two connections should get -cp-1/-cp-2."""
        other_tank = Tank("Other", ContentsType.Brine, ContentsType.Brine, elevation=None, volume=None)
        second_pipe = Pipe(
            "Pipe2", ContentsType.Brine, source_tank, other_tank,
            min_flow=None, max_flow=None, design_flow=None,
        )

        source_name_1, _ = converter.create_conn_points(pipe)
        source_name_2, _ = converter.create_conn_points(second_pipe)

        assert source_name_1 == "Source-cp-1"
        assert source_name_2 == "Source-cp-2"


# --------- translate_attribute ---------
class TestTranslateAttribute:
    """Tests for `PyPES2WaTr.translate_attribute`."""

    def test_plain_value_has_no_unit_triple(self, converter):
        """A plain (non-Pint) value should produce no hasUnit triple."""
        result = converter.translate_attribute("elevation", 12.5, "Tank1")

        assert result["prop_type"] == "QuantifiableProperty"
        assert result["units"] == {}  # units dict should be empty since no pint units given

        ns = converter.model.namespaces
        s223, qudt, qudtqk = ns["s223"], ns["qudt"], ns["qudtqk"]
        graph = converter.model.graph
        term = ns["test"]["Tank1elevation"]

        assert (term, RDF.type, s223["QuantifiableProperty"]) in graph
        assert (term, s223["hasValue"], converter.model.literal(12.5)) in graph
        assert (term, qudt["hasQuantityKind"], qudtqk["Altitude"]) in graph
        assert not list(graph.triples((term, s223["hasUnit"], None)))

    def test_pint_value_extracts_magnitude_and_unit(self, converter):
        """A Pint quantity should have its magnitude and unit split apart."""
        value = u.Quantity(3.0, "meter")
        result = converter.translate_attribute("elevation", value, "Tank1")

        ns = converter.model.namespaces
        s223 = ns["s223"]
        graph = converter.model.graph
        term = ns["test"]["Tank1elevation"]

        assert result["units"]["name"] == "M"
        assert (term, s223["hasValue"], converter.model.literal(3.0)) in graph
        assert (term, s223["hasUnit"], ns["unit"]["M"]) in graph

    def test_none_value_creates_no_property(self, converter):
        """An attribute without data should not be added to the graph at all."""
        result = converter.translate_attribute("volume", None, "Tank1")

        term = converter.model.namespaces["test"]["Tank1volume"]
        graph = converter.model.graph

        assert result is None
        assert "Tank1volume" not in converter.property_dict
        assert not list(graph.triples((term, None, None)))
        assert not list(graph.triples((None, None, term)))

    def test_contents_adds_medium_and_role(self, converter):
        """Passing contents with a role should add ofMedium and hasRole triples."""
        converter.translate_attribute("diameter", 1.0, "Pipe1", contents=ContentsType.ProductWater)

        ns = converter.model.namespaces
        s223, watr = ns["s223"], ns["watr"]
        graph = converter.model.graph
        term = ns["test"]["Pipe1diameter"]

        assert (term, s223["ofMedium"], s223["Fluid-Water"]) in graph
        assert (term, s223["hasRole"], watr["Role-Permeate"]) in graph

    def test_enumeration_kind_attribute_uses_has_enumeration_kind(self, converter):
        """An enumeration-kind attribute should use hasEnumerationKind."""
        # TODO: replace with a real attribute once one with an EnumerationKind
        # is added to the mapping (none exists yet)
        converter.mapping["PyPES2WaTr"]["attributes"]["fake_enum_attr"] = {
            "name": "Binary-OnOff",
            "uri": "s223",
            "kind": "EnumerationKind",
        }
        result = converter.translate_attribute("fake_enum_attr", "on", "Tank1")

        assert result["prop_type"] == "EnumerableProperty"

        ns = converter.model.namespaces
        s223, qudt = ns["s223"], ns["qudt"]
        graph = converter.model.graph
        term = ns["test"]["Tank1fake_enum_attr"]

        assert (term, RDF.type, s223["EnumerableProperty"]) in graph
        assert (term, s223["hasEnumerationKind"], s223["Binary-OnOff"]) in graph
        assert not list(graph.triples((term, qudt["hasQuantityKind"], None)))


# --------- translate_tag ---------
class TestTranslateTag:
    """Tests for `PyPES2WaTr.translate_tag`."""

    def test_basic_quantifiable_tag(self, converter):
        """A normal quantifiable tag should get quantity kind, unit, and medium."""
        tag = Tag(
            "FlowTag",
            units=parse_units("gal/min"),
            tag_type=TagType.Flow,
            source_unit_id=1,
            dest_unit_id=2,
            parent_id="Tank1",
            contents=ContentsType.Brine,
        )
        result = converter.translate_tag(tag)

        assert result["prop_type"] == "QuantifiableObservableProperty"
        assert result["source_unit_id"] == 1
        assert result["dest_unit_id"] == 2

        ns = converter.model.namespaces
        s223, qudt, qudtqk, unit, watr = ns["s223"], ns["qudt"], ns["qudtqk"], ns["unit"], ns["watr"]
        graph = converter.model.graph
        term = ns["test"]["FlowTag"]

        assert (term, RDF.type, s223["QuantifiableObservableProperty"]) in graph
        assert (term, qudt["hasQuantityKind"], qudtqk["VolumeFlowRate"]) in graph
        assert (term, s223["hasUnit"], unit["GAL_US-PER-MIN"]) in graph
        assert (term, s223["ofMedium"], watr["Water-Brine"]) in graph

    def test_tss_tag_adds_substance(self, converter):
        """A TSS tag should link to the suspended-solids substance."""
        tag = Tag(
            "TSSTag",
            units=parse_units("mg/L"),
            tag_type=TagType.TSS,
            source_unit_id="total",
            dest_unit_id="total",
            parent_id="Tank1",
            contents=ContentsType.Brine,
        )
        converter.translate_tag(tag)

        ns = converter.model.namespaces
        term = ns["test"]["TSSTag"]
        assert (term, ns["s223"]["ofSubstance"], ns["watr"]["Constituent-SuspendedSolids"]) in converter.model.graph

    def test_status_tag_uses_enumeration_kind(self, converter, run_status_tag):
        """A RunStatus tag should be an enumerated property of kind Binary-OnOff."""
        result = converter.translate_tag(run_status_tag)

        ns = converter.model.namespaces
        s223, qudt = ns["s223"], ns["qudt"]
        graph = converter.model.graph
        term = ns["test"]["PumpStatus"]

        assert result["prop_type"] == "EnumeratedObservableProperty"
        assert (term, RDF.type, s223["EnumeratedObservableProperty"]) in graph
        assert (term, s223["hasEnumerationKind"], s223["Binary-OnOff"]) in graph
        assert not list(graph.triples((term, qudt["hasQuantityKind"], None)))

    def test_unitless_tag_is_supported(self, converter, run_status_tag):
        """A tag with no units should translate, with no hasUnit triple."""
        result = converter.translate_tag(run_status_tag)

        term = converter.model.namespaces["test"]["PumpStatus"]
        has_unit = converter.model.namespaces["s223"]["hasUnit"]

        assert result["units"] == {}
        assert not list(converter.model.graph.triples((term, has_unit, None)))

    def test_contentless_tag_has_no_medium_triple(self, converter, run_status_tag):
        """A contentless tag type (e.g. RunStatus) should produce no ofMedium triple."""
        converter.translate_tag(run_status_tag)

        term = converter.model.namespaces["test"]["PumpStatus"]
        of_medium = converter.model.namespaces["s223"]["ofMedium"]
        assert not list(converter.model.graph.triples((term, of_medium, None)))

    def test_missing_contents_on_non_contentless_tag_raises_value_error(self, converter):
        """A Flow tag must have contents in PyPES, so omitting them is an error."""
        tag = Tag(
            "FlowTag",
            units=parse_units("gal/min"),
            tag_type=TagType.Flow,
            source_unit_id="total",
            dest_unit_id="total",
            parent_id="Tank1",
            contents=None,
        )
        with pytest.raises(ValueError):
            converter.translate_tag(tag)


# --------- translate_node ---------
class TestTranslateNode:
    """Tests for `PyPES2WaTr.translate_node`."""

    def test_translates_type_and_attributes(self, converter):
        """A node's type and its attributes with data should be translated."""
        tank = Tank("Tank1", ContentsType.Brine, ContentsType.Brine, elevation=3.0, volume=None)
        result = converter.translate_node(tank)

        ns = converter.model.namespaces
        local, watr, s223 = ns["test"], ns["watr"], ns["s223"]
        graph = converter.model.graph

        assert result["node"] == "Tank"
        assert (local["Tank1"], RDF.type, watr["Tank"]) in graph
        # elevation should have become a property linked back to the node...
        assert (local["Tank1"], s223["hasProperty"], local["Tank1elevation"]) in graph
        # ...but volume has no data, so it should not exist at all
        assert (local["Tank1"], s223["hasProperty"], local["Tank1volume"]) not in graph

    def test_not_yet_implemented_attribute_warns_and_is_skipped(self, converter):
        """A not-yet-implemented attribute should warn and not be translated."""
        pump = Pump(
            "Pump1",
            ContentsType.Brine,
            ContentsType.Brine,
            elevation=None,
            min_flow=None,
            max_flow=None,
            design_flow=None,
            power_rating=None,
            num_units=1,
            pump_type=PumpType.Constant,
        )

        with pytest.warns(NotImplementedWarning, match="pump_type"):
            converter.translate_node(pump)

        local = converter.model.namespaces["test"]
        assert not list(converter.model.graph.triples((None, None, local["Pump1pump_type"])))
        assert "Pump1pump_type" not in converter.property_dict

    def test_hides_medium_duplicates(self, converter):
        """Repeated media across input/output contents should be deduped."""
        tank = Tank(
            "MultiTank",
            input_contents=[ContentsType.Brine, ContentsType.Brine],
            output_contents=[ContentsType.Brine],
            elevation=None,
            volume=None,
        )
        converter.translate_node(tank)

        ns = converter.model.namespaces
        local, s223, watr = ns["test"], ns["s223"], ns["watr"]
        media_triples = list(converter.model.graph.triples((local["MultiTank"], s223["hasMedium"], None)))
        assert media_triples == [(local["MultiTank"], s223["hasMedium"], watr["Water-Brine"])]

    def test_hasprocess_added_when_node_type_declares_a_process(self, converter):
        """A node type whose mapping entry declares a process should link it."""
        # NOTE: Brine is used because sludge/biogas contents are not yet in the mapping
        digester = Digestion(
            "Digester1",
            ContentsType.Brine,
            ContentsType.Brine,
            min_flow=None,
            max_flow=None,
            design_flow=None,
            num_units=1,
            volume=None,
            digester_type=DigesterType.Anaerobic,
        )

        with pytest.warns(NotImplementedWarning, match="digester_type"):
            converter.translate_node(digester)

        ns = converter.model.namespaces
        assert (ns["test"]["Digester1"], ns["watr"]["hasProcess"], ns["watr"]["Process-Digestion"]) in converter.model.graph

    def test_cnx_added_for_node_with_inbound_and_outbound_connection(self, converter, source_tank, dest_tank):
        """A node with one inbound and one outbound connection gets 2 cnx triples."""
        junction = Junction("Middle", ContentsType.Brine, ContentsType.Brine)
        inbound = Pipe("InPipe", ContentsType.Brine, source_tank, junction, min_flow=None, max_flow=None, design_flow=None)
        outbound = Pipe("OutPipe", ContentsType.Brine, junction, dest_tank, min_flow=None, max_flow=None, design_flow=None)

        converter.translate_connection(inbound)
        converter.translate_connection(outbound)
        converter.translate_node(junction)

        ns = converter.model.namespaces
        local, s223 = ns["test"], ns["s223"]
        cnx_triples = list(converter.model.graph.triples((local["Middle"], s223["cnx"], None)))
        cnx_targets = {str(o) for _, _, o in cnx_triples}
        assert str(local["Middle-cp-1"]) in cnx_targets  # inbound dest point
        assert str(local["Middle-cp-2"]) in cnx_targets  # outbound source point
        assert len(cnx_triples) == 2

    def test_no_cnx_when_only_inbound_connection_exists(self, converter, source_tank):
        """A node with only an inbound connection should get no cnx triples."""
        junction = Junction("DeadEnd", ContentsType.Brine, ContentsType.Brine)
        inbound = Pipe("InPipe", ContentsType.Brine, source_tank, junction, min_flow=None, max_flow=None, design_flow=None)

        converter.translate_connection(inbound)
        converter.translate_node(junction)

        ns = converter.model.namespaces
        assert not list(converter.model.graph.triples((ns["test"]["DeadEnd"], ns["s223"]["cnx"], None)))


# --------- translate_connection ---------
class TestTranslateConnection:
    """Tests for `PyPES2WaTr.translate_connection`."""

    def test_translates_type_medium_and_attributes(self, converter, pipe):
        """A connection's type, medium, and attributes should be translated."""
        result = converter.translate_connection(pipe)

        ns = converter.model.namespaces
        local, s223, watr = ns["test"], ns["s223"], ns["watr"]
        graph = converter.model.graph

        assert (local["Pipe1"], RDF.type, s223["Pipe"]) in graph
        assert (local["Pipe1"], s223["hasMedium"], watr["Water-Brine"]) in graph
        assert (local["Pipe1"], s223["hasProperty"], local["Pipe1diameter"]) in graph
        assert (local["Pipe1"], s223["hasProperty"], local["Pipe1friction_coeff"]) in graph
        assert result["source"] == "Source"
        assert result["destination"] == "Dest"

    def test_not_yet_implemented_attributes_warn(self, converter, pipe):
        """heating_values and bidirectional should each raise a warning."""
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            converter.translate_connection(pipe)

        messages = [str(w.message) for w in caught if issubclass(w.category, NotImplementedWarning)]
        assert any("heating_values" in m for m in messages)
        assert any("bidirectional" in m for m in messages)

    def test_updates_node_to_conn_ids_for_both_endpoints(self, converter, pipe):
        """Both the source and destination node should track the connection."""
        converter.translate_connection(pipe)

        assert "Pipe1" in converter.node_to_conn_ids["Source"]
        assert "Pipe1" in converter.node_to_conn_ids["Dest"]

    def test_invalid_endpoints_raise_value_error_in_translate_node(self, converter, pipe):
        """A connection tracked against a node that isn't its endpoint should
        cause translate_node() to raise ValueError."""
        other_tank = Tank("Other", ContentsType.Brine, ContentsType.Brine, elevation=None, volume=None)

        converter.translate_connection(pipe)
        converter.node_to_conn_ids.setdefault("Other", []).append("Pipe1")

        with pytest.raises(ValueError):
            converter.translate_node(other_tank)


# --------- translate_network (integration of the pieces above) ---------
class TestTranslateNetwork:
    """Tests for `PyPES2WaTr.translate_network`."""

    def test_translates_nodes_connections_and_tags(self, converter, source_tank):
        """A flat network's nodes, connections, and tags should all be translated."""
        level_tag = Tag(
            "LevelTag",
            units=parse_units("meter"),
            tag_type=TagType.Level,
            source_unit_id="total",
            dest_unit_id="total",
            parent_id="Tank2",
            contents=ContentsType.Brine,
        )
        tank2 = Tank("Tank2", ContentsType.Brine, ContentsType.Brine, elevation=None, volume=None, tags={"LevelTag": level_tag})
        pipe = Pipe("Pipe1", ContentsType.Brine, source_tank, tank2, min_flow=None, max_flow=None, design_flow=None)

        network = Network(
            "World",
            ContentsType.Brine,
            ContentsType.Brine,
            nodes={"Source": source_tank, "Tank2": tank2},
            connections={"Pipe1": pipe},
        )
        converter.world = network
        converter.translate_network(network)

        assert set(converter.node_dict) == {"Source", "Tank2"}
        assert set(converter.conn_dict) == {"Pipe1"}
        assert "LevelTag" in converter.property_dict

    def test_recurses_into_nested_network_and_adds_it_as_a_node(self, converter, source_tank, dest_tank):
        """A nested Network's children should be translated, and the nested
        Network itself should also be translated as a node of its parent."""
        sub_network = Network(
            "SubNet",
            ContentsType.Brine,
            ContentsType.Brine,
            nodes={"Source": source_tank},
            connections={},
        )
        world = Network(
            "World",
            ContentsType.Brine,
            ContentsType.Brine,
            nodes={"Dest": dest_tank, "SubNet": sub_network},
            connections={},
        )
        converter.world = world
        converter.translate_network(world)

        # the nested Network's children are translated...
        assert "Source" in converter.node_dict
        # ...and the sub-network itself is translated as a node of its parent,
        # since converter.world.id ("World") != sub_network.id ("SubNet").
        assert "SubNet" in converter.node_dict

        ns = converter.model.namespaces
        assert (ns["test"]["SubNet"], RDF.type, ns["rec"]["Region"]) in converter.model.graph


# --------- to_graph / export_ttl ---------
class TestToGraphAndExport:
    """Tests for `PyPES2WaTr.to_graph` and `PyPES2WaTr.export_ttl`."""

    def test_to_graph_is_idempotent(self, converter, source_tank):
        """Calling to_graph() twice should not re-run the translation."""
        converter.world = Network(
            "World", ContentsType.Brine, ContentsType.Brine, nodes={"Source": source_tank}, connections={}
        )

        graph1 = converter.to_graph()
        triple_count = len(graph1)
        graph2 = converter.to_graph()

        assert converter._translated is True
        assert graph1 is graph2
        assert len(graph2) == triple_count

    def test_export_ttl_writes_valid_turtle(self, converter, tmp_path):
        """export_ttl() should write a file that reparses to the same graph."""
        tank = Tank("Tank1", ContentsType.Brine, ContentsType.Brine, elevation=3.0, volume=None)
        converter.world = Network(
            "World", ContentsType.Brine, ContentsType.Brine, nodes={"Tank1": tank}, connections={}
        )
        outpath = tmp_path / "out.ttl"

        converter.export_ttl(str(outpath))

        assert outpath.exists()
        reparsed = Graph().parse(str(outpath), format="turtle")
        assert len(reparsed) == len(converter.model.graph)
