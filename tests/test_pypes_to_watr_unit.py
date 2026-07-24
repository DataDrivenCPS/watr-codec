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
from rdflib.namespace import RDF

from pype_schema.connection import Pipe
from pype_schema.node import Junction, Network, Tank
from pype_schema.tag import Tag, TagType
from pype_schema.utils import ContentsType, parse_units
from pype_schema.units import u

from watr_codec.pypes_to_watr import NotImplementedWarning, PyPES2WaTr


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def make_tank(id_="Tank1", contents=ContentsType.Brine, elevation=None, volume=None, tags=None):
    """Build a minimal `pype_schema.node.Tank` for use in a test.

    Parameters
    ----------
    id_ : str, optional
        Tank ID. Defaults to `"Tank1"`.
    contents : pype_schema.utils.ContentsType, optional
        Contents used for both `input_contents` and `output_contents`.
        Defaults to `ContentsType.Brine`.
    elevation : float, optional
        Tank elevation attribute. Defaults to None.
    volume : float, optional
        Tank volume attribute. Defaults to None.
    tags : dict of Tag, optional
        Tags to attach to the tank. Defaults to an empty dict.

    Returns
    -------
    pype_schema.node.Tank
        A single-unit tank with the given attributes.
    """
    return Tank(
        id=id_,
        input_contents=contents,
        output_contents=contents,
        elevation=elevation,
        volume=volume,
        num_units=1,
        tags=tags or {},
    )


def make_junction(id_="Junction1", contents=ContentsType.Brine, tags=None):
    """Build a minimal `pype_schema.node.Junction` for use in a test.

    Parameters
    ----------
    id_ : str, optional
        Junction ID. Defaults to `"Junction1"`.
    contents : pype_schema.utils.ContentsType, optional
        Contents used for both `input_contents` and `output_contents`.
        Defaults to `ContentsType.Brine`.
    tags : dict of Tag, optional
        Tags to attach to the junction. Defaults to an empty dict.

    Returns
    -------
    pype_schema.node.Junction
        A junction with the given attributes.
    """
    return Junction(
        id=id_,
        input_contents=contents,
        output_contents=contents,
        tags=tags or {},
    )


def make_pipe(id_, source, destination, contents=ContentsType.Brine, tags=None, diameter=None, friction=None):
    """Build a minimal `pype_schema.connection.Pipe` for use in a test.

    Parameters
    ----------
    id_ : str
        Pipe ID.
    source : pype_schema.node.Node
        Node the pipe originates from.
    destination : pype_schema.node.Node
        Node the pipe terminates at.
    contents : pype_schema.utils.ContentsType, optional
        Contents carried by the pipe. Defaults to `ContentsType.Brine`.
    tags : dict of Tag, optional
        Tags to attach to the pipe. Defaults to an empty dict.
    diameter : float, optional
        Pipe diameter attribute. Defaults to None.
    friction : float, optional
        Pipe friction coefficient attribute. Defaults to None.

    Returns
    -------
    pype_schema.connection.Pipe
        A pipe connecting `source` to `destination` with the given
        attributes. `min_flow`/`max_flow`/`design_flow` are always None.
    """
    return Pipe(
        id=id_,
        contents=contents,
        source=source,
        destination=destination,
        min_flow=None,
        max_flow=None,
        design_flow=None,
        diameter=diameter,
        friction=friction,
        tags=tags or {},
    )


def make_tag(
    id_,
    tag_type,
    units=None,
    contents=None,
    parent_id="Tank1",
    source_unit_id="total",
    dest_unit_id="total",
):
    """Build a minimal `pype_schema.tag.Tag` for use in a test.

    Parameters
    ----------
    id_ : str
        Tag ID.
    tag_type : pype_schema.tag.TagType
        Type of the tag (e.g. `TagType.Flow`).
    units : pint.Unit, optional
        Units of the tag's value. Defaults to None.
    contents : pype_schema.utils.ContentsType, optional
        Contents the tag observes. Defaults to None.
    parent_id : str, optional
        ID of the node or connection this tag belongs to. Defaults to
        `"Tank1"`.
    source_unit_id : int or str, optional
        Source unit ID for the tag. Defaults to `"total"`.
    dest_unit_id : int or str, optional
        Destination unit ID for the tag. Defaults to `"total"`.

    Returns
    -------
    pype_schema.tag.Tag
        A tag with the given attributes.
    """
    return Tag(
        id=id_,
        units=units,
        tag_type=tag_type,
        source_unit_id=source_unit_id,
        dest_unit_id=dest_unit_id,
        parent_id=parent_id,
        contents=contents,
    )


