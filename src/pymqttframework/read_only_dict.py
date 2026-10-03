from typing import Any


class ReadOnlyDict(dict):
    """A dictionary that cannot be modified after creation."""

    def __readonly__(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("Read only configuration")

    __setitem__ = __readonly__
    __delitem__ = __readonly__
    pop = __readonly__
    popitem = __readonly__
    clear = __readonly__
    update = __readonly__
    setdefault = __readonly__
