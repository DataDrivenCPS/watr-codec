from dataclasses import dataclass
from typing import Any

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF


def _namespace_uri(value: str) -> str:
    return value.strip().removeprefix("<").removesuffix(">")


def _bind_semantic_object_prefixes(graph: Graph) -> None:
    """Use semantic_objects prefix bindings when the runtime provides them."""
    try:
        import typing
        from typing_extensions import Self

        if not hasattr(typing, "Self"):
            typing.Self = Self

        from semantic_objects.namespaces import bind_prefixes
    except Exception:
        return

    bind_prefixes(graph)


@dataclass(frozen=True)
class SemanticTerm:
    iri: URIRef


@dataclass(frozen=True)
class SemanticStatement:
    subject: SemanticTerm
    predicate: SemanticTerm
    object: SemanticTerm | Literal


class SemanticModel:
    """Small graph-backed semantic object model for generated WaTr resources."""

    def __init__(
        self,
        local_prefix: str,
        uri_mapping: dict[str, str],
        local_namespace: str = "urn:ex/",
    ):
        self.local_prefix = local_prefix
        self.graph = Graph()
        self.namespaces = {
            prefix: Namespace(_namespace_uri(uri))
            for prefix, uri in uri_mapping.items()
        }
        self.namespaces[local_prefix] = Namespace(local_namespace)

        _bind_semantic_object_prefixes(self.graph)
        for prefix, namespace in self.namespaces.items():
            self.graph.bind(prefix, namespace)

    def term(self, prefix: str, name: str = "") -> SemanticTerm:
        return SemanticTerm(URIRef(self.namespaces[prefix][name]))

    def local(self, name: str = "") -> SemanticTerm:
        return self.term(self.local_prefix, name)

    def predicate(self, prefix: str, name: str) -> SemanticTerm:
        return self.term(prefix, name)

    def literal(self, value: Any) -> Literal:
        return Literal(value)

    def add(
        self,
        subject: SemanticTerm,
        predicate: SemanticTerm,
        obj: SemanticTerm | Literal,
    ):
        self.graph.add(
            (
                subject.iri,
                predicate.iri,
                obj.iri if isinstance(obj, SemanticTerm) else obj,
            )
        )

    def add_type(self, subject: SemanticTerm, rdf_type: SemanticTerm):
        self.graph.add((subject.iri, RDF.type, rdf_type.iri))

    def serialize(self) -> str:
        return self.graph.serialize(format="turtle")
