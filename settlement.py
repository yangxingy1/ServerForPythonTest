_settled = False


def is_settled():
    return _settled


def to_dict():
    return {"settled": _settled}


def from_dict(d):
    global _settled
    _settled = d.get("settled", False)
