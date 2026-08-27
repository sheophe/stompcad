"""Supplied CAD models and the clearance questions they answer.

Only the kernel-free contract is imported here. The OpenCASCADE-backed
implementation is reached through ``load_case_model``, which imports it
lazily, so ``import stompdrill`` never pays for the kernel. ``OcpCaseModel``
is exported because it now appears in the cutting path's own signatures
(the STEP emitter's options, the CLI's case-model construction) — it names
what a live kernel document actually requires, where ``CaseModel`` names
only what clearance requires.
"""

from .base import CaseModel, Rejection, step_keyword
from .loader import OcpCaseModel, load_case_model

__all__ = ["CaseModel", "OcpCaseModel", "Rejection", "load_case_model", "step_keyword"]
