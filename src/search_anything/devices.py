"""Choose a local inference device without hiding explicit GPU failures."""

import logging
from typing import Literal

InferenceDevice = Literal["auto", "cpu", "mps"]
logger = logging.getLogger(__name__)


def resolve_device(requested: InferenceDevice = "auto") -> str:
    import torch

    available = torch.backends.mps.is_available()
    if requested == "mps" and not available:
        raise RuntimeError("Apple MPS GPU is unavailable to this process")
    device = "mps" if requested != "cpu" and available else "cpu"
    logger.info("Local inference device: %s (requested: %s)", device, requested)
    return device
