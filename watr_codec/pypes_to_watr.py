import inspect
import json
import os
import warnings

import pint
import plumb.brick as brick
import plumb.watr as watr
from plumb import EnumValue, Model, connect
# plumb has no public way to validate against extra ontology terms (see `validate`)
from plumb.core.validation import _package_shapes
from plumb.qudt import quantity_kinds, units
from plumb.watr import enums
from pype_schema import connection, utils
from pype_schema.node import Network, Node
from pype_schema.tag import CONTENTLESS_TYPES, Tag, TagType, VirtualTag
from rdflib import RDF, RDFS, Graph, URIRef


# add this file path to dir so that data folder is always accessible
WATR_CODEC_DIR = os.path.dirname(os.path.abspath(__file__))
MAPPING_PATH = os.path.join(WATR_CODEC_DIR, "data", "pypes_watr_mapping.json")

# WaTr terms the codec defines itself until the WaTr ontology does
EXTENSIONS_PATH = os.path.join(WATR_CODEC_DIR, "data", "watr_extensions.ttl")
WATR_CLASS = URIRef(watr.ONTOLOGY.iri + "#Class")

# IRI prefix for the facility's own terms, unless the caller gives another
DEFAULT_NAMESPACE = "urn:ex/"
TURTLE_FORMAT = "turtle"
FILE_ENCODING = "utf-8"

# strings are stored as global variables to avoid hardcoding
# keys of the PyPES2WaTr mapping file (`pypes_watr_mapping.json`)
TOP_LEVEL_KEY = "PyPES2WaTr"
NODES_KEY = "nodes"
CONNECTIONS_KEY = "connections"
TAG_TYPES_KEY = "tag_types"
ATTRIBUTES_KEY = "attributes"
CONTENTS_TYPES_KEY = "contents_types"
UNITS_KEY = "units"
PROCESS_KEY = "process"
DIGESTER_TYPES_KEY = "digester_types"
CONVERT_TO_KEY = "convert_to"
BY_DIMENSIONALITY_KEY = "by_dimensionality"
NAME_KEY = "name"
URI_KEY = "uri"
KIND_KEY = "kind"
ROLE_KEY = "role"
SUBSTANCE_KEY = "substance"

# allowed values of the mapping file's `kind` key
QUANT_KIND_STR = "QuantityKind"
ENUM_KIND_STR = "EnumerationKind"

# namespace prefixes used in the mapping file's `uri` keys
REC_URI = "rec"

# PyPES attributes starting with this are internal, so they are not translated
PRIVATE_ATTR_PREFIX = "_"

# PyPES attributes with custom translation logic
DIGESTER_TYPE_ATTR = "digester_type"
# the child node a connection to a network leaves (exit) or enters (entry)
EXIT_POINT_ATTR = "exit_point"
ENTRY_POINT_ATTR = "entry_point"

# connection points are named after the connection that uses them
OUTLET_SUFFIX = "-out"
INLET_SUFFIX = "-in"
# plumb's directions for outlet and inlet connection points
OUTLET_DIRECTION = "out"
INLET_DIRECTION = "in"
# plumb names the property a sensor observes `<sensor name>-value`
SENSOR_VALUE_SUFFIX = "-value"
# plumb's parameters for what some classes need when created: the medium of
# e.g. a Junction, and the processes of e.g. a Reactor
MEDIUM_PARAM = "medium"
HAS_PROCESS_PARAM = "has_process"

# These attributes are handled by custom logic and not automatically
CUSTOM_HANDLED_ATTRIBUTES = [
    "nodes",
    "connections",
    "contents",
    "input_contents",
    "output_contents",
    "tags",
    "num_units",
    "id",
    "source",
    "destination",
    EXIT_POINT_ATTR,
    ENTRY_POINT_ATTR,
]

# TODO: implement conversion of the below attributes
NOT_YET_IMPLEMENTED_ATTRIBUTES = [
    "heating_values",
    "pressure",
    "flow_rate",
    "bidirectional",
    "pump_type",
    "pump_curve",
    "area",
    "selectivity",
    "settling_time",
]


