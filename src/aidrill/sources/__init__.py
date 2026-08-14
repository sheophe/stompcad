"""Sources: everything that turns some artwork format into ``DrillData``.

One module per format. They share nothing but the ``Source`` protocol and the
``geometry`` helpers, so adding SVG or DXF later touches nothing that exists.
"""

from .ai_pdf import AiPdfSource

__all__ = ["AiPdfSource"]