@pytest.fixture
def converter():
    """A fresh PyPES2WaTr backed by the real project mapping files.

    Returns
    -------
    watr_codec.pypes_to_watr.PyPES2WaTr
        A converter wrapping an empty `Network` named `"World"`, using the
        local prefix `"test"`.
    """
    empty_world = Network("World", ContentsType.Brine, ContentsType.Brine, nodes={}, connections={})
    return PyPES2WaTr(empty_world, local_prefix="test")


@pytest.fixture
def ns(converter):
    """Shortcut accessors to the rdflib namespaces the converter knows about.

    Parameters
    ----------
    converter : watr_codec.pypes_to_watr.PyPES2WaTr
        Converter to read namespaces from (see `converter` fixture).

    Returns
    -------
    dict of str to rdflib.Namespace
        Mapping of namespace prefix (e.g. `"s223"`, `"test"`) to the
        corresponding rdflib `Namespace`.
    """
    return converter.model.namespaces


# ---------------------------------------------------------------------------
# _sanitize_id
# ---------------------------------------------------------------------------


class TestSanitizeId:
    """Tests for `PyPES2WaTr._sanitize_id`."""

    def test_replaces_spaces_with_dashes(self, converter):
        """Spaces in an ID should be replaced with dashes."""
        assert converter._sanitize_id("Pump 400 A") == "Pump-400-A"

    def test_leaves_ids_without_spaces_unchanged(self, converter):
        """An ID with no spaces should be returned unchanged."""
        assert converter._sanitize_id("HPPump") == "HPPump"


# ---------------------------------------------------------------------------
# convert_units / convert_contents / convert_attribute / convert_tag_type
# ---------------------------------------------------------------------------


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

    def test_unit_mapped_to_empty_dict_returns_empty_dict(self, converter):
        """A unit intentionally left unmapped in the mapping file returns {}."""
        # "MGD" is present in the mapping but intentionally left unmapped ({}).
        assert converter.convert_units(parse_units("MGD")) == {}

    def test_unmapped_unit_raises_key_error(self, converter):
        """A unit absent from the mapping entirely should raise KeyError."""
        with pytest.raises(KeyError):
            converter.convert_units(parse_units("meter"))


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
        """An attribute whose mapped name contains "EnumerationKind" should
        be detected as an enumeration kind rather than a quantity kind."""
        # No attribute in the current mapping actually uses "EnumerationKind"
        # in its name, so inject one to exercise that branch of the logic.
        converter.mapping["PyPES2WaTr"]["attributes"]["fake_enum_attr"] = {
            "name": "SomeEnumerationKind",
            "uri": "s223",
        }
        prop_data, is_quant_kind = converter.convert_attribute("fake_enum_attr")
        assert is_quant_kind is False
        assert prop_data["name"] == "SomeEnumerationKind"


class TestConvertTagType:
    """Tests for `PyPES2WaTr.convert_tag_type`."""

    def test_known_quantifiable_tag_type(self, converter):
        """A normal tag type should be detected as a quantifiable kind."""
        prop_data, is_quant_kind = converter.convert_tag_type(TagType.Flow)
        assert is_quant_kind is True
        assert prop_data["name"] == "VolumeFlowRate"

    def test_unmapped_tag_type_raises_key_error(self, converter):
        """A tag type mapped to an empty placeholder should raise KeyError.

        TDS is listed in the mapping but only as an empty placeholder ({}),
        so looking up its "name" key fails. This documents a real gap:
        translate_tag() has no equivalent of NOT_YET_IMPLEMENTED_ATTRIBUTES
        to skip these gracefully, so a TDS/COD/BOD/InFlow/OutFlow/NetFlow/
        SetPoint tag currently crashes translation instead of warning.
        """
        with pytest.raises(KeyError):
            converter.convert_tag_type(TagType.TDS)