# Define a custom warning category
class NotImplementedWarning(UserWarning):
    """Warning category raised when a PyPES attribute has no WaTr translation yet.

    Used instead of a generic ``UserWarning`` so callers can filter or assert
    on exactly these "not yet implemented" notices without also catching
    unrelated warnings raised by pype_schema or other dependencies.
    """

    pass


class UnitConversionWarning(UserWarning):
    """Warning category raised when a PyPES unit has no QUDT equivalent.

    The mapping file names a unit that does have one (`convert_to`), and
    attribute values are converted to it before being added to the graph.
    """

    pass


def _load_extensions(path: str):
    """Read the codec's own WaTr terms and build a plumb enumeration value for each.

    Parameters
    ----------
    path : str
        Turtle file of WaTr enumeration kinds (see `watr_extensions.ttl`).
        Each term is a `watr:Class` whose `rdfs:subClassOf` superclasses
        are WaTr or 223P enumeration values that plumb already has.

    Returns
    -------
    graph : rdflib.Graph
        The terms' definitions.
    values : dict
        Maps each term's local name (e.g.
        `"Constituent-VolatileSuspendedSolids"`) to its plumb enumeration
        value. A value's parents are its superclasses, so plumb accepts it
        wherever any of them is allowed.
    """
    graph = Graph().parse(path, format=TURTLE_FORMAT)
    values = {}
    for term in sorted(graph.subjects(RDF.type, WATR_CLASS)):
        parents = [watr.REGISTRY.resolve_enum(str(p)) for p in sorted(graph.objects(term, RDFS.subClassOf))]
        value = EnumValue(
            str(term),
            label=str(graph.value(term, RDFS.label)),
            definition=str(graph.value(term, RDFS.comment)),
            parent=parents[0],
        )
        for parent in parents[1:]:
            value._add_parent(parent)  # plumb's only way to give a value several parents
        values[term.fragment] = value
    return graph, values


EXTENSION_GRAPH, EXTENSION_ENUMS = _load_extensions(EXTENSIONS_PATH)


