"""Exception hierarchy. One base so a caller can catch the whole library.

The hierarchy is deliberately shallow — ``AidrillError``, a source family and an
emitter leaf — because the CLI asks it only one question: *is this fault the
input's, or ours?* Everything raised here prints as a single line and exits 3;
anything else keeps its traceback, because a programming error dressed up as a
tidy usage message sends the operator hunting through artwork that was never at
fault. Widening ``cli.main``'s catch to bare ``Exception`` would do exactly that,
which is why the boundary is drawn by this module rather than by a keyword.

The messages are product, not decoration. The person reading them is usually
looking at a panel that appears perfectly fine on screen: paths with neither fill
nor stroke are omitted from Illustrator's PDF stream entirely, so
:class:`EmptyLayerError` names the remedy — give the drill circles a stroke —
rather than reporting "no geometry" and leaving them to guess. That is also why
it takes ``path_count``. *No paths at all* and *paths, but none of them circular*
are different faults with different remedies, and the second message used to be
written by the source overwriting ``.args`` after construction: half of this
module's best writing lived outside this module, one attribute assignment away
from a message that contradicted the class it came from.
"""

from __future__ import annotations

from typing import Iterable

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
    """The requested layer is not in the file — and here are the ones that are.

    Layer names are the operator's own and come from ``/OCProperties``, so the
    two likely causes are a typo and a sublayer, which folds into its parent OCG
    and so is not a top-level name at all. Listing what was found answers both
    without the operator reopening Illustrator.
    """

    def __init__(self, wanted: str, available: Iterable[str]) -> None:
        self.wanted = wanted
        self.available: tuple[str, ...] = tuple(available)
        super().__init__(
            f"no layer named {wanted!r}; found: {', '.join(sorted(self.available)) or '(none)'}"
        )


class EmptyLayerError(SourceError):
    """The layer was found, and yielded no drillable circle.

    ``path_count`` is how many paths the source saw in it, and it selects between
    two messages because it selects between two remedies: zero means the artwork
    is unpainted and never reached the PDF stream, while any other count means
    the shapes are there but are not circles. Only the source can tell these
    apart, so it passes the count in; the error decides what to say about it.
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
