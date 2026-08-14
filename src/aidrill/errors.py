"""Exception hierarchy. One base so callers can catch the whole library."""


class AidrillError(Exception):
    """Base for every error raised by aidrill."""


class SourceError(AidrillError):
    """Something went wrong reading the input artwork."""


class LayerNotFoundError(SourceError):
    def __init__(self, wanted: str, available):
        self.wanted = wanted
        self.available = tuple(available)
        super().__init__(
            f"no layer named {wanted!r}; found: {', '.join(sorted(self.available)) or '(none)'}"
        )


class EmptyLayerError(SourceError):
    def __init__(self, layer: str):
        self.layer = layer
        super().__init__(
            f"layer {layer!r} contained no drillable geometry. In Illustrator, paths "
            f"with neither fill nor stroke are omitted from the PDF stream entirely — "
            f"give the drill circles a stroke."
        )


class EmitterError(AidrillError):
    """An emitter could not produce output from the data it was given."""