class PyPES2WaTr:
    """Translates a pype_schema PyPES network into a WaTr semantic graph.

    An instance walks a `pype_schema.node.Network` (and any nodes,
    connections, and tags nested inside it) and builds the corresponding
    WaTr/223P model with plumb, using the mapping data in
    `pypes_watr_mapping.json`. plumb works out connection points, pipes, and
    sensors, and can validate the result against the WaTr and 223P SHACL
    shapes. The translation only happens once; the first call to `to_graph`
    (or `export_ttl` or `validate`) performs it and caches the result.
    """

    def __init__(
        self,
        network: Network,
        local_prefix: str,
        mapping_path=MAPPING_PATH,
        namespace: str = DEFAULT_NAMESPACE,
    ):
        """Create a translator bound to a PyPES network and mapping data.

        Parameters
        ----------
        network : pype_schema.node.Network
            The (possibly nested) PyPES facility/network to translate.
        local_prefix : str
            RDF namespace prefix bound to `namespace` when the graph is
            serialized.
        mapping_path : str, optional
            Path to the PyPES-to-WaTr JSON mapping file. Defaults to
            `data/pypes_watr_mapping.json` bundled with this package.
        namespace : str, optional
            IRI prefix that terms minted for this facility (nodes,
            connections, properties, sensors) are created under. Defaults to
            `"urn:ex/"`.
        """
        self.world = network
        self.local_prefix = local_prefix
        with open(mapping_path, "r", encoding=FILE_ENCODING) as file:
            self.mapping = json.load(file)

        self.model = Model(namespace, prefixes={local_prefix: namespace})
        self.entities = {}  # PyPES node ID -> plumb equipment or rec space
        self.connections = {}  # PyPES connection ID -> plumb connection handle
        self.properties = {}  # property ID -> plumb property
        self.sensors = {}  # tag ID -> plumb sensor
        self._graph = None

    def _sanitize_id(self, value: str) -> str:
        """Turn a PyPES ID into a string that is safe to use as an IRI suffix.

        Parameters
        ----------
        value : str
            Raw PyPES object ID, which may contain spaces.

        Returns
        -------
        str
            `value` with any spaces replaced by dashes.
        """
        return value.replace(" ", "-")

    def _python_name(self, name: str) -> str:
        """Turn an ontology local name into the attribute name plumb uses.

        Parameters
        ----------
        name : str
            Local name from the mapping file, e.g. `"Water-Brine"` or
            `"GAL_US-PER-MIN"`.

        Returns
        -------
        str
            `name` with dashes replaced by underscores, e.g. `"Water_Brine"`.
        """
        return name.replace("-", "_")

    def _has_data(self, value) -> bool:
        """Check whether a PyPES attribute value holds any data.

        Parameters
        ----------
        value : object
            Value of a node or connection attribute. Some are tuples of
            optional values, e.g. a pipe's `heating_values` of
            `(lower, higher)`.

        Returns
        -------
        bool
            False if `value` is None or a tuple whose items are all None,
            otherwise True.
        """
        if isinstance(value, tuple):
            return any(item is not None for item in value)
        return value is not None

    def _class(self, data: dict):
        """Look up the plumb class for a mapping-file `nodes`/`connections` entry.

        Parameters
        ----------
        data : dict
            Mapping-file entry with `"uri"` and `"name"` keys.

        Returns
        -------
        type
            The plumb class: RealEstateCore classes (`rec`) come from
            `plumb.brick`, and WaTr and 223P classes from `plumb.watr`, which
            carries its own copies of the 223P classes.

        Raises
        ------
        KeyError
            If plumb has no class of that name.
        """
        package = brick if data[URI_KEY] == REC_URI else watr
        try:
            return getattr(package, self._python_name(data[NAME_KEY]))
        except AttributeError:
            raise KeyError(f"plumb has no class for {data[URI_KEY]}:{data[NAME_KEY]}") from None

    def _enum(self, data: dict):
        """Look up the plumb enumeration value for a mapping-file entry.

        Parameters
        ----------
        data : dict
            Mapping-file entry whose `"name"` is a WaTr or 223P enumeration
            value, e.g. a medium (`"Water-Brine"`) or role (`"Role-Permeate"`).

        Returns
        -------
        plumb enumeration value
            See `_enum_value`.
        """
        return self._enum_value(data[NAME_KEY])

    def _enum_value(self, name: str):
        """Look up a WaTr or 223P enumeration value by its ontology name.

        Parameters
        ----------
        name : str
            Local name from the mapping file, e.g. a medium (`"Water-Brine"`),
            role (`"Role-Permeate"`), or substance
            (`"Constituent-SuspendedSolids"`).

        Returns
        -------
        plumb enumeration value
            The corresponding member of `plumb.watr.enums.values`, or else the
            codec's own term of that name from `watr_extensions.ttl`.

        Raises
        ------
        KeyError
            If neither plumb nor `watr_extensions.ttl` defines `name`.
        """
        try:
            return getattr(enums.values, self._python_name(name))
        except AttributeError:  # not in plumb, so it should be one of the codec's own terms
            if name not in EXTENSION_ENUMS:
                raise KeyError(f"Neither plumb nor watr_extensions.ttl defines {name}") from None
            return EXTENSION_ENUMS[name]

    def _quantity_kind(self, data: dict):
        """Look up the plumb QUDT quantity kind for a mapping-file entry.

        Parameters
        ----------
        data : dict
            Mapping-file entry whose `"name"` is a QUDT quantity kind.

        Returns
        -------
        plumb quantity kind
            The corresponding member of `plumb.qudt.quantity_kinds`.
        """
        return getattr(quantity_kinds, data[NAME_KEY])

    def _unit(self, unit_dict: dict):
        """Look up the plumb QUDT unit for a mapping-file `units` entry.

        Parameters
        ----------
        unit_dict : dict
            Mapping-file `units` entry, as returned by `convert_units`.

        Returns
        -------
        plumb unit or None
            The corresponding member of `plumb.qudt.units`, or None if the
            entry has no QUDT unit (unitless values, or units that need
            converting first).
        """
        name = unit_dict.get(NAME_KEY)
        return getattr(units, self._python_name(name)) if name else None

    def convert_units(self, units: pint.Unit):
        """Look up the WaTr/QUDT unit entry for a Pint unit.

        Parameters
        ----------
        units : pint.Unit or None
            Unit to translate, as used by pype_schema attributes and tags.

        Returns
        -------
        dict
            The mapping-file entry for `units`. Units with no QUDT equivalent
            (e.g. MGD) return only a `convert_to` key naming a Pint unit that
            does have one. Unitless values (`units` is None, e.g. RunStatus
            tags) return an empty dict.
        """
        if units is None:  # unitless (e.g., RunStatus tags) so nothing to look up
            return {}
        return self.mapping[TOP_LEVEL_KEY][UNITS_KEY][str(units)]

    def convert_contents(self, contents: utils.ContentsType):
        """Look up the WaTr medium entry for a PyPES contents type.

        Parameters
        ----------
        contents : pype_schema.utils.ContentsType
            PyPES contents type carried by a node, connection, or tag.

        Returns
        -------
        dict
            The mapping-file entry describing the corresponding WaTr medium
            (and, if applicable, its role).
        """
        return self.mapping[TOP_LEVEL_KEY][CONTENTS_TYPES_KEY][contents.name]

    def convert_attribute(self, attr_name: str):
        """Look up the WaTr property entry for a PyPES node/connection attribute.

        Parameters
        ----------
        attr_name : str
            Name of the PyPES attribute (e.g. `"diameter"`, `"elevation"`).

        Returns
        -------
        prop_dict : dict
            The mapping-file entry describing the corresponding WaTr
            property.
        is_quant_kind : bool
            True if the entry's `kind` is `"QuantityKind"`; False if it is
            `"EnumerationKind"`.

        Raises
        ------
        ValueError
            If the entry's `kind` is neither `"QuantityKind"` nor
            `"EnumerationKind"`.
        """
        prop_dict = self.mapping[TOP_LEVEL_KEY][ATTRIBUTES_KEY][attr_name]
        if prop_dict[KIND_KEY] not in (QUANT_KIND_STR, ENUM_KIND_STR):
            raise ValueError(f"Unknown kind {prop_dict[KIND_KEY]!r} for attribute {attr_name}")
        return prop_dict, prop_dict[KIND_KEY] == QUANT_KIND_STR

    def convert_tag_type(self, tag_type: TagType, units: pint.Unit = None):
        """Look up the WaTr property entry for a PyPES tag type.

        Parameters
        ----------
        tag_type : pype_schema.tag.TagType
            Type of the SCADA tag being translated (e.g. `TagType.Flow`).
        units : pint.Unit, optional
            The tag's units. Some tag types mean different quantities
            depending on their units (e.g. `Speed` in RPM is a rotational
            speed, but in m/s a velocity), and their mapping entry lists those
            under `by_dimensionality`.

        Returns
        -------
        prop_dict : dict
            The mapping-file entry describing the corresponding WaTr
            observable property.
        is_quant_kind : bool
            True if the entry's `kind` is `"QuantityKind"`; False if it is
            `"EnumerationKind"`.

        Raises
        ------
        ValueError
            If the entry's `kind` is neither `"QuantityKind"` nor
            `"EnumerationKind"`.
        """
        prop_dict = self.mapping[TOP_LEVEL_KEY][TAG_TYPES_KEY][tag_type.name]
        if units is not None:
            # the quantity a tag type describes can depend on its units' dimensions
            prop_dict = prop_dict.get(BY_DIMENSIONALITY_KEY, {}).get(str(units.dimensionality), prop_dict)
        if prop_dict[KIND_KEY] not in (QUANT_KIND_STR, ENUM_KIND_STR):
            raise ValueError(f"Unknown kind {prop_dict[KIND_KEY]!r} for tag type {tag_type.name}")
        return prop_dict, prop_dict[KIND_KEY] == QUANT_KIND_STR

    def _endpoint(self, node: Node, child: Node, conn_id: str, end: str):
        """Find the plumb equipment a connection actually attaches to.

        Parameters
        ----------
        node : pype_schema.node.Node
            The connection's source or destination.
        child : pype_schema.node.Node or None
            The connection's `exit_point` or `entry_point`: the child node
            it leaves or enters when `node` is a network.
        conn_id : str
            ID of the connection, for error messages.
        end : str
            `"exit_point"` or `"entry_point"`, for error messages.

        Returns
        -------
        plumb equipment
            The translated entity for `child` if given, otherwise for `node`.

        Raises
        ------
        ValueError
            If `node` is a network and `child` is not given. Networks are
            RealEstateCore spaces, which cannot have connection points.
        """
        if child is not None:
            return self.entities[child.id]
        elif isinstance(node, Network):
            raise ValueError(
                f"Connection {conn_id} attaches to network {node.id} without an {end}; "
                "networks are rec spaces and cannot be connected directly"
            )
        else:
            return self.entities[node.id]

    def translate_attribute(self, attr_name, value, parent_id, host):
        """Convert a single PyPES node/connection attribute to a WaTr property.

        Parameters
        ----------
        attr_name : str
            Name of the attribute (e.g. `"diameter"`, `"elevation"`).
        value : pint.Quantity, float, str, or None
            Value of the attribute. If it has `.units`/`.magnitude`
            attributes (i.e. it is a Pint quantity), the units are looked up
            via `convert_units` and the magnitude is used as the value. A
            plain number is only valid for dimensionless quantity kinds (e.g.
            a friction coefficient), and gets QUDT's `unit:UNITLESS`. If
            None, no property is created.
        parent_id : str
            ID of the PyPES node or connection this attribute belongs to.
        host : plumb equipment or connection handle
            The translated node or connection the property is attached to.
            The property takes the host's medium.

        Returns
        -------
        plumb property or None
            The property recorded in `self.properties` for this attribute,
            or None if `value` is None.

        Raises
        ------
        ValueError
            If the attribute's quantity kind has dimensions but its value
            has no units, since 223P requires a unit for every quantifiable
            property with a value. plumb raises its own ValueError for other
            problems, e.g. units of the wrong dimensions.
        """
        # there is no reason to add a property without data to the graph
        if value is None:
            return None

        prop_id = self._sanitize_id(parent_id) + attr_name
        # TODO: handle dictionary attributes
        try:  # if Pint object, there will be units and magnitude fields
            unit_dict = self.convert_units(value.units)
            if CONVERT_TO_KEY in unit_dict:  # no QUDT unit, so convert to one that has
                warnings.warn(
                    f"{value.units} has no QUDT unit, so {prop_id} was converted to {unit_dict[CONVERT_TO_KEY]}",
                    UnitConversionWarning,
                )
                value = value.to(unit_dict[CONVERT_TO_KEY])
                unit_dict = self.convert_units(value.units)
            value = value.magnitude
        except AttributeError:  # if no `units` attribute, assume value is directly stored
            unit_dict = {}

        prop_data, is_quant_kind = self.convert_attribute(attr_name)
        substance = self._enum_value(prop_data[SUBSTANCE_KEY]) if prop_data.get(SUBSTANCE_KEY) else None

        if is_quant_kind:
            kind = self._quantity_kind(prop_data)
            # 223P requires a quantifiable property's value to have a unit, so a plain
            # number is only complete for a dimensionless quantity (e.g. friction)
            if not unit_dict and kind.dimension_vector not in (None, units.UNITLESS.dimension_vector):
                raise ValueError(
                    f"{prop_id} is a {prop_data[NAME_KEY]}, which needs a unit, but its value {value!r} has none"
                )
            # plumb checks the rest, e.g. that the unit has the quantity kind's dimensions
            unit = self._unit(unit_dict) or units.UNITLESS
            prop = host.quantity(prop_id, value, unit=unit, kind=kind, of_substance=substance)
        else:
            prop = watr.EnumerableProperty(
                prop_id,
                has_value=value,
                has_enumeration_kind=self._enum(prop_data),
                of_substance=substance,
                model=self.model,
            )
            host.has_property.add(prop)

        self.properties[prop_id] = prop
        return prop

    def translate_tag(self, tag: Tag):
        """Convert a PyPES SCADA tag to a WaTr sensor and its observed property.

        Parameters
        ----------
        tag : pype_schema.tag.Tag
            Tag to translate. The sensor is named after the tag and observes
            a property named `"<tag id>-value"`, located on the tag's parent
            node or connection. `tag.units`, `tag.tag_type`, and
            `tag.contents` drive the property's quantity kind or enumeration
            kind, unit, substance, and medium.

        Returns
        -------
        plumb sensor
            The sensor recorded in `self.sensors` for this tag.

        Raises
        ------
        ValueError
            If `tag` has no contents but its type is not one of PyPES's
            `CONTENTLESS_TYPES`.
        """
        # Tag attributes:
        # - id : str
        # - units : pint.Unit
        # - tag_type : TagType
        # - source_unit_id : int or str
        # - dest_unit_id : int or str
        # - parent_id : str
        # - totalized : bool
        # - contents : ContentsType
        # - manufacturer : str
        # - measure_freq : pint.Quantity
        # - report_freq : pint.Quantity
        # - downsample_method : DownsampleType
        # - calibration : Logbook
        # NOTE: totalized, manufacturer, measure_freq, report_freq, downsample_method,
        # and calibration are all ignored
        # TODO: add handling of source and destination unit IDs

        # PyPES only allows the tag types in `CONTENTLESS_TYPES` to have no contents
        if tag.contents is None and tag.tag_type not in CONTENTLESS_TYPES:
            raise ValueError(
                f"Tag {tag.id} has no contents, but {tag.tag_type.name} tags must have contents"
            )

        tag_id = self._sanitize_id(tag.id)
        host = self.connections.get(tag.parent_id) or self.entities[tag.parent_id]
        unit_dict = self.convert_units(tag.units)
        if CONVERT_TO_KEY in unit_dict:
            # the tag's data lives outside the codec, so it can't be converted here
            warnings.warn(
                f"{tag.units} has no QUDT unit, so tag {tag_id} was given no unit "
                f"(its data would need converting to {unit_dict[CONVERT_TO_KEY]})",
                UnitConversionWarning,
            )
        unit = self._unit(unit_dict)

        prop_data, is_quant_kind = self.convert_tag_type(tag.tag_type, tag.units)
        kind = self._quantity_kind(prop_data) if is_quant_kind else self._enum(prop_data)
        # TODO: should Role be applied elsewhere or does it make sense in the property itself?
        medium = self._enum(self.convert_contents(tag.contents)) if tag.contents else None
        substance = self._enum_value(prop_data[SUBSTANCE_KEY]) if prop_data.get(SUBSTANCE_KEY) else None

        if unit is not None or not is_quant_kind:
            sensor = host.sensor(tag_id, kind=kind, unit=unit, of_medium=medium, of_substance=substance)
        else:
            # plumb's `sensor()` needs a unit for quantity kinds, so build the sensor by hand,
            # using the class plumb would pick for its quantity kind (e.g. FlowSensor)
            prop = watr.QuantifiableObservableProperty(
                tag_id + SENSOR_VALUE_SUFFIX,
                has_quantity_kind=kind,
                of_medium=medium,
                of_substance=substance,
                model=self.model,
            )
            host.has_property.add(prop)
            sensor_class = watr.REGISTRY.sensor_classes.get(kind.iri)
            sensor_class = watr.REGISTRY.resolve(sensor_class) if sensor_class else watr.Sensor
            sensor = sensor_class(tag_id, has_observation_location=host, observes=prop, model=self.model)

        self.sensors[tag_id] = sensor
        return sensor

    def translate_node(self, node: Node):
        """Convert a PyPES node into WaTr equipment with its properties.

        Parameters
        ----------
        node : pype_schema.node.Node
            Node to translate. Its class name is used to look up the
            corresponding plumb class in the mapping file. Any process the
            mapping declares is given to it when it is created (some WaTr
            classes, e.g. Reactor, require one), a digester's type becomes a
            role, and any remaining attributes are translated via
            `translate_attribute`. Connection points are created later, by
            `translate_connection`.

        Returns
        -------
        plumb equipment
            The entity recorded in `self.entities` for this node.
        """
        pypes_class = type(node).__name__
        node_data = self.mapping[TOP_LEVEL_KEY][NODES_KEY][pypes_class]
        node_id = self._sanitize_id(node.id)
        node_class = self._class(node_data)
        kwargs = {}
        if node_data.get(PROCESS_KEY):
            # plumb checks required processes (e.g. a Reactor's) as soon as the entity is created
            kwargs[HAS_PROCESS_PARAM] = [getattr(watr, self._python_name(node_data[PROCESS_KEY]))]
        medium_param = inspect.signature(node_class).parameters.get(MEDIUM_PARAM)
        if medium_param is not None and medium_param.default is inspect.Parameter.empty:
            # some classes (e.g. Junction) need their medium when they are created
            media = {self.convert_contents(c)[NAME_KEY]: c for c in node.input_contents + node.output_contents}
            if len(media) != 1:
                raise ValueError(f"{pypes_class} {node.id} needs exactly one medium, but has {sorted(media)}")
            kwargs[MEDIUM_PARAM] = self._enum(self.convert_contents(next(iter(media.values()))))
        with self.model:
            entity = node_class(node_id, **kwargs)

        for prop_name, prop_val in node.__dict__.items():  # get all attributes
            if (
                prop_name in CUSTOM_HANDLED_ATTRIBUTES
                or prop_name.startswith(PRIVATE_ATTR_PREFIX)
                or not self._has_data(prop_val)
            ):
                # ignore internal attributes starting with `_`, those handled
                # elsewhere (`CUSTOM_HANDLED_ATTRIBUTES`), and those without data
                pass
            elif prop_name in NOT_YET_IMPLEMENTED_ATTRIBUTES:
                warnings.warn(
                    f"The attribute {prop_name} for node {node_id} is not yet implemented in the WaTr codec!",
                    NotImplementedWarning,
                )
            elif prop_name == DIGESTER_TYPE_ATTR:
                # digester types (aerobic, anaerobic) are WaTr roles of the digester
                role_dict = self.mapping[TOP_LEVEL_KEY][DIGESTER_TYPES_KEY][prop_val.name]
                entity.has_role.add(self._enum(role_dict))
            else:
                # create property and attach it to the node
                self.translate_attribute(prop_name, prop_val, node_id, entity)

        self.entities[node.id] = entity
        return entity

    def translate_connection(self, conn: connection.Connection):
        """Convert a PyPES connection into a WaTr connection with its properties.

        Parameters
        ----------
        conn : pype_schema.connection.Connection
            Connection to translate. It gets an outlet point
            (`"<conn id>-out"`) on the equipment it leaves and an inlet point
            (`"<conn id>-in"`) on the equipment it enters, so plumb never has
            to guess the direction. When an end is a network, the
            connection's `exit_point`/`entry_point` child is used instead.
            Its contents give its medium and role, and any remaining
            attributes are translated via `translate_attribute`.

        Returns
        -------
        plumb connection handle
            The handle recorded in `self.connections` for this connection.
        """
        pypes_class = type(conn).__name__
        conn_id = self._sanitize_id(conn.id)
        conn_data = self.mapping[TOP_LEVEL_KEY][CONNECTIONS_KEY][pypes_class]

        medium_dict = self.convert_contents(conn.contents)
        medium = self._enum(medium_dict)
        source = self._endpoint(conn.source, conn.exit_point, conn.id, EXIT_POINT_ATTR)
        dest = self._endpoint(conn.destination, conn.entry_point, conn.id, ENTRY_POINT_ATTR)
        # give each point the connection's medium, or plumb limits it to the media its
        # equipment's class expects (e.g. a pump's fluid inlets would rule out a Wire)
        outlet = source.port(conn_id + OUTLET_SUFFIX, direction=OUTLET_DIRECTION, medium=medium)
        inlet = dest.port(conn_id + INLET_SUFFIX, direction=INLET_DIRECTION, medium=medium)
        handle = connect(outlet, inlet, name=conn_id, medium=medium, connection=self._class(conn_data))
        if medium_dict.get(ROLE_KEY):
            # TODO: should Role be applied elsewhere or does it make sense in the connection?
            handle.has_role.add(self._enum_value(medium_dict[ROLE_KEY]))

        # TODO: add logic to handle source and destination unit IDs
        # TODO: add logic for bidirectional connections
        for prop_name, prop_val in conn.__dict__.items():  # get all attributes
            if (
                prop_name in CUSTOM_HANDLED_ATTRIBUTES
                or prop_name.startswith(PRIVATE_ATTR_PREFIX)
                or not self._has_data(prop_val)
            ):
                # TODO: add logic for dictionary attributes (like flow_rate and gen_capacity)
                # ignore internal attributes starting with `_`, those handled
                # elsewhere (`CUSTOM_HANDLED_ATTRIBUTES`), and those without data
                pass
            elif prop_name in NOT_YET_IMPLEMENTED_ATTRIBUTES:
                warnings.warn(
                    f"The attribute {prop_name} for connection {conn_id} is not yet implemented in the WaTr codec!",
                    NotImplementedWarning,
                )
            else:
                # create property and attach it to the connection
                self.translate_attribute(prop_name, prop_val, conn_id, handle)

        self.connections[conn.id] = handle
        return handle

    def translate_network(self, network: Network, region=None):
        """Recursively translate every node, connection, and tag in a network.

        Parameters
        ----------
        network : pype_schema.node.Network
            Network to translate. Nested networks (including `Facility` and
            `ModularUnit`) become RealEstateCore spaces (e.g. `rec:Region`)
            that are the location of the nodes inside them.
        region : plumb rec space, optional
            The space translated for `network`, or None for `self.world`,
            which is the model itself rather than a space.
        """
        for node in network.get_all_nodes(recurse=False):
            if isinstance(node, Network):
                node_data = self.mapping[TOP_LEVEL_KEY][NODES_KEY][type(node).__name__]
                with self.model:
                    child = self._class(node_data)(self._sanitize_id(node.id))
                self.entities[node.id] = child
                self.translate_network(node, region=child)
            else:
                child = self.translate_node(node)
            if region is not None:
                if isinstance(child, brick.Space):
                    region.has_part.add(child)
                else:
                    region.is_location_of.add(child)

        for conn in network.get_all_connections(recurse=False):
            self.translate_connection(conn)

        # pype_schema returns tags in set order, so sort them for a reproducible translation
        for tag in sorted(network.get_all_tags(recurse=False), key=lambda tag: tag.id):
            if isinstance(tag, VirtualTag):
                pass  # TODO: implement VirtualTag to Acquirium soft sensor translator
            elif isinstance(self.entities.get(tag.parent_id), brick.Space):
                warnings.warn(
                    f"Tag {tag.id} is on network {tag.parent_id}, and tags on rec spaces "
                    "are not yet implemented in the WaTr codec!",
                    NotImplementedWarning,
                )
            else:
                self.translate_tag(tag)

    def to_graph(self):
        """Translate the facility (if not already done) and return its graph.

        Returns
        -------
        rdflib.Graph
            The resolved semantic graph for `self.world`, including the
            definition of each of the codec's own WaTr terms it uses (see
            `watr_extensions.ttl`). Calling this more than once is safe and
            returns the same graph without re-running the translation.
        """
        if self._graph is None:
            self.translate_network(self.world)
            self._graph = self.model.graph()
            # the codec's own terms are not in the WaTr ontology the graph
            # imports, so define the ones it uses in the graph itself
            for term in set(EXTENSION_GRAPH.subjects()):
                if (None, None, term) in self._graph:
                    self._graph += EXTENSION_GRAPH.triples((term, None, None))
        return self._graph

    def validate(self):
        """Translate the facility (if not already done) and validate it.

        Returns
        -------
        plumb ValidationReport
            The SHACL validation report against the WaTr, 223P, and QUDT
            shapes, plus the codec's own WaTr terms (see
            `watr_extensions.ttl`). It is truthy when the model conforms.
        """
        self.to_graph()
        # add the codec's own terms to the shapes plumb would use by default,
        # so they are recognized like the WaTr ontology's terms
        shapes = _package_shapes(self.model)
        shapes += EXTENSION_GRAPH
        return self.model.validate(shapes)

    def export_ttl(self, outpath):
        """Translate the facility and write the resulting graph as Turtle.

        Parameters
        ----------
        outpath : str or os.PathLike
            Path to write the serialized Turtle (`.ttl`) file to.
        """
        graph = self.to_graph()
        with open(outpath, "w", encoding=FILE_ENCODING) as file:
            file.write(graph.serialize(format=TURTLE_FORMAT))
