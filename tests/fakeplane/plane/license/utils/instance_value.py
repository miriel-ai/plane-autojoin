# Plane reads InstanceConfiguration rows and falls back to each key's
# default. Tests set rows in `values`; `fail` makes the read raise.
values = {}
fail = False


def get_configuration_value(keys):
    if fail:
        raise RuntimeError("instance configuration unavailable")
    return tuple(values.get(k["key"], k.get("default")) for k in keys)
