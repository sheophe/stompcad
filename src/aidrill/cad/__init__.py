"""Supplied CAD models and the clearance questions they answer.

Only the kernel-free contract is imported here. The OpenCASCADE-backed
implementation is reached through ``load_case_model``, which imports it
lazily, so ``import aidrill`` never pays for the kernel.
"""

from .base import CaseModel, Frame, KernelUnavailable, Rejection

__all__ = ["CaseModel", "Frame", "Rejection", "KernelUnavailable"]