# ---------------------------------------------------------------------------
# generate_conn_point_name
# ---------------------------------------------------------------------------


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
        """Repeated collisions should keep incrementing the suffix."""
        converter.conn_point_dict["Tank1-cp-1"] = {}
        converter.conn_point_dict["Tank1-cp-2"] = {}
        converter.conn_point_dict["Tank1-cp-3"] = {}
        assert converter.generate_conn_point_name("Tank1-cp-1") == "Tank1-cp-4"


# ---------------------------------------------------------------------------
# create_conn_points
# ---------------------------------------------------------------------------


class TestCreateConnPoints:
    """Tests for `PyPES2WaTr.create_conn_points`."""

    def test_creates_source_and_dest_points_with_medium_and_role(self, converter, ns):
        """Both connection points should be typed and carry medium/role."""
        source = make_tank("Source")
        dest = make_tank("Dest")
        pipe = make_pipe("Pipe1", source, dest, contents=ContentsType.ProductWater)

        source_name, dest_name = converter.create_conn_points(pipe)

        assert source_name == "Source-cp-1"
        assert dest_name == "Dest-cp-1"
        assert set(converter.conn_point_dict) == {"Source-cp-1", "Dest-cp-1"}

        s223 = ns["s223"]
        local = ns["test"]
        graph = converter.model.graph

        assert (local["Source-cp-1"], RDF.type, s223["OutletConnectionPoint"]) in graph
        assert (local["Dest-cp-1"], RDF.type, s223["InletConnectionPoint"]) in graph
        assert (local["Source-cp-1"], s223["isConnectionPointOf"], local["Source"]) in graph
        assert (local["Dest-cp-1"], s223["isConnectionPointOf"], local["Dest"]) in graph
        assert (local["Source-cp-1"], s223["connectsThrough"], local["Pipe1"]) in graph
        assert (local["Dest-cp-1"], s223["connectsThrough"], local["Pipe1"]) in graph

        # ProductWater carries a role, so both connection points should get it.
        watr = ns["watr"]
        assert (local["Source-cp-1"], s223["hasRole"], watr["Role-Permeate"]) in graph
        assert (local["Dest-cp-1"], s223["hasRole"], watr["Role-Permeate"]) in graph

    def test_repeated_node_id_gets_disambiguated_name(self, converter):
        """A node used as source in two connections should get -cp-1/-cp-2."""
        node_a = make_tank("Hub")
        node_b = make_tank("Other")
        node_c = make_tank("AnotherOther")

        pipe1 = make_pipe("Pipe1", node_a, node_b)
        pipe2 = make_pipe("Pipe2", node_a, node_c)

        source_name_1, _ = converter.create_conn_points(pipe1)
        source_name_2, _ = converter.create_conn_points(pipe2)

        assert source_name_1 == "Hub-cp-1"
        assert source_name_2 == "Hub-cp-2"


# ---------------------------------------------------------------------------
# translate_attribute
# ---------------------------------------------------------------------------


