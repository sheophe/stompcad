"""Supplied CAD models and the clearance questions they answer.

Only the kernel-free contract is imported here. The OpenCASCADE-backed
implementation is reached through ``load_case_model``, which imports it
lazily, so ``import stompdrill`` never pays for the kernel.
"""

from .base import CaseModel, Frame, KernelUnavailable, Rejection
from .loader import load_case_model

__all__ = ["CaseModel", "Frame", "Rejection", "KernelUnavailable", "load_case_model"]
