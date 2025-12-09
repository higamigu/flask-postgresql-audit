import typing as t

_P = t.ParamSpec("_P")
_R = t.TypeVar("_R")


class hybridmethod(t.Generic[_P, _R]):
    """A decorator which allows definition of a Python object method with both
    instance-level and class-level behavior.

    """

    def __init__(
        self,
        inst_func: t.Callable[t.Concatenate[t.Any, _P], _R],
        cls_func: t.Optional[t.Callable[t.Concatenate[t.Any, _P], _R]] = None,
    ):
        self.inst_func = inst_func
        if cls_func is not None:
            self.classmethod(cls_func)
        else:
            self.classmethod(inst_func)

    def __get__(
        self, instance: t.Optional[object], owner: t.Type[object]
    ) -> t.Callable[t.Concatenate[t.Any, _P], _R]:
        if instance is None:
            return self.cls_func.__get__(owner, owner)
        else:
            return self.inst_func.__get__(instance, owner)

    def classmethod(
        self, cls_func: t.Callable[t.Concatenate[t.Any, _P], _R]
    ) -> "hybridmethod[_P, _R]":
        self.cls_func = cls_func
        if not self.cls_func.__doc__:
            self.cls_func.__doc__ = self.inst_func.__doc__
        return self
