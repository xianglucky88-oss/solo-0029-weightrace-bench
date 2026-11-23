STEPS = (
    ("zero_in", "首空盘", "zero"),
    ("rise_low", "升程 · 低档", "low"),
    ("rise_high", "升程 · 高档", "high"),
    ("fall_low", "回程 · 低档", "low"),
    ("repeat_a", "重复 · 中心 A", "high"),
    ("repeat_b", "重复 · 中心 B", "high"),
    ("repeat_c", "重复 · 中心 C", "high"),
    ("offset_left", "偏载 · 左位", "high"),
    ("offset_right", "偏载 · 右位", "high"),
    ("zero_out", "尾空盘", "zero"),
)

STEP_KEYS = frozenset(key for key, _, _ in STEPS)
LIMIT_KEYS = ("indication", "hysteresis", "repeatability", "eccentricity", "drift")


def steps_for(loads):
    return [{"id": key, "label": label, "load": load, **{
        field: loads[load][field] for field in ("reference_mg", "radius_mg")
    }} for key, label, load in STEPS]
