"""Unit tests for watr_codec.pypes_to_watr.PyPES2WaTr.

These tests exercise the individual translation helpers in isolation using
small, real pype_schema objects rather than a full facility, so that each
piece of translation logic (unit conversion, media and roles, sensors,
networks, attribute skipping, etc.) can be verified on its own. The
end-to-end tests that exercise the full desalination.json pipeline live in
test_pypes_to_watr_e2e.py.
"""

import json
import os
import warnings

import pytest
from rdflib import Graph, Namespace
from rdflib.namespace import RDF, RDFS

import plumb.brick as brick
import plumb.watr as watr
import pype_schema.connection as pypes_connection
import pype_schema.node as pypes_node
from pype_schema.connection import Connection, Pipe, Wire
from pype_schema.node import Battery, Digestion, Junction, Network, Node, Pump, Tank
from pype_schema.tag import Tag, TagType
from pype_schema.units import u
from pype_schema.utils import ContentsType, DigesterType, PumpType, parse_quantity, parse_units

from watr_codec.pypes_to_watr import WATR_CODEC_DIR, NotImplementedWarning, PyPES2WaTr, UnitConversionWarning

LOCAL = Namespace("urn:ex/")
S223 = Namespace("http://data.ashrae.org/standard223#")
WATR = Namespace("https://watermetadata.org/ontology/watr#")
QUDT = Namespace("http://qudt.org/schema/qudt/")
QK = Namespace("http://qudt.org/vocab/quantitykind/")
UNIT = Namespace("http://qudt.org/vocab/unit/")
REC = Namespace("https://w3id.org/rec#")
BRICK = Namespace("https://brickschema.org/schema/Brick#")

with open(os.path.join(WATR_CODEC_DIR, "data", "pypes_watr_mapping.json"), encoding="utf-8") as file:
    MAPPING = json.load(file)["PyPES2WaTr"]

# Every non-placeholder node and connection entry. PRV is mapped to the 223P
# class it should be, which plumb does not have yet; the strict xfail flags
# this test as soon as plumb adds it.
MAPPED_CLASSES = [
    pytest.param(
        section,
        key,
        marks=pytest.mark.xfail(strict=True, reason="plumb has no PressureReducingValve class") if key == "PRV" else (),
    )
    for section in ("nodes", "connections")
    for key, data in MAPPING[section].items()
    if data
]


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
        diameter=u.Quantity(2.0, "inch"),
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