class TestTranslateAttribute:
    """Tests for `PyPES2WaTr.translate_attribute`."""

    def test_plain_value_has_no_unit_triple(self, converter, ns):
        """A plain (non-Pint) value should produce no hasUnit triple."""
        result = converter.translate_attribute("elevation", 12.5, "Tank1")

        assert result["prop_type"] == "QuantifiableProperty"
        assert result[  # units dict should be empty since no pint units given
            "units"
        ] == {}

        local = ns["test"]
        s223 = ns["s223"]
        qudt = ns["qudt"]
        qudtqk = ns["qudtqk"]
        graph = converter.model.graph
        term = local["Tank1elevation"]

        assert (term, RDF.type, s223["QuantifiableProperty"]) in graph
        assert (term, s223["hasValue"], converter.model.literal(12.5)) in graph
        assert (term, qudt["hasQuantityKind"], qudtqk["Altitude"]) in graph
        assert not list(graph.triples((term, s223["hasUnit"], None)))

    def test_pint_value_extracts_magnitude_and_unit(self, converter, ns):
        """A Pint quantity should have its magnitude and unit split apart."""
        value = u.Quantity(42, "psi")
        result = converter.translate_attribute("friction_coeff", value, "Tank1")

        local = ns["test"]
        s223 = ns["s223"]
        unit = ns["unit"]
        graph = converter.model.graph
        term = local["Tank1friction_coeff"]

        assert result["units"]["name"] == "PSI"
        assert (term, s223["hasValue"], converter.model.literal(42)) in graph
        assert (term, s223["hasUnit"], unit["PSI"]) in graph

    def test_none_value_adds_no_has_value_triple(self, converter, ns):
        """A None value should not produce a hasValue triple."""
        converter.translate_attribute("volume", None, "Tank1")

        local = ns["test"]
        s223 = ns["s223"]
        graph = converter.model.graph
        term = local["Tank1volume"]

        assert not list(graph.triples((term, s223["hasValue"], None)))

    def test_contents_adds_medium_and_role(self, converter, ns):
        """Passing contents with a role should add a hasRole triple."""
        converter.translate_attribute("diameter", 1.0, "Pipe1", contents=ContentsType.ProductWater)

        local = ns["test"]
        s223 = ns["s223"]
        watr = ns["watr"]
        graph = converter.model.graph
        term = local["Pipe1diameter"]

        assert (term, s223["ofMedium"], watr["Role-Permeate"]) not in graph  # sanity: role != medium
        assert (term, s223["hasRole"], watr["Role-Permeate"]) in graph

    def test_enumeration_kind_attribute_uses_has_enumeration_kind(self, converter, ns):
        """An enumeration-kind attribute should use hasEnumerationKind."""
        converter.mapping["PyPES2WaTr"]["attributes"]["fake_enum_attr"] = {
            "name": "SomeEnumerationKind",
            "uri": "s223",
        }
        result = converter.translate_attribute("fake_enum_attr", "on", "Tank1")

        assert result["prop_type"] == "EnumerableProperty"

        local = ns["test"]
        s223 = ns["s223"]
        graph = converter.model.graph
        term = local["Tank1fake_enum_attr"]

        assert (term, RDF.type, s223["EnumerableProperty"]) in graph
        assert (term, s223["hasEnumerationKind"], s223["SomeEnumerationKind"]) in graph
        assert not list(graph.triples((term, converter._predicate("qudt", "hasQuantityKind").iri, None)))

    def test_substance_relation_added_when_present(self, converter, ns):
        """An attribute whose mapping entry has a substance should link it."""
        converter.mapping["PyPES2WaTr"]["attributes"]["fake_substance_attr"] = {
            "name": "Concentration",
            "uri": "qudtqk",
            "substance": "Constituent-SuspendedSolids",
            "substance-uri": "watr",
        }
        converter.translate_attribute("fake_substance_attr", 5, "Tank1")

        local = ns["test"]
        s223 = ns["s223"]
        watr = ns["watr"]
        graph = converter.model.graph
        term = local["Tank1fake_substance_attr"]

        assert (term, s223["ofSubstance"], watr["Constituent-SuspendedSolids"]) in graph


# ---------------------------------------------------------------------------
# translate_tag
# ---------------------------------------------------------------------------


