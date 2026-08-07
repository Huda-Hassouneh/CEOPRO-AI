"""
CEOPRO AI - MPI Sample-Size Policy (spec S17, S23).
The MPI's `scoring.py` already dampens toward the neutral midpoint
continuously via volume_confidence - this module is the discrete status
label (OK / LOW_SAMPLE_SIZE) the dashboard/evidence explanation needs on top
of that, same shape as sentiment/cold_start.py's LOW SAMPLE SIZE flag, one
level below sentiment's own threshold since an MPI already blends multiple
weakly-sampled reviews rather than reporting one review's raw label.
"""

import os
from dataclasses import dataclass

MIN_SAMPLE_SIZE = int(os.getenv("MPI_MIN_SAMPLE_SIZE", "5"))


@dataclass
class SampleSizeAssessment:
    sufficient: bool
    analyzed_count: int
    minimum_required: int
    status: str  # "LOW_SAMPLE_SIZE" | "OK"

    def as_dict(self) -> dict:
        return {
            "sufficient": self.sufficient,
            "analyzed_count": self.analyzed_count,
            "minimum_required": self.minimum_required,
            "status": self.status,
        }


def assess(analyzed_count: int) -> SampleSizeAssessment:
    sufficient = analyzed_count >= MIN_SAMPLE_SIZE
    return SampleSizeAssessment(
        sufficient=sufficient,
        analyzed_count=analyzed_count,
        minimum_required=MIN_SAMPLE_SIZE,
        status="OK" if sufficient else "LOW_SAMPLE_SIZE",
    )
