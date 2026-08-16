"""Library exception hierarchy with source- and emitter-specific failures."""

from __future__ import annotations

from collections.abc import Iterable

__all__ = [
    "AidrillError",
    "SourceError",
    "LayerNotFoundError",
    "EmptyLayerError",
    "EmitterError",
]


class AidrillError(Exception):
    """Base for every error raised by aidrill."""


class SourceError(AidrillError):
    """Something went wrong reading the input artwork."""


class LayerNotFoundError(SourceError):
    """The requested layer is absent; report the available top-level layers."""

    def __init__(self, wanted: str, available: Iterable[str]) -> None:
        self.wanted = wanted
        self.available: tuple[str, ...] = tuple(available)
        super().__init__(
            f"no layer named {wanted!r}; found: {', '.join(sorted(self.available)) or '(none)'}"
        )


class EmptyLayerError(SourceError):
    """The layer was found, and yielded no drillable circle.

    ``path_count == 0`` means no painted paths reached the PDF stream; a positive
    count means paths were present but none satisfied the circle predicate.
    """

    def __init__(self, layer: str, path_count: int = 0) -> None:
        self.layer = layer
        self.path_count = path_count
        super().__init__(_empty_layer_message(layer, path_count))


class EmitterError(AidrillError):
    """An emitter could not produce output from the data it was given."""


def _empty_layer_message(layer: str, path_count: int) -> str:
    if path_count:
        return (
            f"layer {layer!r} has {path_count} path(s) but none of them is a circle. "
            f"Only true circles are drillable: four cubic Beziers, equal radii, "
            f"kappa-consistent controls. Rounded rectangles, ellipses, compound "
            f"shapes and stray marks all read as non-circular here."
        )
    return (
        f"layer {layer!r} contained no drillable geometry. In Illustrator, paths "
        f"with neither fill nor stroke are omitted from the PDF stream entirely — "
        f"give the drill circles a stroke."
    )
