import json
import os
import warnings

import pint
from pype_schema import connection, utils
from pype_schema.node import Network, Node
from pype_schema.tag import CONTENTLESS_TYPES, Tag, TagType, VirtualTag

from watr_codec.semantic_backend import SemanticModel, SemanticTerm


# add this file path to dir so that data folder is always accessible
WATR_CODEC_DIR = os.path.dirname(os.path.abspath(__file__))

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
NAME_KEY = "name"
URI_KEY = "uri"
KIND_KEY = "kind"
ROLE_KEY = "role"
ROLE_URI_KEY = "role-uri"
SUBSTANCE_KEY = "substance"
SUBSTANCE_URI_KEY = "substance-uri"

# allowed values of the mapping file's `kind` key
QUANT_KIND_STR = "QuantityKind"
ENUM_KIND_STR = "EnumerationKind"

# namespace prefixes (see `uri_mapping.json`)
S223_URI = "s223"
WATR_URI = "watr"
QUDT_URI = "qudt"
OWL_URI = "owl"

# RDF classes
QUANT_PROP_CLASS = "QuantifiableProperty"
ENUM_PROP_CLASS = "EnumerableProperty"
QUANT_OBS_PROP_CLASS = "QuantifiableObservableProperty"
ENUM_OBS_PROP_CLASS = "EnumeratedObservableProperty"
OUTLET_CONN_POINT_CLASS = "OutletConnectionPoint"
INLET_CONN_POINT_CLASS = "InletConnectionPoint"
ONTOLOGY_CLASS = "Ontology"

# RDF predicates
HAS_VALUE_PRED = "hasValue"
HAS_UNIT_PRED = "hasUnit"
HAS_QUANT_KIND_PRED = "hasQuantityKind"
HAS_ENUM_KIND_PRED = "hasEnumerationKind"
HAS_MEDIUM_PRED = "hasMedium"
OF_MEDIUM_PRED = "ofMedium"
HAS_ROLE_PRED = "hasRole"
OF_SUBSTANCE_PRED = "ofSubstance"
HAS_PROPERTY_PRED = "hasProperty"
HAS_PROCESS_PRED = "hasProcess"
HAS_CONN_POINT_PRED = "hasConnectionPoint"
IS_CONN_POINT_OF_PRED = "isConnectionPointOf"
CONNECTS_THROUGH_PRED = "connectsThrough"
CNX_PRED = "cnx"

# connection points are named `{node_id}-cp-{n}`
CONN_POINT_STR = "-cp-"

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
    "exit_point",
    "entry_point",
]

