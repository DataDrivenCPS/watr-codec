from dataclasses import dataclass
from typing import Any

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF
from semantic_objects.namespaces import bind_prefixes


def _namespace_uri(value: str) -> str:
    """Strip optional angle brackets from a namespace IRI string.

    Parameters
    ----------
    value : str
        Namespace IRI, optionally wrapped in `<...>` (as used in
        `uri_mapping.json`).

    Returns
    -------
    str
        `value` with any leading `<` and trailing `>` removed, and
        surrounding whitespace stripped.
    """
    return value.strip().removeprefix("<").removesuffix(">")


@dataclass
class SemanticTerm:
    """An RDF term (IRI) usable as a subject, predicate, or object.

    Attributes
    ----------
    iri : rdflib.URIRef
        The term's full IRI, e.g. `http://data.ashrae.org/standard223#hasMedium`.
        This is what gets written into the rdflib graph.
    """

    iri: URIRef


class SemanticModel:
    """Small graph-backed semantic object model for generated WaTr resources."""

    def __init__(
        self,
        local_prefix: str,
        uri_mapping: dict[str, str],
        local_namespace: str = "urn:ex/",
    ):
        """Create an empty graph with the given namespaces bound.

        Parameters
        ----------
        local_prefix : str
            Prefix to register for this model's own local namespace (e.g.
            the abbreviation for a specific facility).
        uri_mapping : dict of str to str
            Mapping of namespace prefix to namespace IRI (as loaded from
            `uri_mapping.json`), registered in addition to `local_prefix`.
        local_namespace : str, optional
            IRI to use for `local_prefix`. Defaults to `"urn:ex/"`.
        """
        self.local_prefix = local_prefix
        self.graph = Graph()
        self.namespaces = {
            prefix: Namespace(_namespace_uri(uri))
            for prefix, uri in uri_mapping.items()
        }
        self.namespaces[local_prefix] = Namespace(local_namespace)

        bind_prefixes(self.graph)
        for prefix, namespace in self.namespaces.items():
            self.graph.bind(prefix, namespace)

    def term(self, prefix: str, name: str = "") -> SemanticTerm:
        """Build a term from a registered namespace prefix and local name.

        Parameters
        ----------
        prefix : str
            Namespace prefix previously registered via `uri_mapping` or
            `local_prefix`.
        name : str, optional
            Local name within that namespace. Defaults to the empty string,
            which yields the namespace's root term.

        Returns
        -------
        SemanticTerm
            Term identified by `prefix:name`.
        """
        return SemanticTerm(URIRef(self.namespaces[prefix][name]))

    def local(self, name: str = "") -> SemanticTerm:
        """Build a term in this model's own local namespace.

        Parameters
        ----------
        name : str, optional
            Local name to append to the local namespace. Defaults to the
            empty string, which yields the namespace's root term.

        Returns
        -------
        SemanticTerm
            Term identified by `self.local_prefix:name`.
        """
        return self.term(self.local_prefix, name)

    def predicate(self, prefix: str, name: str) -> SemanticTerm:
        """Build a predicate term from a namespace prefix and local name.

        Parameters
        ----------
        prefix : str
            Namespace prefix of the predicate.
        name : str
            Local name of the predicate within `prefix`.

        Returns
        -------
        SemanticTerm
            Term identified by `prefix:name`, used as a predicate.
        """
        return self.term(prefix, name)

    def literal(self, value: Any) -> Literal:
        """Wrap a plain Python value as an RDF literal.

        Parameters
        ----------
        value : Any
            Value to wrap (e.g. `int`, `float`, `str`, `bool`).

        Returns
        -------
        rdflib.Literal
            RDF literal for `value`.
        """
        return Literal(value)

    def add(
        self,
        subject: SemanticTerm,
        predicate: SemanticTerm,
        obj: SemanticTerm | Literal,
    ):
        """Add a single (subject, predicate, object) triple to the graph.

        Parameters
        ----------
        subject : SemanticTerm
            Subject of the triple.
        predicate : SemanticTerm
            Predicate of the triple.
        obj : SemanticTerm or rdflib.Literal
            Object of the triple. If a `SemanticTerm`, its IRI is used;
            otherwise (e.g. a `Literal`) it is added as-is.
        """
        self.graph.add(
            (
                subject.iri,
                predicate.iri,
                obj.iri if isinstance(obj, SemanticTerm) else obj,
            )
        )

    def add_type(self, subject: SemanticTerm, rdf_type: SemanticTerm):
        """Add an `rdf:type` triple for a term.

        Parameters
        ----------
        subject : SemanticTerm
            Term to type.
        rdf_type : SemanticTerm
            Class term to assign as `subject`'s `rdf:type`.
        """
        self.graph.add((subject.iri, RDF.type, rdf_type.iri))

    def serialize(self) -> str:
        """Serialize the accumulated graph as Turtle.

        Returns
        -------
        str
            The graph's contents serialized in Turtle (`.ttl`) syntax.
        """
        return self.graph.serialize(format="turtle")