def make_pump(id_="Pump1"):
    """Build a real brine `Pump` with no flow or power data."""
    return Pump(
        id_,
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


def translated(converter, *nodes, connections=(), tags=()):
    """Translate nodes, then connections, then tags, and return the resolved graph."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", NotImplementedWarning)
        for node in nodes:
            converter.translate_node(node)
        for conn in connections:
            converter.translate_connection(conn)
        for tag in tags:
            converter.translate_tag(tag)
    return converter.model.graph()


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

    def test_rpm_maps_to_qudt_revolutions_per_minute(self, converter):
        """RPM should map to QUDT's `unit:REV-PER-MIN`."""
        assert converter.convert_units(parse_units("RPM"))["name"] == "REV-PER-MIN"

    def test_unitless_returns_empty_dict(self, converter):
        """A unitless value (units is None) has nothing to look up, so returns {}."""
        assert converter.convert_units(None) == {}

    def test_unit_without_qudt_equivalent_names_conversion_target(self, converter):
        """MGD has no QUDT unit, so its entry names a unit to convert to instead."""
        assert converter.convert_units(parse_units("MGD")) == {"convert_to": "meter ** 3 / day"}

    def test_therm_maps_to_qudt_ec_therm(self, converter):
        """Pint's `therm` is the EC therm, which QUDT calls `unit:THM_EEC`."""
        assert converter.convert_units(parse_units("therm"))["name"] == "THM_EEC"

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
        assert "role" not in medium_dict

    def test_contents_with_role(self, converter):
        """Contents with an associated role should include it."""
        assert converter.convert_contents(ContentsType.ProductWater)["role"] == "Role-Permeate"

    def test_sludge_contents_map_to_watr_sludge(self, converter):
        """Sludge contents should map to WaTr's sludge medium."""
        for contents in (ContentsType.PrimarySludge, ContentsType.WasteActivatedSludge, ContentsType.ThickenedSludgeBlend):
            assert converter.convert_contents(contents)["name"] == "Fluid-Sludge"

    def test_seawater_maps_to_watr_seawater(self, converter):
        """Seawater should map to WaTr's seawater medium."""
        assert converter.convert_contents(ContentsType.Seawater)["name"] == "Water-Seawater"


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

    def test_speed_in_rpm_is_rotational_velocity(self, converter):
        """In PyPES, Speed in RPM is a rotational speed."""
        prop_data, _ = converter.convert_tag_type(TagType.Speed, parse_units("RPM"))
        assert prop_data["name"] == "RotationalVelocity"

    def test_speed_in_meters_per_second_is_speed(self, converter):
        """In PyPES, Speed in m/s is a velocity."""
        prop_data, _ = converter.convert_tag_type(TagType.Speed, parse_units("m/s"))
        assert prop_data["name"] == "Speed"

    def test_rotation_in_hertz_is_rotational_frequency(self, converter):
        """In PyPES, Rotation in Hz is a rotational frequency."""
        prop_data, _ = converter.convert_tag_type(TagType.Rotation, parse_units("Hz"))
        assert prop_data["name"] == "RotationalFrequency"

    def test_unmapped_tag_type_raises_key_error(self, converter):
        """A tag type mapped to an empty placeholder should raise KeyError.

        COD is listed in the mapping but only as an empty placeholder ({}),
        so looking up its "kind" key fails. COD, BOD, InFlow, OutFlow, NetFlow
        and SetPoint are all still placeholders.
        """
        with pytest.raises(KeyError):
            converter.convert_tag_type(TagType.COD)

    def test_unknown_kind_raises_value_error(self, converter):
        """A mapping entry whose kind is misspelled should raise ValueError
        rather than silently being treated as an enumeration kind."""
        converter.mapping["PyPES2WaTr"]["tag_types"]["Flow"]["kind"] = "QuantKind"
        with pytest.raises(ValueError):
            converter.convert_tag_type(TagType.Flow)


# --------- plumb class lookup ---------
class TestClassLookup:
    """Tests for `PyPES2WaTr._class`."""

    def test_rec_classes_come_from_plumb_brick(self, converter):
        """Network maps to rec:Region, which plumb provides through Brick."""
        assert converter._class(converter.mapping["PyPES2WaTr"]["nodes"]["Network"]) is brick.Region

    def test_s223_classes_come_from_plumb_watr(self, converter):
        """223P classes come from plumb's WaTr package, whose copies work with WaTr equipment."""
        assert converter._class(converter.mapping["PyPES2WaTr"]["connections"]["Pipe"]) is watr.Pipe

    def test_class_plumb_lacks_raises_key_error(self, converter):
        """A mapped class plumb has no class for should raise a clear KeyError."""
        with pytest.raises(KeyError, match="PressureReducingValve"):
            converter._class(converter.mapping["PyPES2WaTr"]["nodes"]["PRV"])


# --------- mapping file ---------
class TestMappingFile:
    """Tests that `pypes_watr_mapping.json` matches pype_schema and plumb."""

    def test_every_pypes_node_and_connection_class_is_mapped(self):
        """Every pype_schema node and connection class should have an entry, so a
        class renamed in pype_schema (e.g. StaticMixer to StaticMixing) is caught."""
        node_classes = {
            cls.__name__ for cls in vars(pypes_node).values()
            if isinstance(cls, type) and issubclass(cls, Node) and cls is not Node
        }
        connection_classes = {
            cls.__name__ for cls in vars(pypes_connection).values()
            if isinstance(cls, type) and issubclass(cls, Connection) and cls is not Connection
        }
        assert node_classes - set(MAPPING["nodes"]) == set()
        assert connection_classes - set(MAPPING["connections"]) == set()

    @pytest.mark.parametrize("section, key", MAPPED_CLASSES)
    def test_mapped_class_and_process_exist_in_plumb(self, converter, section, key):
        """Every class (and process) in the mapping file should be one plumb has."""
        data = MAPPING[section][key]
        converter._class(data)
        if data.get("process"):
            assert hasattr(watr, converter._python_name(data["process"]))

    def test_mapped_enumeration_values_exist(self, converter):
        """Every medium, role, substance, digester type, and enumeration kind should
        be a WaTr or 223P value, or one of the codec's own (watr_extensions.ttl)."""
        names = [entry["name"] for entry in MAPPING["contents_types"].values()]
        names += [entry["role"] for entry in MAPPING["contents_types"].values() if entry.get("role")]
        names += [entry["name"] for entry in MAPPING["digester_types"].values()]
        for entry in [*MAPPING["tag_types"].values(), *MAPPING["attributes"].values()]:
            if entry.get("kind") == "EnumerationKind":
                names.append(entry["name"])
            if entry.get("substance"):
                names.append(entry["substance"])
        for name in names:
            converter._enum_value(name)  # raises KeyError naming any missing value

    def test_mapped_quantity_kinds_and_units_exist(self, converter):
        """Every quantity kind and unit in the mapping file should be one plumb has."""
        entries = [entry for entry in [*MAPPING["tag_types"].values(), *MAPPING["attributes"].values()] if entry]
        entries += [option for entry in entries for option in entry.get("by_dimensionality", {}).values()]
        for entry in entries:
            if entry["kind"] == "QuantityKind":
                converter._quantity_kind(entry)
        for unit_dict in MAPPING["units"].values():
            converter._unit(unit_dict)

    def test_unknown_enumeration_value_raises_key_error(self, converter):
        """A name neither plumb nor watr_extensions.ttl defines should raise a clear KeyError."""
        with pytest.raises(KeyError, match="Constituent-NotARealSubstance"):
            converter._enum_value("Constituent-NotARealSubstance")


# --------- translate_attribute ---------
class TestTranslateAttribute:
    """Tests for `PyPES2WaTr.translate_attribute`."""

    def test_plain_dimensionless_value_is_unitless(self, converter, source_tank, dest_tank, pipe):
        """A friction coefficient is dimensionless, so its plain number gets unit:UNITLESS."""
        graph = translated(converter, source_tank, dest_tank, connections=[pipe])
        term = LOCAL["Pipe1friction_coeff"]

        assert (term, RDF.type, S223["QuantifiableProperty"]) in graph
        assert (term, QUDT["hasQuantityKind"], QK["FrictionCoefficient"]) in graph
        assert (term, QUDT["hasUnit"], UNIT["UNITLESS"]) in graph
        assert [o.toPython() for o in graph.objects(term, S223["hasValue"])] == [0.5]

    def test_plain_dimensional_value_raises_value_error(self, converter):
        """An elevation without units is incomplete, since 223P requires a unit."""
        tank = Tank("Tank1", ContentsType.Brine, ContentsType.Brine, elevation=12.5, volume=None)
        with pytest.raises(ValueError, match="Tank1elevation.*needs a unit"):
            converter.translate_node(tank)

    def test_units_of_the_wrong_dimensions_raise_plumbs_error(self, converter):
        """An elevation in a flow unit should raise plumb's own error, not one
        claiming the value has no units."""
        tank = Tank(
            "Tank1", ContentsType.Brine, ContentsType.Brine, elevation=u.Quantity(5.0, "gallon / minute"), volume=None
        )
        with pytest.raises(ValueError, match="Tank1elevation.*incompatible"):
            converter.translate_node(tank)

    def test_units_pype_schema_attaches_are_mapped(self, converter, source_tank, dest_tank, pipe):
        """pype_schema reads diameters in inches and volumes in cubic meters."""
        tank = Tank("Tank1", ContentsType.Brine, ContentsType.Brine, elevation=None, volume=parse_quantity(5.0, "m3"))
        graph = translated(converter, tank, source_tank, dest_tank, connections=[pipe])

        assert (LOCAL["Pipe1diameter"], QUDT["hasUnit"], UNIT["IN"]) in graph
        assert (LOCAL["Tank1volume"], QUDT["hasUnit"], UNIT["M3"]) in graph

    def test_pint_value_extracts_magnitude_and_unit(self, converter):
        """A Pint quantity should have its magnitude and unit split apart."""
        tank = Tank("Tank1", ContentsType.Brine, ContentsType.Brine, elevation=u.Quantity(3.0, "meter"), volume=None)
        graph = translated(converter, tank)
        term = LOCAL["Tank1elevation"]

        assert [o.toPython() for o in graph.objects(term, S223["hasValue"])] == [3.0]
        assert (term, QUDT["hasUnit"], UNIT["M"]) in graph

    def test_none_value_creates_no_property(self, converter):
        """An attribute without data should not be added to the graph at all."""
        tank = Tank("Tank1", ContentsType.Brine, ContentsType.Brine, elevation=u.Quantity(3.0, "meter"), volume=None)
        graph = translated(converter, tank)
        term = LOCAL["Tank1volume"]

        assert "Tank1volume" not in converter.properties
        assert not list(graph.triples((term, None, None)))
        assert not list(graph.triples((None, None, term)))

    def test_connection_attributes_are_properties_of_the_pipe(self, converter, source_tank, dest_tank, pipe):
        """A connection's attributes should be properties of the resolved pipe."""
        graph = translated(converter, source_tank, dest_tank, connections=[pipe])

        assert (LOCAL["Pipe1"], S223["hasProperty"], LOCAL["Pipe1diameter"]) in graph
        assert (LOCAL["Pipe1"], S223["hasProperty"], LOCAL["Pipe1friction_coeff"]) in graph


# --------- translate_tag ---------
class TestTranslateTag:
    """Tests for `PyPES2WaTr.translate_tag`."""

    def test_flow_tag_becomes_a_flow_sensor_on_its_pipe(self, converter, source_tank, dest_tank, pipe):
        """A flow tag on a pipe should be a flow sensor observing a flow-rate property."""
        tag = Tag("FlowTag", parse_units("gal/min"), TagType.Flow, 1, 2, "Pipe1", contents=ContentsType.Brine)
        graph = translated(converter, source_tank, dest_tank, connections=[pipe], tags=[tag])
        sensor, value = LOCAL["FlowTag"], LOCAL["FlowTag-value"]

        assert (sensor, RDF.type, WATR["FlowSensor"]) in graph
        assert (sensor, S223["hasObservationLocation"], LOCAL["Pipe1"]) in graph
        assert (sensor, S223["observes"], value) in graph
        assert (value, RDF.type, S223["QuantifiableObservableProperty"]) in graph
        assert (value, QUDT["hasQuantityKind"], QK["VolumeFlowRate"]) in graph
        assert (value, QUDT["hasUnit"], UNIT["GAL_US-PER-MIN"]) in graph
        assert (value, S223["ofMedium"], WATR["Water-Brine"]) in graph

    def test_tss_tag_adds_suspended_solids_substance(self, converter):
        """A TSS tag should be a concentration of suspended solids."""
        tank = Tank("Tank1", ContentsType.Brine, ContentsType.Brine, elevation=None, volume=None)
        tag = Tag("TSSTag", parse_units("mg/L"), TagType.TSS, "total", "total", "Tank1", contents=ContentsType.Brine)
        graph = translated(converter, tank, tags=[tag])

        assert (LOCAL["TSSTag-value"], S223["ofSubstance"], WATR["Constituent-SuspendedSolids"]) in graph

    def test_tds_tag_adds_dissolved_solids_substance(self, converter):
        """A TDS tag should be a concentration of dissolved solids."""
        tank = Tank("Tank1", ContentsType.Brine, ContentsType.Brine, elevation=None, volume=None)
        tag = Tag("TDSTag", parse_units("mg/L"), TagType.TDS, "total", "total", "Tank1", contents=ContentsType.Brine)
        graph = translated(converter, tank, tags=[tag])
        value = LOCAL["TDSTag-value"]

        assert (value, QUDT["hasQuantityKind"], QK["MassConcentration"]) in graph
        assert (value, S223["ofSubstance"], WATR["Constituent-DissolvedSolids"]) in graph

    def test_vss_tag_adds_volatile_suspended_solids_substance(self, converter):
        """VSS are solids that are both organic and suspended, so the codec's own
        WaTr term for them (watr_extensions.ttl) is a subclass of both, and its
        definition is added to the graph."""
        tank = Tank("Tank1", ContentsType.Brine, ContentsType.Brine, elevation=None, volume=None)
        tag = Tag("VSSTag", parse_units("mg/L"), TagType.VSS, "total", "total", "Tank1", contents=ContentsType.Brine)
        translated(converter, tank, tags=[tag])
        graph = converter.to_graph()
        vss = WATR["Constituent-VolatileSuspendedSolids"]

        assert (LOCAL["VSSTag-value"], S223["ofSubstance"], vss) in graph
        assert set(graph.objects(vss, RDFS.subClassOf)) == {
            WATR["Constituent-OrganicSolids"],
            WATR["Constituent-SuspendedSolids"],
        }

    def test_unused_codec_terms_are_not_added_to_the_graph(self, converter):
        """The codec's own WaTr terms should only be defined in graphs that use them."""
        tank = Tank("Tank1", ContentsType.Brine, ContentsType.Brine, elevation=None, volume=None)
        tag = Tag("TSSTag", parse_units("mg/L"), TagType.TSS, "total", "total", "Tank1", contents=ContentsType.Brine)
        translated(converter, tank, tags=[tag])
        graph = converter.to_graph()

        assert not list(graph.triples((WATR["Constituent-VolatileSuspendedSolids"], None, None)))

    def test_rotational_speed_tag(self, converter):
        """A Speed tag in RPM should observe a rotational velocity."""
        tag = Tag("PumpSpeed", parse_units("RPM"), TagType.Speed, "total", "total", "Pump1", contents=ContentsType.Brine)
        graph = translated(converter, make_pump(), tags=[tag])
        value = LOCAL["PumpSpeed-value"]

        assert (value, QUDT["hasQuantityKind"], QK["RotationalVelocity"]) in graph
        assert (value, QUDT["hasUnit"], UNIT["REV-PER-MIN"]) in graph

    def test_status_tag_uses_enumeration_kind(self, converter, run_status_tag):
        """A RunStatus tag should observe an enumerated property of kind Binary-OnOff."""
        graph = translated(converter, make_pump(), tags=[run_status_tag])
        value = LOCAL["PumpStatus-value"]

        assert (value, RDF.type, S223["EnumeratedObservableProperty"]) in graph
        assert (value, S223["hasEnumerationKind"], S223["Binary-OnOff"]) in graph
        assert not list(graph.objects(value, QUDT["hasQuantityKind"]))

    def test_unitless_contentless_tag_has_no_unit_or_medium(self, converter, run_status_tag):
        """A RunStatus tag has neither units nor contents, so neither appears."""
        graph = translated(converter, make_pump(), tags=[run_status_tag])
        value = LOCAL["PumpStatus-value"]

        assert not list(graph.objects(value, QUDT["hasUnit"]))
        assert not list(graph.objects(value, S223["ofMedium"]))

    def test_missing_contents_on_non_contentless_tag_raises_value_error(self, converter):
        """A Flow tag must have contents in PyPES, so omitting them is an error."""
        tag = Tag("FlowTag", parse_units("gal/min"), TagType.Flow, "total", "total", "Pump1", contents=None)
        translated(converter, make_pump())
        with pytest.raises(ValueError):
            converter.translate_tag(tag)

    def test_mgd_flow_tag_is_a_flow_sensor_without_a_unit(self, converter, source_tank, dest_tank, pipe):
        """An MGD tag's data can't be converted by the codec, so it warns and gets
        no unit, but it is still a flow sensor on its pipe."""
        tag = Tag("PlantFlow", parse_units("MGD"), TagType.Flow, "total", "total", "Pipe1", contents=ContentsType.Brine)
        translated(converter, source_tank, dest_tank, connections=[pipe])
        with pytest.warns(UnitConversionWarning, match="PlantFlow"):
            converter.translate_tag(tag)

        graph = converter.model.graph()
        sensor, value = LOCAL["PlantFlow"], LOCAL["PlantFlow-value"]
        assert (sensor, RDF.type, WATR["FlowSensor"]) in graph
        assert (sensor, S223["hasObservationLocation"], LOCAL["Pipe1"]) in graph
        assert (sensor, S223["observes"], value) in graph
        assert (value, QUDT["hasQuantityKind"], QK["VolumeFlowRate"]) in graph
        assert (value, S223["ofMedium"], WATR["Water-Brine"]) in graph
        assert not list(graph.objects(value, QUDT["hasUnit"]))


# --------- translate_node ---------
class TestTranslateNode:
    """Tests for `PyPES2WaTr.translate_node`."""

    def test_translates_type(self, converter, source_tank):
        """A node should become equipment of its mapped WaTr class."""
        graph = translated(converter, source_tank)
        assert (LOCAL["Source"], RDF.type, WATR["Tank"]) in graph

    def test_not_yet_implemented_attribute_warns_and_is_skipped(self, converter):
        """A not-yet-implemented attribute should warn and not be translated."""
        with pytest.warns(NotImplementedWarning, match="pump_type"):
            converter.translate_node(make_pump())

        assert "Pump1pump_type" not in converter.properties
        assert not list(converter.model.graph().triples((LOCAL["Pump1pump_type"], None, None)))

    def test_digester_gets_process_and_digester_type_role(self, converter):
        """A digester should have its process and its type as a WaTr role."""
        digester = Digestion(
            "Digester1",
            ContentsType.ThickenedSludgeBlend,
            ContentsType.SludgeBlend,
            min_flow=None,
            max_flow=None,
            design_flow=None,
            num_units=1,
            volume=None,
            digester_type=DigesterType.Anaerobic,
        )
        with warnings.catch_warnings():
            warnings.simplefilter("error", NotImplementedWarning)
            converter.translate_node(digester)

        graph = converter.model.graph()
        assert (LOCAL["Digester1"], WATR["hasProcess"], WATR["Process-Digestion"]) in graph
        assert (LOCAL["Digester1"], S223["hasRole"], WATR["Role-Anaerobic"]) in graph

    def test_digester_of_unknown_type_gets_no_role(self, converter):
        """PyPES allows a digester with no digester_type, which should get no role."""
        digester = Digestion(
            "Digester1",
            ContentsType.ThickenedSludgeBlend,
            ContentsType.SludgeBlend,
            min_flow=None,
            max_flow=None,
            design_flow=None,
            num_units=1,
            volume=None,
            digester_type=None,
        )
        graph = translated(converter, digester)

        assert (LOCAL["Digester1"], WATR["hasProcess"], WATR["Process-Digestion"]) in graph
        assert not list(graph.objects(LOCAL["Digester1"], S223["hasRole"]))


# --------- translate_connection ---------
class TestTranslateConnection:
    """Tests for `PyPES2WaTr.translate_connection`."""

    def test_translates_type_medium_and_points(self, converter, source_tank, dest_tank, pipe):
        """A connection should be a pipe joining a named outlet and inlet point."""
        graph = translated(converter, source_tank, dest_tank, connections=[pipe])

        assert (LOCAL["Pipe1"], RDF.type, S223["Pipe"]) in graph
        assert (LOCAL["Pipe1"], S223["hasMedium"], WATR["Water-Brine"]) in graph
        assert (LOCAL["Pipe1-out"], RDF.type, S223["OutletConnectionPoint"]) in graph
        assert (LOCAL["Pipe1-in"], RDF.type, S223["InletConnectionPoint"]) in graph
        assert (LOCAL["Pipe1-out"], S223["isConnectionPointOf"], LOCAL["Source"]) in graph
        assert (LOCAL["Pipe1-in"], S223["isConnectionPointOf"], LOCAL["Dest"]) in graph

    def test_contents_role_is_added_to_the_pipe(self, converter, source_tank, dest_tank):
        """ProductWater carries the permeate role, which should be on the pipe."""
        permeate_pipe = Pipe("Pipe1", ContentsType.ProductWater, source_tank, dest_tank, None, None, None)
        graph = translated(converter, source_tank, dest_tank, connections=[permeate_pipe])

        assert (LOCAL["Pipe1"], S223["hasMedium"], S223["Fluid-Water"]) in graph
        assert (LOCAL["Pipe1"], S223["hasRole"], WATR["Role-Permeate"]) in graph

    def test_wire_is_an_electrical_conductor(self, converter):
        """A PyPES Wire carries electricity, which 223P models as a Conductor."""
        battery = Battery("Battery1", energy_capacity=None, charge_rate=None, discharge_rate=None, rte=None, leakage=None)
        pump = make_pump()
        wire = Wire("Wire1", ContentsType.Electricity, battery, pump)
        graph = translated(converter, battery, pump, connections=[wire])

        assert (LOCAL["Wire1"], RDF.type, S223["Conductor"]) in graph
        assert (LOCAL["Wire1"], S223["hasMedium"], S223["Constituent-Electricity"]) in graph
        assert (LOCAL["Wire1-out"], S223["isConnectionPointOf"], LOCAL["Battery1"]) in graph
        assert (LOCAL["Wire1-in"], S223["isConnectionPointOf"], LOCAL["Pump1"]) in graph

    def test_not_yet_implemented_attributes_warn_only_with_data(self, converter, source_tank, dest_tank, pipe):
        """bidirectional (False) has data, so it should warn, but heating_values
        of (None, None) has none, so it should not."""
        translated(converter, source_tank, dest_tank)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            converter.translate_connection(pipe)

        messages = [str(w.message) for w in caught if issubclass(w.category, NotImplementedWarning)]
        assert any("bidirectional" in m for m in messages)
        assert not any("heating_values" in m for m in messages)

    def test_node_in_several_connections_gets_a_point_for_each(self, converter, source_tank, dest_tank, pipe):
        """A node that is the source of two pipes should get two outlet points."""
        other_tank = Tank("Other", ContentsType.Brine, ContentsType.Brine, elevation=None, volume=None)
        second_pipe = Pipe("Pipe2", ContentsType.Brine, source_tank, other_tank, None, None, None)
        graph = translated(converter, source_tank, dest_tank, other_tank, connections=[pipe, second_pipe])

        points = set(graph.objects(LOCAL["Source"], S223["hasConnectionPoint"]))
        assert {LOCAL["Pipe1-out"], LOCAL["Pipe2-out"]} <= points

    def test_junction_direction_comes_from_the_connection(self, converter, source_tank, dest_tank):
        """A junction's points face the way the PyPES connections flow."""
        junction = Junction("Middle", ContentsType.Brine, ContentsType.Brine)
        inbound = Pipe("InPipe", ContentsType.Brine, source_tank, junction, None, None, None)
        outbound = Pipe("OutPipe", ContentsType.Brine, junction, dest_tank, None, None, None)
        graph = translated(converter, source_tank, junction, dest_tank, connections=[inbound, outbound])

        assert (LOCAL["InPipe-in"], S223["isConnectionPointOf"], LOCAL["Middle"]) in graph
        assert (LOCAL["OutPipe-out"], S223["isConnectionPointOf"], LOCAL["Middle"]) in graph


# --------- translate_network ---------
class TestTranslateNetwork:
    """Tests for `PyPES2WaTr.translate_network`."""

    def test_translates_nodes_connections_and_tags(self, converter, source_tank):
        """A flat network's nodes, connections, and tags should all be translated."""
        level_tag = Tag("LevelTag", parse_units("meter"), TagType.Level, "total", "total", "Tank2", contents=ContentsType.Brine)
        tank2 = Tank("Tank2", ContentsType.Brine, ContentsType.Brine, elevation=None, volume=None, tags={"LevelTag": level_tag})
        pipe = Pipe("Pipe1", ContentsType.Brine, source_tank, tank2, None, None, None)
        converter.world = Network(
            "World", ContentsType.Brine, ContentsType.Brine,
            nodes={"Source": source_tank, "Tank2": tank2}, connections={"Pipe1": pipe},
        )
        converter.to_graph()

        assert set(converter.entities) == {"Source", "Tank2"}
        assert set(converter.connections) == {"Pipe1"}
        assert set(converter.sensors) == {"LevelTag"}

    def test_nested_network_is_a_rec_region_located_around_its_nodes(self, converter, source_tank):
        """A nested network should be a rec:Region that is the location of its nodes,
        and a pipe into it should attach to its entry point."""
        pump = make_pump()
        sub_network = Network("SubNet", ContentsType.Brine, ContentsType.Brine, nodes={"Pump1": pump}, connections={})
        inbound = Pipe("InPipe", ContentsType.Brine, source_tank, sub_network, None, None, None, entry_point=pump)
        converter.world = Network(
            "World", ContentsType.Brine, ContentsType.Brine,
            nodes={"Source": source_tank, "SubNet": sub_network}, connections={"InPipe": inbound},
        )
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", NotImplementedWarning)
            graph = converter.to_graph()

        assert (LOCAL["SubNet"], RDF.type, REC["Region"]) in graph
        assert (LOCAL["SubNet"], BRICK["isLocationOf"], LOCAL["Pump1"]) in graph
        assert (LOCAL["InPipe-in"], S223["isConnectionPointOf"], LOCAL["Pump1"]) in graph

    def test_connection_to_network_without_entry_point_raises_value_error(self, converter, source_tank):
        """rec spaces can't be connected, so a pipe into a network must name its entry point."""
        sub_network = Network("SubNet", ContentsType.Brine, ContentsType.Brine, nodes={"Pump1": make_pump()}, connections={})
        inbound = Pipe("InPipe", ContentsType.Brine, source_tank, sub_network, None, None, None)
        converter.world = Network(
            "World", ContentsType.Brine, ContentsType.Brine,
            nodes={"Source": source_tank, "SubNet": sub_network}, connections={"InPipe": inbound},
        )
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", NotImplementedWarning)
            with pytest.raises(ValueError, match="entry_point"):
                converter.to_graph()


# --------- to_graph / validate / export_ttl ---------
class TestToGraphValidateAndExport:
    """Tests for `PyPES2WaTr.to_graph`, `validate`, and `export_ttl`."""

    @pytest.fixture
    def small_world(self, source_tank, dest_tank, pipe):
        """A two-tank network joined by one pipe."""
        return Network(
            "World", ContentsType.Brine, ContentsType.Brine,
            nodes={"Source": source_tank, "Dest": dest_tank}, connections={"Pipe1": pipe},
        )

    def test_to_graph_is_idempotent(self, converter, small_world):
        """Calling to_graph() twice should not re-run the translation."""
        converter.world = small_world
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", NotImplementedWarning)
            graph1 = converter.to_graph()
        triple_count = len(graph1)
        graph2 = converter.to_graph()

        assert graph1 is graph2
        assert len(graph2) == triple_count

    def test_validate_conforms(self, converter, small_world):
        """The translated model should conform to the WaTr and 223P shapes."""
        converter.world = small_world
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", NotImplementedWarning)
            report = converter.validate()
        assert report, str(report)

    def test_validate_recognizes_the_codecs_own_watr_terms(self, converter, dest_tank):
        """A VSS tag uses the codec's own WaTr term, which should validate like
        the WaTr ontology's terms."""
        vss_tag = Tag("VSSTag", parse_units("mg/L"), TagType.VSS, "total", "total", "Source", contents=ContentsType.Brine)
        source = Tank(
            "Source", ContentsType.Brine, ContentsType.Brine, elevation=None, volume=None, tags={"VSSTag": vss_tag}
        )
        pipe = Pipe("Pipe1", ContentsType.Brine, source, dest_tank, None, None, None)
        converter.world = Network(
            "World", ContentsType.Brine, ContentsType.Brine,
            nodes={"Source": source, "Dest": dest_tank}, connections={"Pipe1": pipe},
        )
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", NotImplementedWarning)
            report = converter.validate()
        assert report, str(report)

    def test_export_ttl_writes_valid_turtle(self, converter, small_world, tmp_path):
        """export_ttl() should write a file that reparses to the same graph."""
        converter.world = small_world
        outpath = tmp_path / "out.ttl"
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", NotImplementedWarning)
            converter.export_ttl(str(outpath))

        reparsed = Graph().parse(str(outpath), format="turtle")
        assert len(reparsed) == len(converter.to_graph())