class TestTranslateTag:
    """Tests for `PyPES2WaTr.translate_tag`."""

    def test_basic_quantifiable_tag(self, converter, ns):
        """A normal quantifiable tag should get quantity kind, unit, and medium."""
        tag = make_tag(
            "FlowTag",
            TagType.Flow,
            units=parse_units("gal/min"),
            contents=ContentsType.Brine,
            parent_id="Tank1",
            source_unit_id=1,
            dest_unit_id=2,
        )
        result = converter.translate_tag(tag)

        assert result["prop_type"] == "QuantifiableObservableProperty"
        assert result["source_unit_id"] == 1
        assert result["dest_unit_id"] == 2

        local = ns["test"]
        s223 = ns["s223"]
        qudt = ns["qudt"]
        qudtqk = ns["qudtqk"]
        unit = ns["unit"]
        watr = ns["watr"]
        graph = converter.model.graph
        term = local["FlowTag"]

        assert (term, RDF.type, s223["QuantifiableObservableProperty"]) in graph
        assert (term, qudt["hasQuantityKind"], qudtqk["VolumeFlowRate"]) in graph
        assert (term, s223["hasUnit"], unit["GAL_US-PER-MIN"]) in graph
        assert (term, s223["ofMedium"], watr["Water-Brine"]) in graph

    def test_tss_tag_adds_substance(self, converter, ns):
        """A TSS tag should link to the suspended-solids substance."""
        tag = make_tag(
            "TSSTag",
            TagType.TSS,
            units=parse_units("mg/L"),
            contents=ContentsType.Brine,
        )
        converter.translate_tag(tag)

        local = ns["test"]
        s223 = ns["s223"]
        watr = ns["watr"]
        graph = converter.model.graph
        term = local["TSSTag"]

        assert (term, s223["ofSubstance"], watr["Constituent-SuspendedSolids"]) in graph

    def test_tag_without_contents_has_no_medium_triple(self, converter, ns):
        """A tag with contents=None should produce no ofMedium triple."""
        tag = make_tag("NoContentsTag", TagType.Flow, units=parse_units("gal/min"), contents=None)
        converter.translate_tag(tag)

        local = ns["test"]
        s223 = ns["s223"]
        graph = converter.model.graph
        term = local["NoContentsTag"]

        assert not list(graph.triples((term, s223["ofMedium"], None)))

    def test_tag_with_none_units_raises_key_error(self, converter):
        """A tag with units=None should currently crash rather than warn.

        Documents a real gap: translate_tag() calls convert_units(tag.units)
        unconditionally, so a tag with no units string (e.g. RunStatus,
        which is contentless and often unitless) crashes translation
        instead of leaving the unit fields empty.
        """
        tag = make_tag("Unitless", TagType.RunStatus, units=None)
        with pytest.raises(KeyError):
            converter.translate_tag(tag)


# ---------------------------------------------------------------------------
# translate_node
# ---------------------------------------------------------------------------


class TestTranslateNode:
    """Tests for `PyPES2WaTr.translate_node`."""

    def test_translates_type_and_attributes(self, converter, ns):
        """A node's type and its attributes should both be translated."""
        tank = make_tank("Tank1", elevation=3.0, volume=None)
        result = converter.translate_node(tank)

        local = ns["test"]
        watr = ns["watr"]
        s223 = ns["s223"]
        graph = converter.model.graph

        assert (local["Tank1"], RDF.type, watr["Tank"]) in graph
        # elevation should have become a property linked back to the node
        elevation_term = local["Tank1elevation"]
        assert (local["Tank1"], s223["hasProperty"], elevation_term) in graph
        assert result["node"] == "Tank"

    def test_not_yet_implemented_attribute_warns_and_is_skipped(self, converter, ns):
        """A not-yet-implemented attribute should warn and not be translated."""
        node = make_junction("Junction1")
        node.bidirectional = True  # not a real Junction attribute, but enough
        # to exercise the skip-and-warn branch in translate_node.

        with pytest.warns(NotImplementedWarning):
            converter.translate_node(node)

        local = ns["test"]
        graph = converter.model.graph
        assert not list(graph.triples((None, None, local["Junction1bidirectional"])))
        assert "Junction1bidirectional" not in converter.property_dict

    def test_hides_medium_duplicates(self, converter, ns):
        """Repeated media across input/output contents should be deduped."""
        tank = Tank(
            id="MultiTank",
            input_contents=[ContentsType.Brine, ContentsType.Brine],
            output_contents=[ContentsType.Brine],
            elevation=None,
            volume=None,
            tags={},
        )
        converter.translate_node(tank)

        local = ns["test"]
        s223 = ns["s223"]
        graph = converter.model.graph
        media_triples = list(graph.triples((local["MultiTank"], s223["hasMedium"], None)))
        assert len(media_triples) == 1

    def test_hasprocess_added_when_node_type_declares_a_process(self, converter, ns):
        """A node type whose mapping entry declares a process should link it."""

        # Duck-typed stand-in for pype_schema.node.Digestion: translate_node()
        # only relies on attribute access (not isinstance), and "Digestion"
        # is the mapping key that declares a `process`.
        class Digestion:
            """Minimal duck-typed stand-in for pype_schema.node.Digestion."""

            def __init__(self, id):
                """Set the bare-minimum attributes translate_node() reads.

                Parameters
                ----------
                id : str
                    Node ID.
                """
                self.id = id
                self.input_contents = []
                self.output_contents = []
                self.tags = {}

        node = Digestion("Digester1")
        converter.translate_node(node)

        local = ns["test"]
        watr = ns["watr"]
        graph = converter.model.graph
        assert (local["Digester1"], watr["hasProcess"], watr["Process-Digestion"]) in graph

    def test_cnx_added_for_node_with_inbound_and_outbound_connection(self, converter, ns):
        """A node with one inbound and one outbound connection gets 2 cnx triples."""
        upstream = make_tank("Upstream")
        junction = make_junction("Middle")
        downstream = make_tank("Downstream")

        inbound = make_pipe("InPipe", upstream, junction)
        outbound = make_pipe("OutPipe", junction, downstream)

        converter.translate_connection(inbound)
        converter.translate_connection(outbound)
        converter.translate_node(junction)

        local = ns["test"]
        s223 = ns["s223"]
        graph = converter.model.graph

        cnx_triples = list(graph.triples((local["Middle"], s223["cnx"], None)))
        cnx_targets = {str(o) for _, _, o in cnx_triples}
        assert str(local["Middle-cp-1"]) in cnx_targets  # inbound dest point
        assert str(local["Middle-cp-2"]) in cnx_targets  # outbound source point
        assert len(cnx_triples) == 2

    def test_no_cnx_when_only_inbound_connection_exists(self, converter, ns):
        """A node with only an inbound connection should get no cnx triples."""
        upstream = make_tank("Upstream")
        junction = make_junction("DeadEnd")
        inbound = make_pipe("InPipe", upstream, junction)

        converter.translate_connection(inbound)
        converter.translate_node(junction)

        local = ns["test"]
        s223 = ns["s223"]
        graph = converter.model.graph
        assert not list(graph.triples((local["DeadEnd"], s223["cnx"], None)))