# TODO: implement conversion of the below attributes
NOT_YET_IMPLEMENTED_ATTRIBUTES = [
    "heating_values",
    "pressure",
    "flow_rate",
    "bidirectional",
    "pump_type",
    "pump_curve",
    "digester_type",
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


class PyPES2WaTr:
    """Translates a pype_schema PyPES network into a WaTr semantic graph.

    An instance walks a `pype_schema.node.Network` (and any nodes,
    connections, and tags nested inside it), converts each piece into the
    corresponding WaTr/S223/QUDT terms using the mapping data in
    `pypes_watr_mapping.json`, and accumulates the resulting triples in an
    internal `SemanticModel`. The translation only happens once; the first
    call to `to_graph` (or `export_ttl`) performs it and caches the result.
    """

    def __init__(
        self,
        network: Network,
        local_prefix: str,
        mapping_path=WATR_CODEC_DIR + "/data/pypes_watr_mapping.json",
        uri_mapping_path=WATR_CODEC_DIR + "/data/uri_mapping.json",
    ):
        """Create a translator bound to a PyPES network and mapping data.

        Parameters
        ----------
        network : pype_schema.node.Network
            The (possibly nested) PyPES facility/network to translate.
        local_prefix : str
            RDF namespace prefix used for terms minted for this facility
            (e.g. node, connection, and property IRIs).
        mapping_path : str, optional
            Path to the PyPES-to-WaTr JSON mapping file. Defaults to
            `data/pypes_watr_mapping.json` bundled with this package.
        uri_mapping_path : str, optional
            Path to the JSON file mapping URI prefixes to namespace IRIs.
            Defaults to `data/uri_mapping.json` bundled with this package.
        """
        self.world = network
        self.local_prefix = local_prefix
        with open(mapping_path, "r", encoding="utf-8") as file:
            self.mapping = json.load(file)
        with open(uri_mapping_path, "r", encoding="utf-8") as file:
            self.uri_mapping = json.load(file)

        self.model = SemanticModel(local_prefix, self.uri_mapping)
        self.property_dict = {}
        self.node_to_conn_ids = {}
        self.node_dict = {}
        self.conn_dict = {}
        self.conn_point_dict = {}
        self._translated = False

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

    def _local(self, name: str = "") -> SemanticTerm:
        """Build a term in this facility's local namespace.

        Parameters
        ----------
        name : str, optional
            Local name to append to the local namespace. Defaults to the
            empty string, which yields the namespace's root term (used to
            represent the ontology itself).

        Returns
        -------
        SemanticTerm
            Term for `name` in the local namespace.
        """
        return self.model.local(name)

    def _term(self, data: dict) -> SemanticTerm:
        """Build a term from a mapping-file entry's URI prefix and name.

        Parameters
        ----------
        data : dict
            A mapping-file entry containing at least `"uri"` and `"name"`
            keys (e.g. an entry from `nodes`, `contents_types`,
            `attributes`, or `tag_types` in `pypes_watr_mapping.json`).

        Returns
        -------
        SemanticTerm
            Term identified by `data["uri"]:data["name"]`.
        """
        return self.model.term(data[URI_KEY], data[NAME_KEY])

    def _predicate(self, prefix: str, name: str) -> SemanticTerm:
        """Build a predicate term from a namespace prefix and local name.

        Parameters
        ----------
        prefix : str
            Namespace prefix (e.g. `"s223"`, `"qudt"`, `"watr"`).
        name : str
            Local name of the predicate within that namespace.

        Returns
        -------
        SemanticTerm
            Term identified by `prefix:name`.
        """
        return self.model.predicate(prefix, name)

    def _add_relation(
        self, subject: SemanticTerm, prefix: str, name: str, obj: SemanticTerm
    ):
        """Add a single (subject, predicate, object) triple to the graph.

        Parameters
        ----------
        subject : SemanticTerm
            Subject of the triple.
        prefix : str
            Namespace prefix of the predicate.
        name : str
            Local name of the predicate within `prefix`.
        obj : SemanticTerm
            Object of the triple.
        """
        self.model.add(subject, self._predicate(prefix, name), obj)

    def get_uri_prefix(self, uri: str):
        """Look up the namespace IRI registered for a URI prefix.

        Parameters
        ----------
        uri : str
            Short URI prefix, e.g. `"s223"` or `"watr"`.

        Returns
        -------
        str
            The full namespace IRI associated with `uri` in
            `uri_mapping.json`.
        """
        return self.uri_mapping[uri]

    def convert_units(self, units: pint.Unit):
        """Look up the WaTr/QUDT unit entry for a Pint unit.

        Parameters
        ----------
        units : pint.Unit
            Unit to translate, as used by pype_schema attributes and tags.

        Returns
        -------
        dict
            The mapping-file entry for `units` (may be an empty dict if the
            unit is listed but intentionally left unmapped).
        """
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

    def convert_tag_type(self, tag_type: TagType):
        """Look up the WaTr property entry for a PyPES tag type.

        Parameters
        ----------
        tag_type : pype_schema.tag.TagType
            Type of the SCADA tag being translated (e.g. `TagType.Flow`).

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
        if prop_dict[KIND_KEY] not in (QUANT_KIND_STR, ENUM_KIND_STR):
            raise ValueError(f"Unknown kind {prop_dict[KIND_KEY]!r} for tag type {tag_type.name}")
        return prop_dict, prop_dict[KIND_KEY] == QUANT_KIND_STR

    def generate_conn_point_name(self, name: str):
        """Disambiguate a connection-point name against already-used names.

        A node that participates in more than one connection will request
        the same base name (e.g. `"ERI-cp-1"`) more than once - once per
        connection it is a source or destination of. When that happens this
        method increments the numeric suffix (`-cp-2`, `-cp-3`, ...) so
        every connection point still gets a unique name; it does not change
        how many connection points get created; every connection still
        contributes exactly two.

        Parameters
        ----------
        name : str
            Proposed connection-point name, typically `"{node_id}-cp-1"`.

        Returns
        -------
        str
            `name` unchanged if it is not already taken, otherwise `name`
            with its numeric suffix incremented until it is unique.

        Raises
        ------
        ValueError
            If `name` is taken and does not end in a numeric suffix.
        """
        if name not in self.conn_point_dict:
            return name

        prefix, _, suffix = name.rpartition("-")
        next_num = int(suffix) + 1
        while f"{prefix}-{next_num}" in self.conn_point_dict:
            next_num += 1
        return f"{prefix}-{next_num}"

    def _add_medium_and_role(
        self, subject: SemanticTerm, medium_dict: dict, medium_predicate: str
    ):
        """Attach a medium relation (and role relation, if any) to a term.

        Parameters
        ----------
        subject : SemanticTerm
            Term the medium (and role) relation should be attached to.
        medium_dict : dict
            Mapping-file `contents_types` entry, as returned by
            `convert_contents`. May optionally include `"role"` and
            `"role-uri"` keys.
        medium_predicate : str
            Local name of the medium predicate to use (e.g. `"hasMedium"`
            for nodes/connections, `"ofMedium"` for properties).
        """
        medium = self._term(medium_dict)
        self._add_relation(subject, S223_URI, medium_predicate, medium)

        role = medium_dict.get(ROLE_KEY)
        if role:
            self._add_relation(
                subject,
                S223_URI,
                HAS_ROLE_PRED,
                self.model.term(medium_dict[ROLE_URI_KEY], role),
            )

    def create_conn_points(self, conn: connection.Connection):
        """Create the inlet/outlet connection points for a PyPES connection.

        Parameters
        ----------
        conn : pype_schema.connection.Connection
            Connection whose source and destination connection points
            should be created.

        Returns
        -------
        source_name : str
            Name of the outlet connection point created on `conn.source`.
        dest_name : str
            Name of the inlet connection point created on `conn.destination`.
        """
        source_name = self.generate_conn_point_name(f"{conn.source.id}{CONN_POINT_STR}1")
        dest_name = self.generate_conn_point_name(f"{conn.destination.id}{CONN_POINT_STR}1")
        source = self._local(source_name)
        dest = self._local(dest_name)
        conn_term = self._local(self._sanitize_id(conn.id))
        medium_dict = self.convert_contents(conn.contents)

        self.model.add_type(source, self.model.term(S223_URI, OUTLET_CONN_POINT_CLASS))
        self.model.add_type(dest, self.model.term(S223_URI, INLET_CONN_POINT_CLASS))
        self._add_relation(
            source,
            S223_URI,
            IS_CONN_POINT_OF_PRED,
            self._local(self._sanitize_id(conn.source.id)),
        )
        self._add_relation(
            dest,
            S223_URI,
            IS_CONN_POINT_OF_PRED,
            self._local(self._sanitize_id(conn.destination.id)),
        )
        self._add_relation(source, S223_URI, CONNECTS_THROUGH_PRED, conn_term)
        self._add_relation(dest, S223_URI, CONNECTS_THROUGH_PRED, conn_term)
        self._add_medium_and_role(source, medium_dict, HAS_MEDIUM_PRED)
        self._add_medium_and_role(dest, medium_dict, HAS_MEDIUM_PRED)

        # NOTE: ignoring connectsAt and connectsThrough as those can be inferred
        self.conn_point_dict[source_name] = {
            "node": conn.source.id,
            "connection": conn.id,
            "term": source,
        }
        self.conn_point_dict[dest_name] = {
            "node": conn.destination.id,
            "connection": conn.id,
            "term": dest,
        }
        return source_name, dest_name

    def translate_attribute(self, attr_name, value, parent_id, contents=None):
        """Convert a single PyPES node/connection attribute to a WaTr property.

        Parameters
        ----------
        attr_name : str
            Name of the attribute (e.g. `"diameter"`, `"elevation"`).
        value : pint.Quantity, float, str, or None
            Value of the attribute. If it has `.units`/`.magnitude`
            attributes (i.e. it is a Pint quantity), the units are looked up
            via `convert_units` and the magnitude is used as the value. If
            None, no property is created.
        parent_id : str
            ID of the PyPES node or connection this attribute belongs to.
        contents : pype_schema.utils.ContentsType, optional
            Contents to associate with this property, when they can be
            determined for the parent (e.g. a connection's `contents`).
            Default is None, for cases where contents cannot be
            automatically determined (e.g. plain node attributes).

        Returns
        -------
        dict or None
            The entry recorded in `self.property_dict` for this attribute,
            or None if `value` is None.
        """
        # there is no reason to add a property without data to the graph
        if value is None:
            return None

        prop_id = self._sanitize_id(parent_id) + attr_name
        # TODO: handle dictionary attributes
        try:  # if Pint object, there will be units and magnitude fields
            unit_dict = self.convert_units(value.units)
            converted_units = unit_dict.get(NAME_KEY)
            unit_uri = unit_dict.get(URI_KEY)
            value = value.magnitude
        except AttributeError:  # if no `units` attribute, assume value is directly stored
            unit_dict, converted_units, unit_uri = {}, None, None

        prop_data, is_quant_kind = self.convert_attribute(attr_name)
        prop_type = QUANT_PROP_CLASS if is_quant_kind else ENUM_PROP_CLASS
        prop_term = self._local(prop_id)

        self.model.add_type(prop_term, self.model.term(S223_URI, prop_type))
        self.model.add(
            prop_term,
            self._predicate(S223_URI, HAS_VALUE_PRED),
            self.model.literal(value),
        )

        # contents may be impossible to automatically discern for nodes, hence this check
        if contents is not None:
            # TODO: should Role be applied elsewhere or does it make sense in the property itself?
            medium_dict = self.convert_contents(contents)
            medium_name = medium_dict[NAME_KEY]
            medium_uri = medium_dict[URI_KEY]
            self._add_medium_and_role(prop_term, medium_dict, OF_MEDIUM_PRED)
            role_name = medium_dict.get(ROLE_KEY)
            role_uri = medium_dict.get(ROLE_URI_KEY) if role_name is not None else None
        else:
            medium_name, medium_uri, role_name, role_uri = None, None, None, None

        if is_quant_kind:
            self._add_relation(
                prop_term, QUDT_URI, HAS_QUANT_KIND_PRED, self._term(prop_data)
            )
        else:
            self._add_relation(
                prop_term, S223_URI, HAS_ENUM_KIND_PRED, self._term(prop_data)
            )

        substance_name = prop_data.get(SUBSTANCE_KEY)
        substance_uri = prop_data.get(SUBSTANCE_URI_KEY)
        if substance_name:
            self._add_relation(
                prop_term,
                S223_URI,
                OF_SUBSTANCE_PRED,
                self.model.term(substance_uri or S223_URI, substance_name),
            )

        if converted_units:
            self._add_relation(
                prop_term,
                S223_URI,
                HAS_UNIT_PRED,
                self.model.term(unit_uri, converted_units),
            )

        self.property_dict[prop_id] = {
            "property": prop_data[NAME_KEY],
            "prop_type": prop_type,
            "prop_uri": prop_data[URI_KEY],
            "parent_id": self._sanitize_id(parent_id),
            "medium": medium_name,
            "medium_uri": medium_uri,
            "role": role_name,
            "role_uri": role_uri,
            "substance": substance_name,
            "substance_uri": substance_uri,
            "source_unit_id": None,  # TODO: use this downstream
            "dest_unit_id": None,  # TODO: use this downstream
            "is_quant_kind": is_quant_kind,
            UNITS_KEY: unit_dict,
            "term": prop_term,
        }
        return self.property_dict[prop_id]

    def translate_tag(self, tag: Tag):
        """Convert a PyPES SCADA tag to a WaTr observable property.

        Parameters
        ----------
        tag : pype_schema.tag.Tag
            Tag to translate. `tag.units`, `tag.tag_type`, and
            `tag.contents` drive the WaTr quantity kind / enumeration kind,
            unit, and medium relations; `tag.source_unit_id` and
            `tag.dest_unit_id` are recorded but not yet used downstream.

        Returns
        -------
        dict
            The entry recorded in `self.property_dict` for this tag.

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

        # PyPES only allows the tag types in `CONTENTLESS_TYPES` to have no contents
        if tag.contents is None and tag.tag_type not in CONTENTLESS_TYPES:
            raise ValueError(
                f"Tag {tag.id} has no contents, but {tag.tag_type.name} tags must have contents"
            )

        tag_id = self._sanitize_id(tag.id)
        parent_id = self._sanitize_id(tag.parent_id)
        if tag.units is None:  # unitless tags (e.g., RunStatus) have no units to convert
            unit_dict, converted_units, unit_uri = {}, None, None
        else:
            unit_dict = self.convert_units(tag.units)
            converted_units = unit_dict.get(NAME_KEY)
            unit_uri = unit_dict.get(URI_KEY)

        prop_data, is_quant_kind = self.convert_tag_type(tag.tag_type)
        prop_type = QUANT_OBS_PROP_CLASS if is_quant_kind else ENUM_OBS_PROP_CLASS
        tag_term = self._local(tag_id)

        self.model.add_type(tag_term, self.model.term(S223_URI, prop_type))
        if tag.contents:
            # TODO: should Role be applied elsewhere or does it make sense in the property itself?
            medium_dict = self.convert_contents(tag.contents)
            medium_name = medium_dict[NAME_KEY]
            medium_uri = medium_dict[URI_KEY]
            self._add_medium_and_role(tag_term, medium_dict, OF_MEDIUM_PRED)
            role_name = medium_dict.get(ROLE_KEY)
            role_uri = medium_dict.get(ROLE_URI_KEY) if role_name is not None else None
        else:
            medium_name, medium_uri, role_name, role_uri = None, None, None, None

        if is_quant_kind:
            self._add_relation(
                tag_term, QUDT_URI, HAS_QUANT_KIND_PRED, self._term(prop_data)
            )
        else:
            self._add_relation(
                tag_term, S223_URI, HAS_ENUM_KIND_PRED, self._term(prop_data)
            )

        substance_name = prop_data.get(SUBSTANCE_KEY)
        substance_uri = prop_data.get(SUBSTANCE_URI_KEY)
        if substance_name:
            self._add_relation(
                tag_term,
                S223_URI,
                OF_SUBSTANCE_PRED,
                self.model.term(substance_uri or S223_URI, substance_name),
            )

        if converted_units:
            self._add_relation(
                tag_term,
                S223_URI,
                HAS_UNIT_PRED,
                self.model.term(unit_uri, converted_units),
            )

        self.property_dict[tag_id] = {
            "property": prop_data[NAME_KEY],
            "prop_type": prop_type,
            "prop_uri": prop_data[URI_KEY],
            "parent_id": parent_id,
            "medium": medium_name,
            "medium_uri": medium_uri,
            "role": role_name,
            "role_uri": role_uri,
            "substance": substance_name,
            "substance_uri": substance_uri,
            "source_unit_id": tag.source_unit_id,  # TODO: use this downstream
            "dest_unit_id": tag.dest_unit_id,  # TODO: use this downstream
            "is_quant_kind": is_quant_kind,
            UNITS_KEY: unit_dict,
            "term": tag_term,
        }
        return self.property_dict[tag_id]

    def _properties_for_parent(self, parent_id: str):
        """Look up the property terms already translated for a given parent.

        Parameters
        ----------
        parent_id : str
            Raw (unsanitized) ID of the parent node or connection.

        Returns
        -------
        list of SemanticTerm
            Terms of every entry in `self.property_dict` whose `parent_id`
            matches the sanitized form of `parent_id`.
        """
        parent_id = self._sanitize_id(parent_id)
        return [
            prop_attrs["term"]
            for prop_attrs in self.property_dict.values()
            if prop_attrs["parent_id"] == parent_id
        ]

    def _add_parent_properties(self, parent: SemanticTerm, parent_id: str):
        """Link a node or connection term to all of its translated properties.

        Parameters
        ----------
        parent : SemanticTerm
            Term for the node or connection that owns the properties.
        parent_id : str
            Raw (unsanitized) ID of that node or connection, used to look up
            its properties via `_properties_for_parent`.
        """
        for prop_term in self._properties_for_parent(parent_id):
            self._add_relation(parent, S223_URI, HAS_PROPERTY_PRED, prop_term)

    def translate_node(self, node: Node):
        """Convert a PyPES node into its WaTr type, connections, and properties.

        Parameters
        ----------
        node : pype_schema.node.Node
            Node to translate. Its class name is used to look up the
            corresponding WaTr type in the mapping file; its
            `input_contents`/`output_contents` become `hasMedium`
            relations; its connections (tracked via `node_to_conn_ids`)
            become `hasConnectionPoint`/`cnx` relations; and any remaining
            attributes are translated via `translate_attribute`.

        Returns
        -------
        dict
            The entry recorded in `self.node_dict` for this node.

        Raises
        ------
        ValueError
            If a connection tracked against this node does not actually
            list it as a source or destination.
        """
        pypes_class = type(node).__name__
        node_data = self.mapping[TOP_LEVEL_KEY][NODES_KEY][pypes_class]
        node_id = self._sanitize_id(node.id)
        node_term = self._local(node_id)

        self.model.add_type(node_term, self._term(node_data))
        if node_data.get(PROCESS_KEY):
            self._add_relation(
                node_term,
                WATR_URI,
                HAS_PROCESS_PRED,
                self.model.term(WATR_URI, node_data[PROCESS_KEY]),
            )

        # TODO: add handling of source and destination unit IDs to below logic
        conn_point_list = []
        conn_from_list = []
        conn_to_list = []
        conn_point_in = None
        conn_point_out = None

        for conn_id in self.node_to_conn_ids.get(node.id, []):
            conn_data = self.conn_dict[conn_id]
            # TODO: double check below logic
            if conn_data["destination"] == node.id:
                conn_point_list.append(conn_data["dest_conn_point"])
                conn_from_list.append(conn_data["source"])
                conn_point_in = conn_data["dest_conn_point"]
                # node_str += f"    {S223_URI}:connectedFrom {self.local_prefix}:{self.conn_dict[conn_id]["source"]} ;\n"
            elif conn_data["source"] == node.id:
                conn_point_list.append(conn_data["source_conn_point"])
                conn_to_list.append(conn_data["destination"])
                conn_point_out = conn_data["source_conn_point"]
                # node_str += f"    {S223_URI}:connectedTo {self.local_prefix}:{self.conn_dict[conn_id]["destination"]} ;\n"
            else:
                raise ValueError(
                    "Connection `source` or `destination` must match node `id`"
                )

            # TODO: how to handle if there are three connection points?
            # TODO: is this `cnx` necessary? I saw it from the examples, but am not sure
            if conn_point_in and conn_point_out:
                self._add_relation(
                    node_term, S223_URI, CNX_PRED, self._local(conn_point_in)
                )
                self._add_relation(
                    node_term, S223_URI, CNX_PRED, self._local(conn_point_out)
                )
                conn_point_in = None
                conn_point_out = None

        for conn_point in conn_point_list:
            self._add_relation(
                node_term, S223_URI, HAS_CONN_POINT_PRED, self._local(conn_point)
            )

        media_added = set()
        for contents in node.input_contents + node.output_contents:
            medium_dict = self.convert_contents(contents)
            medium_name = medium_dict[NAME_KEY]
            if medium_name not in media_added:
                self._add_relation(
                    node_term, S223_URI, HAS_MEDIUM_PRED, self._term(medium_dict)
                )
                media_added.add(medium_name)

        for prop_name, prop_val in node.__dict__.items():  # get all attributes
            if prop_name in CUSTOM_HANDLED_ATTRIBUTES or prop_name.startswith("_"):
                # ignore internal attributes starting with `_`
                # and those handled elsewhere (`CUSTOM_HANDLED_ATTRIBUTES`)
                pass
            elif prop_name in NOT_YET_IMPLEMENTED_ATTRIBUTES:
                warnings.warn(
                    f"The attribute {prop_name} for node {node_id} is not yet implemented in the WaTr codec!",
                    NotImplementedWarning,
                )
            else:
                # create property and add to property_dict
                # TODO: try to automatically determine contents
                self.translate_attribute(prop_name, prop_val, node_id, contents=None)

        self._add_parent_properties(node_term, node_id)
        # TODO: add more attributes to below dictionary
        self.node_dict[node_id] = {
            "node": node_data[NAME_KEY],
            "conn_points": conn_point_list,
            "connected_from": conn_from_list,
            "connected_to": conn_to_list,
            "term": node_term,
        }
        return self.node_dict[node_id]

    def translate_connection(self, conn: connection.Connection):
        """Convert a PyPES connection into its WaTr type, points, and properties.

        Parameters
        ----------
        conn : pype_schema.connection.Connection
            Connection to translate. Its class name is used to look up the
            corresponding WaTr type in the mapping file; `create_conn_points`
            builds its inlet/outlet connection points; and any remaining
            attributes are translated via `translate_attribute`.

        Returns
        -------
        dict
            The entry recorded in `self.conn_dict` for this connection.
        """
        pypes_class = type(conn).__name__
        conn_id = self._sanitize_id(conn.id)
        conn_data = self.mapping[TOP_LEVEL_KEY][CONNECTIONS_KEY][pypes_class]
        conn_term = self._local(conn_id)

        # This dictionary enables us to add the correct connections to each node
        self.node_to_conn_ids.setdefault(conn.source.id, []).append(conn.id)
        self.node_to_conn_ids.setdefault(conn.destination.id, []).append(conn.id)

        self.model.add_type(conn_term, self._term(conn_data))
        source_conn_point, dest_conn_point = self.create_conn_points(conn)
        self._add_relation(conn_term, S223_URI, CNX_PRED, self._local(source_conn_point))
        self._add_relation(conn_term, S223_URI, CNX_PRED, self._local(dest_conn_point))

        # TODO: should Role be applied elsewhere or does it make sense in the connection?
        medium_dict = self.convert_contents(conn.contents)
        medium_name = medium_dict[NAME_KEY]
        medium_uri = medium_dict[URI_KEY]
        self._add_medium_and_role(conn_term, medium_dict, HAS_MEDIUM_PRED)
        role_name = medium_dict.get(ROLE_KEY)
        role_uri = medium_dict.get(ROLE_URI_KEY) if role_name is not None else None

        # TODO: add logic to handle source and destination unit IDs
        # TODO: add logic for bidirectional connections
        for prop_name, prop_val in conn.__dict__.items():  # get all attributes
            if prop_name in CUSTOM_HANDLED_ATTRIBUTES or prop_name.startswith("_"):
                # TODO: add logic for dictionary attributes (like flow_rate and gen_capacity)
                # ignore internal attributes starting with `_`
                # and those handled elsewhere (`CUSTOM_HANDLED_ATTRIBUTES`)
                pass
            elif prop_name in NOT_YET_IMPLEMENTED_ATTRIBUTES:
                warnings.warn(
                    f"The attribute {prop_name} for connection {conn_id} is not yet implemented in the WaTr codec!",
                    NotImplementedWarning,
                )
            else:
                # create property and add to property_dict
                self.translate_attribute(
                    prop_name, prop_val, conn_id, contents=conn.contents
                )

        # TODO: check that hasProperty can have unlimited entries
        self._add_parent_properties(conn_term, conn_id)
        self.conn_dict[conn.id] = {
            "connection": conn_data[NAME_KEY],
            "source": conn.source.id,
            "destination": conn.destination.id,
            "source_conn_point": source_conn_point,
            "dest_conn_point": dest_conn_point,
            "medium": medium_name,
            "medium_uri": medium_uri,
            "role": role_name,
            "role_uri": role_uri,
            "term": conn_term,
        }
        return self.conn_dict[conn.id]

    # TODO: add contains and isContained logic to network hierarchy
    def translate_network(self, network: Network):
        """Recursively translate every tag, connection, and node in a network.

        Parameters
        ----------
        network : pype_schema.node.Network
            Network to translate. Nested `Network` nodes are translated
            recursively (and, since they are also nodes of their parent
            network, are additionally translated as nodes in their own
            right unless `network` is `self.world`).
        """
        for tag in network.get_all_tags():
            if isinstance(tag, VirtualTag):
                pass  # TODO: implement VirtualTag to Acquirium soft sensor translator
            else:
                self.translate_tag(tag)

        for conn in network.get_all_connections():
            self.translate_connection(conn)

        for node in network.get_all_nodes():
            if isinstance(node, Network):
                self.translate_network(node)
            else:
                self.translate_node(node)

        if self.world.id != network.id:
            self.translate_node(network)

    def to_graph(self):
        """Translate the facility (if not already done) and return its graph.

        Returns
        -------
        rdflib.Graph
            The accumulated semantic graph for `self.world`. Calling this
            more than once is safe and returns the same graph without
            re-running the translation.
        """
        if not self._translated:
            self.model.add_type(self._local(), self.model.term(OWL_URI, ONTOLOGY_CLASS))
            self.translate_network(self.world)
            self._translated = True
        return self.model.graph

    def export_ttl(self, outpath):
        """Translate the facility and write the resulting graph as Turtle.

        Parameters
        ----------
        outpath : str or os.PathLike
            Path to write the serialized Turtle (`.ttl`) file to.
        """
        graph = self.to_graph()
        with open(outpath, "w", encoding="utf-8") as file:
            file.write(graph.serialize(format="turtle"))
