import hashlib
import json


def object_pairs(pairs):
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError("JSON 含重复字段")
    return result


def invalid_constant(value):
    raise ValueError(f"无效 JSON 数值：{value}")


def loads(data):
    text = data.decode("utf-8") if isinstance(data, bytes) else data
    value = json.loads(text, object_pairs_hook=object_pairs, parse_constant=invalid_constant)
    # JSON escape sequences can otherwise introduce lone Unicode surrogates.
    canonical(value).encode("utf-8")
    return value


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()