# ---------------------------------------------------------------------------
# translate_connection
# ---------------------------------------------------------------------------


class TestTranslateConnection:
    """Tests for `PyPES2WaTr.translate_connection`."""

    def test_translates_type_medium_and_attributes(self, converter, ns):
        """A connection's type, medium, and attributes should be translated."""
        source = make_tank("Source")
        dest = make_tank("Dest")
        pipe = make_pipe("Pipe1", source, dest, diameter=2.0, friction=0.5)

        result = converter.translate_connection(pipe)

        local = ns["test"]
        s223 = ns["s223"]
        watr = ns["watr"]
        graph = converter.model.graph

        assert (local["Pipe1"], RDF.type, s223["Pipe"]) in graph
        assert (local["Pipe1"], s223["hasMedium"], watr["Water-Brine"]) in graph
        assert (local["Pipe1"], s223["hasProperty"], local["Pipe1diameter"]) in graph
        assert (local["Pipe1"], s223["hasProperty"], local["Pipe1friction_coeff"]) in graph
        assert result["source"] == "Source"
        assert result["destination"] == "Dest"

    def test_not_yet_implemented_attributes_warn(self, converter):
        """heating_values and bidirectional should each raise a warning."""
        source = make_tank("Source")
        dest = make_tank("Dest")
        pipe = make_pipe("Pipe1", source, dest)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            converter.translate_connection(pipe)

        messages = [str(w.message) for w in caught if issubclass(w.category, NotImplementedWarning)]
        assert any("heating_values" in m for m in messages)
        assert any("bidirectional" in m for m in messages)

    def test_updates_node_to_conn_ids_for_both_endpoints(self, converter):
        """Both the source and destination node should track the connection."""
        source = make_tank("Source")
        dest = make_tank("Dest")
        pipe = make_pipe("Pipe1", source, dest)

        converter.translate_connection(pipe)

        assert "Pipe1" in converter.node_to_conn_ids["Source"]
        assert "Pipe1" in converter.node_to_conn_ids["Dest"]

    def test_invalid_endpoints_raise_value_error_in_translate_node(self, converter):
        """A connection tracked against a node that isn't its endpoint should
        cause translate_node() to raise ValueError."""
        # translate_node raises ValueError if a connection tracked against a
        # node doesn't actually list that node as source or destination.
        source = make_tank("Source")
        dest = make_tank("Dest")
        other = make_tank("Other")
        pipe = make_pipe("Pipe1", source, dest)

        converter.translate_connection(pipe)
        converter.node_to_conn_ids.setdefault("Other", []).append("Pipe1")

        with pytest.raises(ValueError):
            converter.translate_node(other)


