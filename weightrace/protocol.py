STEPS = (
    ("zero_in", "首空盘", "zero"),
    ("rise_low", "升程 · 低档", "low"),
    ("rise_high", "升程 · 高档", "high"),
    ("zero_mid_before", "清零前空盘", "zero"),
    ("zero_mid_after", "清零后空盘", "zero"),
    ("fall_low", "回程 · 低档", "low"),
    ("repeat_a", "重复 · 中心 A", "high"),
    ("repeat_b", "重复 · 中心 B", "high"),
    ("repeat_c", "重复 · 中心 C", "high"),
    ("offset_left", "偏载 · 左位", "high"),
    ("offset_right", "偏载 · 右位", "high"),
    ("zero_out", "尾空盘", "zero"),
)

# The two mid-shift pans exist only when a session declares an intermediate reset.
MID_ZERO_KEYS = ("zero_mid_before", "zero_mid_after")
BASE_KEYS = tuple(key for key, _, _ in STEPS if key not in MID_ZERO_KEYS)
STEP_KEYS = frozenset(key for key, _, _ in STEPS)
LIMIT_KEYS = ("indication", "hysteresis", "repeatability", "eccentricity", "drift")

# A hand-off freezes the first (rise) segment: both rise indications plus the
# pans that bracket them.  The reset pan belongs to the second segment.
RISE_SEGMENT = ("zero_in", "rise_low", "rise_high", "zero_mid_before")
FALL_SEGMENT = ("zero_mid_after", "fall_low", "repeat_a", "repeat_b", "repeat_c",
                "offset_left", "offset_right", "zero_out")


def steps_for(loads, mid_zero=False):
    included = STEP_KEYS - set(MID_ZERO_KEYS) if not mid_zero else STEP_KEYS
    return [{"id": key, "label": label, "load": load, **{
        field: loads[load][field] for field in ("reference_mg", "radius_mg")
    }} for key, label, load in STEPS if key in included]


def segments_for(plan):
    """Return the disjoint zero segments of a plan as (id, anchor keys, step keys)."""
    if plan.get("mid_zero"):
        return (("rise", ("zero_in", "zero_mid_before"), RISE_SEGMENT),
                ("fall", ("zero_mid_after", "zero_out"), FALL_SEGMENT))
    return (("full", ("zero_in", "zero_out"), BASE_KEYS),)
