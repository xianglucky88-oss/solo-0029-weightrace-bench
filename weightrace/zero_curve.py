from fractions import Fraction

from .protocol import segments_for
from .values import instant


def segment_corrections(plan, chosen):
    """Correct every fully-sampled zero segment against its own pair of pans.

    Each segment interpolates between the two empty-pan readings that bracket
    it, so a mid-shift reset never bleeds one segment's zero into another and
    the reset jump itself is never read as drift.  Segments whose readings are
    missing are skipped, which lets a hand-off correct only the rise segment.
    """
    reference = {step["id"]: step["reference_mg"] for step in plan["steps"]}
    corrected, drifts = {}, {}
    for segment_id, anchors, step_keys in segments_for(plan):
        if any(key not in chosen for key in (*anchors, *step_keys)):
            continue
        first, last = (chosen[key] for key in anchors)
        start = instant(first["observed_at"])
        duration = (instant(last["observed_at"]) - start).seconds
        drift = last["indicated_mg"] - first["indicated_mg"]
        drifts[segment_id] = {"drift": drift, "anchors": list(anchors), "span_seconds": duration}
        for key in step_keys:
            row = chosen[key]
            ratio = Fraction((instant(row["observed_at"]) - start).seconds, duration)
            zero = first["indicated_mg"] + ratio * drift
            corrected[key] = {"zero": zero, "indication": row["indicated_mg"] - zero,
                              "error": row["indicated_mg"] - zero - reference[key],
                              "weight": ratio, "segment": segment_id}
    return corrected, drifts


def zero_correct(plan, chosen):
    return segment_corrections(plan, chosen)