# ---------------------------------------------------------------------------
# translate_network (integration of the pieces above)
# ---------------------------------------------------------------------------


class TestTranslateNetwork:
    """Tests for `PyPES2WaTr.translate_network`."""

    def test_translates_nodes_connections_and_tags(self, converter, ns):
        """A flat network's nodes, connections, and tags should all be translated."""
        tank1 = make_tank("Tank1")
        tank2 = make_tank(
            "Tank2",
            tags={
                "LevelTag": make_tag(
                    "LevelTag", TagType.Level, units=parse_units("gal/min"), parent_id="Tank2"
                )
            },
        )
        pipe = make_pipe("Pipe1", tank1, tank2)

        network = Network(
            "World",
            ContentsType.Brine,
            ContentsType.Brine,
            nodes={"Tank1": tank1, "Tank2": tank2},
            connections={"Pipe1": pipe},
        )
        converter.world = network
        converter.translate_network(network)

        assert set(converter.node_dict) == {"Tank1", "Tank2"}
        assert set(converter.conn_dict) == {"Pipe1"}
        assert "LevelTag" in converter.property_dict

    def test_recurses_into_nested_network_and_adds_it_as_a_node(self, converter, ns):
        """A nested Network's children should be translated, and the nested
        Network itself should also be translated as a node of its parent."""
        inner_tank = make_tank("InnerTank")
        sub_network = Network(
            "SubNet",
            ContentsType.Brine,
            ContentsType.Brine,
            nodes={"InnerTank": inner_tank},
            connections={},
        )
        outer_tank = make_tank("OuterTank")
        world = Network(
            "World",
            ContentsType.Brine,
            ContentsType.Brine,
            nodes={"OuterTank": outer_tank, "SubNet": sub_network},
            connections={},
        )
        converter.world = world
        converter.translate_network(world)

        # the nested Network's children are translated...
        assert "InnerTank" in converter.node_dict
        # ...and the sub-network itself is translated as a node of its parent,
        # since converter.world.id ("World") != sub_network.id ("SubNet").
        assert "SubNet" in converter.node_dict

        local = ns["test"]
        rec = ns["rec"]
        graph = converter.model.graph
        assert (local["SubNet"], RDF.type, rec["Region"]) in graph


# ---------------------------------------------------------------------------
# to_graph / export_ttl
# ---------------------------------------------------------------------------


class TestToGraphAndExport:
    """Tests for `PyPES2WaTr.to_graph` and `PyPES2WaTr.export_ttl`."""

    def test_to_graph_is_idempotent(self, converter):
        """Calling to_graph() twice should not re-run the translation."""
        tank = make_tank("Tank1")
        converter.world = Network(
            "World", ContentsType.Brine, ContentsType.Brine, nodes={"Tank1": tank}, connections={}
        )

        graph1 = converter.to_graph()
        triple_count = len(graph1)
        graph2 = converter.to_graph()

        assert converter._translated is True
        assert graph1 is graph2
        assert len(graph2) == triple_count

    def test_export_ttl_writes_valid_turtle(self, converter, tmp_path):
        """export_ttl() should write a file that reparses to the same graph."""
        tank = make_tank("Tank1", elevation=3.0)
        converter.world = Network(
            "World", ContentsType.Brine, ContentsType.Brine, nodes={"Tank1": tank}, connections={}
        )
        outpath = tmp_path / "out.ttl"

        converter.export_ttl(str(outpath))

        assert outpath.exists()
        from rdflib import Graph

        reparsed = Graph().parse(str(outpath), format="turtle")
        assert len(reparsed) == len(converter.model.graph)
