import sys
from unittest.mock import Mock, _importer
from functools import wraps

class _isolate(object):
    def __init__(self, target, excludes=None):
        self.target = target
        self.excludes = []
        if excludes is not None:
            self.excludes = excludes
        self.names_under_test = set(self.get_names_under_test())

    def get_names_under_test(self):
        module = sys.modules[self.target.__module__]
        for name, value in module.__dict__.items():
            if value is self.target or name in self.excludes:
                yield name

    def __enter__(self):
        module_name = self.target.__module__
        self.module = sys.modules[module_name]
        old_module_dict = self.module.__dict__.copy()
        module_keys = set(self.module.__dict__.keys())

        dunders = set([k for k in module_keys
                        if k.startswith('__') and k.endswith('__')])
        replaced_keys = (module_keys - dunders - self.names_under_test)
        for key in replaced_keys:
            self.module.__dict__[key] = Mock()
        self.module.__dict__['__mock_isolated_dict__'] = old_module_dict

    def __exit__(self, *_):
        old_module_dict = self.module.__dict__['__mock_isolated_dict__']
        self.module.__dict__.clear()
        self.module.__dict__.update(old_module_dict)

    def __call__(self, thing, *args, **kwargs):
        if isinstance(thing, type):
            return self.decorate_class(thing)
        else:
            return self.decorate_callable(thing)

    def decorate_callable(self, func):
        @wraps(func)
        def patched(*args, **keywargs):
            # don't use a with here (backwards compatability with 2.5)
            self.__enter__()
            try:
                return func(*args, **keywargs)
            finally:
                self.__exit__()

        if hasattr(func, 'func_code'):
            # not in Python 3
            patched.compat_co_firstlineno = getattr(func, "compat_co_firstlineno",
                                                    func.func_code.co_firstlineno)
        return patched

    def decorate_class(self, klass, *args):
        # wrapping setUp allows further shared customization of mocks
        setup = getattr(klass, 'setUp', None)
        teardown = getattr(klass, 'tearDown', None)
        if not setup:
            setattr(klass, 'setUp', self.start)
        else:
            def wrap_setup(*args):
                self.start()
                setup(*args)
            setattr(klass, setup.__name__, wrap_setup)

        if not teardown:
            setattr(klass, 'tearDown', self.stop)
        else:
            def wrap_teardown(*args):
                self.stop()
                teardown(*args)
            setattr(klass, teardown.__name__, wrap_teardown)

        return klass

    start = __enter__
    stop = __exit__


def isolate(target, excludes=None):
    """
    ``isolate`` acts as a function decorator, class decorator or
    context manager.  Within the function, TestCase methods or context all
    objects within the targets module will be patched with a new ``Mock``
    object.  On exiting the function or context the patch is undone.  For a
    ``TestCase`` setUp and tearDown are wrapped.

    ``isolate`` is useful to quickly mock out everything in a module except
    the ``target``.

    ``excludes`` is either a string of form `'package.module.objectname'` or
    a list of such strings.   The named objects will not be patched.

    If applied to a TestCase ``isolate`` will wrap the setUp and tearDown
    methods.  This allows configuration of the mocked module attributes
    during setUp.

    ``isolate`` borrows heavily from DingusTestCase.
    """
    target = _importer(target)
    return _isolate(target, excludes)


def _isolate_object(*args, **kwargs):
    return _isolate(*args, **kwargs)


isolate.object = _isolate_object
