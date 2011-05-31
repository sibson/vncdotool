# mock.py
# Test tools for mocking and patching.
# Copyright (C) 2007-2011 Michael Foord & the mock team
# E-mail: fuzzyman AT voidspace DOT org DOT uk

# mock 0.8.0
# http://www.voidspace.org.uk/python/mock/

# Released subject to the BSD License
# Please see http://www.voidspace.org.uk/python/license.shtml

# Scripts maintained at http://www.voidspace.org.uk/python/index.shtml
# Comments, suggestions and bug reports welcome.


__all__ = (
    'Mock',
    'MagicMock',
    'mocksignature',
    'patch',
    'sentinel',
    'DEFAULT',
    'ANY',
    'call',
    'create_autospec',
    'FILTER_DIR',
)


__version__ = '0.8.0alpha1'

__unittest = True


import sys

try:
    import inspect
except ImportError:
    # for alternative platforms that
    # may not have inspect
    inspect = None

try:
    BaseException
except NameError:
    # Python 2.4 compatibility
    BaseException = Exception

try:
    from functools import wraps
except ImportError:
    # Python 2.4 compatibility
    def wraps(original):
        def inner(f):
            f.__name__ = original.__name__
            f.__doc__ = original.__doc__
            f.__module__ = original.__module__
            return f
        return inner

try:
    unicode
except NameError:
    # Python 3
    basestring = unicode = str

try:
    long
except NameError:
    # Python 3
    long = int

try:
    _isidentifier = str.isidentifier
except AttributeError:
    # Python 2.X
    import keyword
    import re
    regex = re.compile(r'^[a-z_][a-z0-9_]*$', re.I)
    def _isidentifier(string):
        if string in keyword.kwlist:
            return False
        return regex.match(string)


inPy3k = sys.version_info[0] == 3

self = 'im_self'
builtin = '__builtin__'
if inPy3k:
    self = '__self__'
    builtin = 'builtins'

# hack for Python 3 :-)
_super = super

FILTER_DIR = True


# getsignature and mocksignature heavily "inspired" by
# the decorator module: http://pypi.python.org/pypi/decorator/
# by Michele Simionato

def _getsignature(func, skipfirst):
    if inspect is None:
        raise ImportError('inspect module not available')

    if inspect.isclass(func):
        func = func.__init__
        # will have a self arg
        skipfirst = True
    elif not (inspect.ismethod(func) or inspect.isfunction(func)):
        func = func.__call__

    regargs, varargs, varkwargs, defaults = inspect.getargspec(func)

    # instance methods need to lose the self argument
    if getattr(func, self, None) is not None:
        regargs = regargs[1:]

    _msg = "_mock_ is a reserved argument name, can't mock signatures using _mock_"
    assert '_mock_' not in regargs, _msg
    if varargs is not None:
        assert '_mock_' not in varargs, _msg
    if varkwargs is not None:
        assert '_mock_' not in varkwargs, _msg
    if skipfirst:
        regargs = regargs[1:]

    signature = inspect.formatargspec(regargs, varargs, varkwargs, defaults,
                                      formatvalue=lambda value: "")
    return signature[1:-1], func


def _getsignature2(func, skipfirst):
    if inspect is None:
        raise ImportError('inspect module not available')

    if isinstance(func, ClassTypes):
        try:
            func = func.__init__
        except AttributeError:
            return
        skipfirst = True
    elif not isinstance(func, FunctionTypes):
        func = func.__call__

    try:
        regargs, varargs, varkwargs, defaults = inspect.getargspec(func)
    except TypeError:
        # C function / method, possibly inherited object().__init__
        return

    # instance methods and classmethods need to lose the self argument
    if getattr(func, self, None) is not None:
        regargs = regargs[1:]
    if skipfirst:
        # this condition and the above one are never both True - why?
        regargs = regargs[1:]

    signature = inspect.formatargspec(regargs, varargs, varkwargs, defaults,
                                      formatvalue=lambda value: "")
    return signature[1:-1], func


def _check_signature(func, mock, skipfirst):
    if not _callable(func):
        return

    result = _getsignature2(func, skipfirst)
    if result is None:
        return
    signature, func = result

    src = "lambda self, %s: None" % signature
    checksig = eval(src, {})
    _copy_func_details(func, checksig)
    type(mock)._mock_check_sig = checksig


def _copy_func_details(func, funcopy):
    funcopy.__name__ = func.__name__
    funcopy.__doc__ = func.__doc__
    #funcopy.__dict__.update(func.__dict__)
    funcopy.__module__ = func.__module__
    if not inPy3k:
        funcopy.func_defaults = func.func_defaults
    else:
        funcopy.__defaults__ = func.__defaults__
        funcopy.__kwdefaults__ = func.__kwdefaults__


def _callable(obj):
    if isinstance(obj, ClassTypes):
        return True
    if getattr(obj, '__call__', None) is not None:
        return True
    return False


def _set_signature(mock, original, skipfirst):
    # creates a function with signature (*args, **kwargs) that delegates to a
    # mock. It still does signature checking by calling a lambda with the same
    # signature as the original. This is effectively mocksignature2.
    if not _callable(original):
        return

    skipfirst = isinstance(original, ClassTypes)
    result = _getsignature2(original, skipfirst)
    if result is None:
        # was a C function (e.g. object().__init__ ) that can't be mocked
        return

    signature, func = result

    src = "lambda %s: None" % signature
    context = {'_mock_': mock}
    checksig = eval(src, context)
    _copy_func_details(func, checksig)

    name = original.__name__
    import keyword
    if not _isidentifier(name):
        name = funcopy
    context = {'checksig': checksig, 'mock': mock}
    src = """def %s(*args, **kwargs):
    checksig(*args, **kwargs)
    return mock(*args, **kwargs)""" % name
    exec (src, context)
    funcopy = context[name]
    _setup_func(funcopy, mock)
    return funcopy


def mocksignature(func, mock=None, skipfirst=False):
    """
    mocksignature(func, mock=None, skipfirst=False)

    Create a new function with the same signature as `func` that delegates
    to `mock`. If `skipfirst` is True the first argument is skipped, useful
    for methods where `self` needs to be omitted from the new function.

    If you don't pass in a `mock` then one will be created for you.

    The mock is set as the `mock` attribute of the returned function for easy
    access.

    `mocksignature` can also be used with classes. It copies the signature of
    the `__init__` method.

    When used with callable objects (instances) it copies the signature of the
    `__call__` method.
    """
    if mock is None:
        mock = Mock()
    signature, func = _getsignature(func, skipfirst)
    src = "lambda %(signature)s: _mock_(%(signature)s)" % {
        'signature': signature
    }

    funcopy = eval(src, dict(_mock_=mock))
    _copy_func_details(func, funcopy)
    _setup_func(funcopy, mock)
    return funcopy


def _setup_func(funcopy, mock):
    funcopy.mock = mock
    if not isinstance(mock, Mock):
        return

    def assert_called_with(*args, **kwargs):
        return mock.assert_called_with(*args, **kwargs)
    def assert_called_once_with(*args, **kwargs):
        return mock.assert_called_once_with(*args, **kwargs)
    def reset_mock():
        funcopy.method_calls = []
        mock.reset_mock()
        ret = funcopy.return_value
        if isinstance(ret, Mock) and not ret is mock:
            ret.reset_mock()

    funcopy.called = False
    funcopy.call_count = 0
    funcopy.call_args = None
    funcopy.call_args_list = []
    funcopy.method_calls = []
    funcopy.return_value = mock.return_value
    funcopy.side_effect = mock.side_effect
    funcopy._mock_children = mock._mock_children

    funcopy.assert_called_with = assert_called_with
    funcopy.assert_called_once_with = assert_called_once_with
    funcopy.reset_mock = reset_mock

    mock._mock_signature = funcopy


def _is_magic(name):
    return '__%s__' % name[2:-2] == name


class SentinelObject(object):
    "A unique, named, sentinel object."
    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return '<SentinelObject "%s">' % self.name


class Sentinel(object):
    """Access attributes to return a named object, usable as a sentinel."""
    def __init__(self):
        self._sentinels = {}

    def __getattr__(self, name):
        if name == '__bases__':
            # Without this help(mock) raises an exception
            raise AttributeError
        return self._sentinels.setdefault(name, SentinelObject(name))


sentinel = Sentinel()

DEFAULT = sentinel.DEFAULT


class OldStyleClass:
    pass
ClassType = type(OldStyleClass)


def _copy(value):
    if type(value) in (dict, list, tuple, set):
        return type(value)(value)
    return value


ClassTypes = (type,)
if not inPy3k:
    ClassTypes = (type, ClassType)

_allowed_names = set(['return_value'])

def _mock_signature_property(name):
    _allowed_names.add(name)
    def _get(self):
        sig = self._mock_signature
        if sig is None:
            return getattr(self, '_mock_' + name)
        return getattr(sig, name)
    def _set(self, value):
        sig = self._mock_signature
        if sig is None:
            setattr(self, '_mock_' + name, value)
        else:
            setattr(sig, name, value)

    return property(_get, _set)


class Mock(object):
    """
    Create a new ``Mock`` object. ``Mock`` takes several optional arguments
    that specify the behaviour of the Mock object:

    * ``spec``: This can be either a list of strings or an existing object (a
      class or instance) that acts as the specification for the mock object. If
      you pass in an object then a list of strings is formed by calling dir on
      the object (excluding unsupported magic attributes and methods). Accessing
      any attribute not in this list will raise an ``AttributeError``.

      If ``spec`` is an object (rather than a list of strings) then
      `mock.__class__` returns the class of the spec object. This allows mocks
      to pass `isinstance` tests.

    * ``spec_set``: A stricter variant of ``spec``. If used, attempting to *set*
      or get an attribute on the mock that isn't on the object passed as
      ``spec_set`` will raise an ``AttributeError``.

    * ``side_effect``: A function to be called whenever the Mock is called. See
      the :attr:`Mock.side_effect` attribute. Useful for raising exceptions or
      dynamically changing return values. The function is called with the same
      arguments as the mock, and unless it returns :data:`DEFAULT`, the return
      value of this function is used as the return value.

      Alternatively ``side_effect`` can be an exception class or instance. In
      this case the exception will be raised when the mock is called.

    * ``return_value``: The value returned when the mock is called. By default
      this is a new Mock (created on first access). See the
      :attr:`Mock.return_value` attribute.

    * ``wraps``: Item for the mock object to wrap. If ``wraps`` is not None
      then calling the Mock will pass the call through to the wrapped object
      (returning the real result and ignoring ``return_value``). Attribute
      access on the mock will return a Mock object that wraps the corresponding
      attribute of the wrapped object (so attempting to access an attribute that
      doesn't exist will raise an ``AttributeError``).

      If the mock has an explicit ``return_value`` set then calls are not passed
      to the wrapped object and the ``return_value`` is returned instead.

    * ``name``: If the mock has a name then it will be used in the repr of the
      mock. This can be useful for debugging. The name is propagated to child
      mocks.
    """
    def __new__(cls, *args, **kw):
        # every instance has its own class
        # so we can create magic methods on the
        # class without stomping on other mocks
        new = type(cls.__name__, (cls,), {'__doc__': cls.__doc__})
        return object.__new__(new)


    def __init__(self, spec=None, side_effect=None, return_value=DEFAULT,
                    wraps=None, name=None, spec_set=None, parent=None,
                    _old_name=None, _spec_state=None, **kwargs):
        self._mock_parent = parent
        self._mock_name = name
        self._mock_old_name = _old_name

        self._spec_state = _spec_state

        _spec_class = None
        if spec_set is not None:
            spec = spec_set
            spec_set = True

        if spec is not None and type(spec) is not list:
            if isinstance(spec, ClassTypes):
                _spec_class = spec
            else:
                _spec_class = _get_class(spec)

            spec = dir(spec)

        self._spec_class = _spec_class
        self._spec_set = spec_set
        self._mock_methods = spec
        self._mock_children = {}
        self._mock_return_value = return_value
        self._mock_side_effect = side_effect
        self._mock_wraps = wraps
        self.mock_calls = []
        self._mock_signature = None

        self._mock_called = False
        self._mock_call_args = None
        self._mock_call_count = 0
        self._mock_call_args_list = []

        self.reset_mock()
        self.configure_mock(**kwargs)


    @property
    def __class__(self):
        if self._spec_class is None:
            return type(self)
        return self._spec_class

    called = _mock_signature_property('called')
    call_count = _mock_signature_property('call_count')
    call_args = _mock_signature_property('call_args')
    call_args_list = _mock_signature_property('call_args_list')
    side_effect = _mock_signature_property('side_effect')


    def reset_mock(self):
        "Restore the mock object to its initial state."
        self.called = False
        self.call_args = None
        self.call_count = 0
        self.call_args_list = []
        self.method_calls = []

        for child in self._mock_children.values():
            child.reset_mock()

        ret = self._mock_return_value
        if isinstance(ret, Mock) and ret is not self:
            ret.reset_mock()


    def configure_mock(self, **kwargs):
        """XXX needs docstring"""
        for arg, val in sorted(kwargs.items(),
                               # we sort on the number of dots so that
                               # attributes are set before we set attributes on
                               # attributes
                               key=lambda entry: entry[0].count('.')):
            args = arg.split('.')
            final = args.pop()
            obj = self
            for entry in args:
                obj = getattr(obj, entry)
            setattr(obj, final, val)


    def __get_return_value(self):
        ret = self._mock_return_value
        if self._mock_signature is not None:
            ret = self._mock_signature.return_value

        if ret is DEFAULT:
            ret = self._get_child_mock()
            self.return_value = ret
        return ret


    def __set_return_value(self, value):
        if self._mock_signature is not None:
            self._mock_signature.return_value = value
        else:
            self._mock_return_value = value

    __return_value_doc = "The value to be returned when the mock is called."
    return_value = property(__get_return_value, __set_return_value,
                            __return_value_doc)


    def _mock_check_sig(self, *args, **kwargs):
        # stub method that can be replaced with one with a specific signature
        pass

    def __call__(self, *args, **kwargs):
        self._mock_check_sig(*args, **kwargs)
        return self._mock_call(*args, **kwargs)

    def _mock_call(self, *args, **kwargs):
        self.called = True
        self.call_count += 1
        self.call_args = callargs((args, kwargs))
        self.call_args_list.append(callargs((args, kwargs)))

        parent = self._mock_parent
        name = self._mock_name
        while parent is not None:
            parent.method_calls.append(callargs((name, args, kwargs)))
            if parent._mock_parent is None:
                break
            name = parent._mock_name + '.' + name
            parent = parent._mock_parent

        ret_val = DEFAULT
        if self.side_effect is not None:
            if (isinstance(self.side_effect, BaseException) or
                isinstance(self.side_effect, ClassTypes) and
                issubclass(self.side_effect, BaseException)):
                raise self.side_effect

            ret_val = self.side_effect(*args, **kwargs)
            if ret_val is DEFAULT:
                ret_val = self.return_value

        if self._mock_wraps is not None and self._mock_return_value is DEFAULT:
            return self._mock_wraps(*args, **kwargs)
        if ret_val is DEFAULT:
            ret_val = self.return_value
        return ret_val


    def __getattr__(self, name):
        if name == '_mock_methods':
            raise AttributeError(name)
        elif self._mock_methods is not None:
            if name not in self._mock_methods or name in _all_magics:
                raise AttributeError("Mock object has no attribute %r" % name)
        elif _is_magic(name):
            raise AttributeError(name)

        result = self._mock_children.get(name)
        if result is None:
            wraps = None
            if self._mock_wraps is not None:
                # XXXX should we get the attribute without triggering code
                # execution?
                wraps = getattr(self._mock_wraps, name)
            result = self._get_child_mock(parent=self, name=name, wraps=wraps)
            self._mock_children[name]  = result

        elif isinstance(result, _SpecState):
            result = create_autospec(
                result.spec, result.spec_set, result.inherit, None,
                result.parent, result.name, result.instance
            )
            self._mock_children[name]  = result

        return result


    def __repr__(self):
        if self._mock_name is None and self._spec_class is None:
            return object.__repr__(self)

        name_string = ''
        spec_string = ''
        if self._mock_name is not None:
            def get_name(name):
                if name is None:
                    return 'mock'
                return name
            parent = self._mock_parent
            name = self._mock_name
            while parent is not None:
                name = get_name(parent._mock_name) + '.' + name
                parent = parent._mock_parent
            name_string = ' name=%r' % name
        if self._spec_class is not None:
            spec_string = ' spec=%r'
            if self._spec_set:
                spec_string = ' spec_set=%r'
            spec_string = spec_string % self._spec_class.__name__
        return "<%s%s%s id='%s'>" % (type(self).__name__,
                                      name_string,
                                      spec_string,
                                      id(self))


    def __dir__(self):
        extras = self._mock_methods or []
        from_type = dir(type(self))
        from_dict = list(self.__dict__)

        if FILTER_DIR:
            from_type = [e for e in from_type if not e.startswith('_')]
            from_dict = [e for e in from_dict if not e.startswith('_') or
                         _is_magic(e)]
        return sorted(set(extras + from_type + from_dict +
                          list(self._mock_children)))


    def __setattr__(self, name, value):
        if not 'method_calls' in self.__dict__:
            # allow all attribute setting until initialisation is complete
            return object.__setattr__(self, name, value)

        if (self._spec_set and self._mock_methods is not None and name not in
            self._mock_methods and name not in self.__dict__ and
            name not in _allowed_names):
            raise AttributeError("Mock object has no attribute '%s'" % name)
        if name in _unsupported_magics:
            msg = 'Attempting to set unsupported magic method %r.' % name
            raise AttributeError(msg)
        elif name in _all_magics:
            if self._mock_methods is not None and name not in self._mock_methods:
                raise AttributeError("Mock object has no attribute '%s'" % name)

            if isinstance(value, MagicProxy):
                setattr(type(self), name, value)
                return

            if not isinstance(value, Mock):
                setattr(type(self), name, _get_method(name, value))
                original = value
                real = lambda *args, **kw: original(self, *args, **kw)
                value = mocksignature(value, real, skipfirst=True)
            else:
                setattr(type(self), name, value)
        return object.__setattr__(self, name, value)


    def __delattr__(self, name):
        if name in _all_magics and name in type(self).__dict__:
            delattr(type(self), name)
        return object.__delattr__(self, name)


    def assert_called_with(self, *args, **kwargs):
        """
        assert that the mock was called with the specified arguments.

        Raises an AssertionError if the args and keyword args passed in are
        different to the last call to the mock.
        """
        if self.call_args is None:
            raise AssertionError('Expected: %s\nNot called' % ((args, kwargs),))
        if not self.call_args == (args, kwargs):
            raise AssertionError(
                'Expected: %s\nCalled with: %s' % ((args, kwargs), self.call_args)
            )


    def assert_called_once_with(self, *args, **kwargs):
        """
        assert that the mock was called exactly once and with the specified
        arguments.
        """
        if not self.call_count == 1:
            msg = ("Expected to be called once. Called %s times." %
                   self.call_count)
            raise AssertionError(msg)
        return self.assert_called_with(*args, **kwargs)


    def _get_child_mock(self, **kw):
        klass = type(self).__mro__[1]
        return klass(**kw)



class callargs(tuple):
    """
    A tuple for holding the results of a call to a mock, either in the form
    `(args, kwargs)` or `(name, args, kwargs)`.

    If args or kwargs are empty then a callargs tuple will compare equal to
    a tuple without those values. This makes comparisons less verbose::

        callargs('name', (), {}) == ('name',)
        callargs('name', (1,), {}) == ('name', (1,))
        callargs((), {'a': 'b'}) == ({'a': 'b'},)
    """
    def __eq__(self, other):
        if len(self) == 3:
            if other[0] != self[0]:
                return False
            args_kwargs = self[1:]
            other_args_kwargs = other[1:]
        else:
            args_kwargs = tuple(self)
            other_args_kwargs = other

        if len(other_args_kwargs) == 0:
            other_args, other_kwargs = (), {}
        elif len(other_args_kwargs) == 1:
            if isinstance(other_args_kwargs[0], tuple):
                other_args = other_args_kwargs[0]
                other_kwargs = {}
            else:
                other_args = ()
                other_kwargs = other_args_kwargs[0]
        else:
            other_args, other_kwargs = other_args_kwargs

        return tuple(args_kwargs) == (other_args, other_kwargs)


def _dot_lookup(thing, comp, import_path):
    try:
        return getattr(thing, comp)
    except AttributeError:
        __import__(import_path)
        return getattr(thing, comp)


def _importer(target):
    components = target.split('.')
    import_path = components.pop(0)
    thing = __import__(import_path)

    for comp in components:
        import_path += ".%s" % comp
        thing = _dot_lookup(thing, comp, import_path)
    return thing


class _patch(object):
    def __init__(self, target, attribute, new, spec, create,
                    mocksignature, spec_set, autospec, kwargs):
        self.target = target
        self.attribute = attribute
        self.new = new
        self.spec = spec
        self.create = create
        self.has_local = False
        self.mocksignature = mocksignature
        self.spec_set = spec_set
        self.autospec = autospec
        self.kwargs = kwargs


    def copy(self):
        return _patch(self.target, self.attribute, self.new, self.spec,
                        self.create, self.mocksignature, self.spec_set,
                        self.autospec, self.kwargs)


    def __call__(self, func):
        if isinstance(func, ClassTypes):
            return self.decorate_class(func)
        return self.decorate_callable(func)


    def decorate_class(self, klass):
        for attr in dir(klass):
            attr_value = getattr(klass, attr)
            if attr.startswith("test") and hasattr(attr_value, "__call__"):
                setattr(klass, attr, self.copy()(attr_value))
        return klass


    def decorate_callable(self, func):
        if hasattr(func, 'patchings'):
            func.patchings.append(self)
            return func

        @wraps(func)
        def patched(*args, **keywargs):
            # don't use a with here (backwards compatability with 2.5)
            extra_args = []
            for patching in patched.patchings:
                arg = patching.__enter__()
                if patching.new is DEFAULT:
                    extra_args.append(arg)
            args += tuple(extra_args)
            try:
                return func(*args, **keywargs)
            finally:
                for patching in reversed(getattr(patched, 'patchings', [])):
                    patching.__exit__()

        patched.patchings = [self]
        if hasattr(func, 'func_code'):
            # not in Python 3
            patched.compat_co_firstlineno = getattr(
                func, "compat_co_firstlineno",
                func.func_code.co_firstlineno
            )
        return patched


    def get_original(self):
        target = self.target
        name = self.attribute

        original = DEFAULT
        local = False

        try:
            original = target.__dict__[name]
        except (AttributeError, KeyError):
            original = getattr(target, name, DEFAULT)
        else:
            local = True

        if not self.create and original is DEFAULT:
            raise AttributeError(
                "%s does not have the attribute %r" % (target, name)
            )
        return original, local


    def __enter__(self):
        """Perform the patch."""
        new, spec = self.new, self.spec
        spec_set, autospec = self.spec_set, self.autospec
        kwargs = self.kwargs

        original, local = self.get_original()
        if new is DEFAULT and autospec is False:
            # XXXX what if original is DEFAULT - shouldn't use it as a spec
            inherit = False
            if spec_set == True:
                spec_set = original
                if isinstance(spec_set, ClassTypes):
                    inherit = True
            elif spec == True:
                # set spec to the object we are replacing
                spec = original
                if isinstance(spec, ClassTypes):
                    inherit = True
            new = MagicMock(spec=spec, spec_set=spec_set, **kwargs)
            if inherit:
                new.return_value = Mock(spec=spec, spec_set=spec_set)
        elif autospec is not False:
            # spec is ignored, new *must* be default, spec_set is treated
            # as a boolean. Should we check spec is not None and that spec_set
            # is a bool? mocksignature should also not be used. Should we
            # check this?
            if new is not DEFAULT:
                raise TypeError(
                    "autospec creates the mock for you. Can't specify "
                    "autospec and new."
                )
            spec_set = bool(spec_set)
            _kwargs = {'_name': getattr(original, '__name__', None)}
            if autospec is True:
                autospec = original
            new = create_autospec(autospec, spec_set, inherit=True,
                                  configure=kwargs, **_kwargs)
        elif self.kwargs:
            # can't set keyword args when we aren't creating the mock
            # XXXX If new is a Mock we could call new.configure_mock(**kwargs)
            raise TypeError("Can't pass kwargs to a mock we aren't creating")

        new_attr = new
        if self.mocksignature:
            new_attr = mocksignature(original, new)

        self.temp_original = original
        self.is_local = local
        setattr(self.target, self.attribute, new_attr)
        return new


    def __exit__(self, *_):
        """Undo the patch."""
        if self.is_local and self.temp_original is not DEFAULT:
            setattr(self.target, self.attribute, self.temp_original)
        else:
            delattr(self.target, self.attribute)
            if not self.create and not hasattr(self.target, self.attribute):
                # needed for proxy objects like django settings
                setattr(self.target, self.attribute, self.temp_original)

        del self.temp_original
        del self.is_local

    start = __enter__
    stop = __exit__


def _patch_object(target, attribute, new=DEFAULT, spec=None,
                      create=False, mocksignature=False, spec_set=None,
                      autospec=False, **kwargs):
    """
    patch.object(target, attribute, new=DEFAULT, spec=None, create=False,
                 mocksignature=False, spec_set=None)

    patch the named member (`attribute`) on an object (`target`) with a mock
    object.

    Arguments new, spec, create, mocksignature and spec_set have the same
    meaning as for patch.
    """
    return _patch(target, attribute, new, spec, create, mocksignature,
                  spec_set, autospec, kwargs)


def patch(target, new=DEFAULT, spec=None, create=False, mocksignature=False,
          spec_set=None, autospec=False, **kwargs):
    """
    ``patch`` acts as a function decorator, class decorator or a context
    manager. Inside the body of the function or with statement, the ``target``
    (specified in the form `'PackageName.ModuleName.ClassName'`) is patched
    with a ``new`` object. When the function/with statement exits the patch is
    undone.

    The ``target`` is imported and the specified attribute patched with the new
    object, so it must be importable from the environment you are calling the
    decorator from.

    If ``new`` is omitted, then a new ``Mock`` is created and passed in as an
    extra argument to the decorated function.

    The ``spec`` and ``spec_set`` keyword arguments are passed to the ``Mock``
    if patch is creating one for you.

    In addition you can pass ``spec=True`` or ``spec_set=True``, which causes
    patch to pass in the object being mocked as the spec/spec_set object.

    If ``mocksignature`` is True then the patch will be done with a function
    created by mocking the one being replaced. If the object being replaced is
    a class then the signature of `__init__` will be copied. If the object
    being replaced is a callable object then the signature of `__call__` will
    be copied.

    By default ``patch`` will fail to replace attributes that don't exist. If
    you pass in 'create=True' and the attribute doesn't exist, patch will
    create the attribute for you when the patched function is called, and
    delete it again afterwards. This is useful for writing tests against
    attributes that your production code creates at runtime. It is off by by
    default because it can be dangerous. With it switched on you can write
    passing tests against APIs that don't actually exist!

    Patch can be used as a TestCase class decorator. It works by
    decorating each test method in the class. This reduces the boilerplate
    code when your test methods share a common patchings set.

    Patch can be used with the with statement, if this is available in your
    version of Python. Here the patching applies to the indented block after
    the with statement. If you use "as" then the patched object will be bound
    to the name after the "as"; very useful if `patch` is creating a mock
    object for you.

    `patch.dict(...)` and `patch.object(...)` are available for alternate
    use-cases.
    """
    try:
        target, attribute = target.rsplit('.', 1)
    except (TypeError, ValueError):
        raise TypeError("Need a valid target to patch. You supplied: %r" %
                        (target,))
    target = _importer(target)
    return _patch(target, attribute, new, spec, create, mocksignature,
                  spec_set, autospec, kwargs)



class _patch_dict(object):
    """
    Patch a dictionary and restore the dictionary to its original state after
    the test.

    `in_dict` can be a dictionary or a mapping like container. If it is a
    mapping then it must at least support getting, setting and deleting items
    plus iterating over keys.

    `in_dict` can also be a string specifying the name of the dictionary, which
    will then be fetched by importing it.

    `values` can be a dictionary of values to set in the dictionary. `values`
    can also be an iterable of ``(key, value)`` pairs.

    If `clear` is True then the dictionary will be cleared before the new
    values are set.
    """

    def __init__(self, in_dict, values=(), clear=False, **kwargs):
        if isinstance(in_dict, basestring):
            in_dict = _importer(in_dict)
        self.in_dict = in_dict
        # support any argument supported by dict(...) constructor
        self.values = dict(values)
        self.values.update(kwargs)
        self.clear = clear
        self._original = None


    def __call__(self, f):
        if isinstance(f, ClassTypes):
            return self.decorate_class(f)
        @wraps(f)
        def _inner(*args, **kw):
            self._patch_dict()
            try:
                return f(*args, **kw)
            finally:
                self._unpatch_dict()

        return _inner


    def decorate_class(self, klass):
        for attr in dir(klass):
            attr_value = getattr(klass, attr)
            if attr.startswith("test") and hasattr(attr_value, "__call__"):
                decorator = _patch_dict(self.in_dict, self.values, self.clear)
                decorated = decorator(attr_value)
                setattr(klass, attr, decorated)
        return klass


    def __enter__(self):
        """Patch the dict."""
        self._patch_dict()


    def _patch_dict(self):
        """Unpatch the dict."""
        values = self.values
        in_dict = self.in_dict
        clear = self.clear

        try:
            original = in_dict.copy()
        except AttributeError:
            # dict like object with no copy method
            # must support iteration over keys
            original = {}
            for key in in_dict:
                original[key] = in_dict[key]
        self._original = original

        if clear:
            _clear_dict(in_dict)

        try:
            in_dict.update(values)
        except AttributeError:
            # dict like object with no update method
            for key in values:
                in_dict[key] = values[key]


    def _unpatch_dict(self):
        in_dict = self.in_dict
        original = self._original

        _clear_dict(in_dict)

        try:
            in_dict.update(original)
        except AttributeError:
            for key in original:
                in_dict[key] = original[key]


    def __exit__(self, *args):
        self._unpatch_dict()
        return False

    start = __enter__
    stop = __exit__


def _clear_dict(in_dict):
    try:
        in_dict.clear()
    except AttributeError:
        keys = list(in_dict)
        for key in keys:
            del in_dict[key]


patch.object = _patch_object
patch.dict = _patch_dict


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
        if isinstance(thing, ClassTypes):
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


magic_methods = (
    "lt le gt ge eq ne "
    "getitem setitem delitem "
    "len contains iter "
    "hash str sizeof "
    "enter exit "
    "divmod neg pos abs invert "
    "complex int float index "
    "trunc floor ceil "
)

numerics = "add sub mul div truediv floordiv mod lshift rshift and xor or pow "
inplace = ' '.join('i%s' % n for n in numerics.split())
right = ' '.join('r%s' % n for n in numerics.split())
extra = ''
if inPy3k:
    extra = 'bool next '
else:
    extra = 'unicode long nonzero oct hex '
# __truediv__ and __rtruediv__ not available in Python 3 either

# not including __prepare__, __instancecheck__, __subclasscheck__
# (as they are metaclass methods)
# __del__ is not supported at all as it causes problems if it exists

_non_defaults = set('__%s__' % method for method in [
    'cmp', 'getslice', 'setslice', 'coerce', 'subclasses',
    'format', 'get', 'set', 'delete', 'reversed',
    'missing', 'reduce', 'reduce_ex', 'getinitargs',
    'getnewargs', 'getstate', 'setstate', 'getformat',
    'setformat', 'repr', 'dir'
])


def _get_method(name, func):
    "Turns a callable object (like a mock) into a real function"
    def method(self, *args, **kw):
        return func(self, *args, **kw)
    method.__name__ = name
    return method


_magics = set(
    '__%s__' % method for method in
    ' '.join([magic_methods, numerics, inplace, right, extra]).split()
)

_all_magics = _magics | _non_defaults

_unsupported_magics = set([
    '__getattr__', '__setattr__',
    '__init__', '__new__', '__prepare__'
    '__instancecheck__', '__subclasscheck__',
    '__del__'
])

_calculate_return_value = {
    '__hash__': lambda self: object.__hash__(self),
    '__str__': lambda self: object.__str__(self),
    '__sizeof__': lambda self: object.__sizeof__(self),
    '__unicode__': lambda self: unicode(object.__str__(self)),
}

_side_effect_methods = {
    '__eq__': lambda self: lambda other: self is other,
    '__ne__': lambda self: lambda other: self is not other,
}

_return_values = {
    '__int__': 1,
    '__contains__': False,
    '__len__': 0,
    '__iter__': iter([]),
    '__exit__': False,
    '__complex__': 1j,
    '__float__': 1.0,
    '__bool__': True,
    '__nonzero__': True,
    '__oct__': '1',
    '__hex__': '0x1',
    '__long__': long(1),
    '__index__': 1,
}


def _get_eq(self):
    def __eq__(other):
        ret_val = self.__eq__._mock_return_value
        if ret_val is not DEFAULT:
            return ret_val
        return self is other
    return __eq__

def _get_ne(self):
    def __ne__(other):
        if self.__ne__._mock_return_value is not DEFAULT:
            return DEFAULT
        return self is not other
    return __ne__

_side_effect_methods = {
    '__eq__': _get_eq,
    '__ne__': _get_ne,
}



def _set_return_value(mock, method, name):
    return_value = DEFAULT
    if name in _return_values:
        return_value = _return_values[name]
    elif name in _calculate_return_value:
        try:
            return_value = _calculate_return_value[name](mock)
        except AttributeError:
            # XXXX why do we return AttributeError here?
            #      set it as a side_effect instead?
            return_value = AttributeError(name)
    elif name in _side_effect_methods:
        side_effect = _side_effect_methods[name](mock)
        method.side_effect = side_effect
    if return_value is not DEFAULT:
        method.return_value = return_value



class MagicMock(Mock):
    """
    MagicMock is a subclass of Mock with default implementations
    of most of the magic methods. You can use MagicMock without having to
    configure the magic methods yourself.

    If you use the ``spec`` or ``spec_set`` arguments then *only* magic
    methods that exist in the spec will be created.

    Attributes and the return value of a `MagicMock` will also be `MagicMocks`.
    """
    def __init__(self, *args, **kw):
        _super(MagicMock, self).__init__(*args, **kw)

        these_magics = _magics
        if self._mock_methods is not None:
            these_magics = _magics.intersection(self._mock_methods)

        for entry in these_magics:
            setattr(self, entry, _create_proxy(entry, self))


def _create_proxy(entry, self):
    # could specify parent?
    def create_mock():
        m = MagicMock(name=entry)
        setattr(self, entry, m)
        _set_return_value(self, m, entry)
        return m
    return MagicProxy(create_mock)



class MagicProxy(object):
    def __init__(self, create_mock):
        self.create_mock = create_mock
    def __call__(self, *args, **kwargs):
        m = self.create_mock()
        return m(*args, **kwargs)
    def __get__(self, obj, _type=None):
        return self.create_mock()



class _ANY(object):
    "A helper object that compares equal to everything."

    def __eq__(self, other):
        return True

    def __repr__(self):
        return '<ANY>'

ANY = _ANY()



class _Call(object):
    "Call helper object"

    def __init__(self, name=None):
        self.name = name

    def __call__(self, *args, **kwargs):
        if self.name is None:
            return (args, kwargs)
        return (self.name, args, kwargs)

    def __getattr__(self, attr):
        if self.name is None:
            return _Call(attr)
        name = '%s.%s' % (self.name, attr)
        return _Call(name)

    def __repr__(self):
        if self.name is None:
            return '<call>'
        return '<call %s>' % self.name

call = _Call()



def create_autospec(spec, spec_set=False, inherit=False, configure=None,
                    _parent=None, _name=None, _instance=False):
    """XXXX needs docstring!"""
    if configure is None:
        configure = {}

    if type(spec) == list:
        # can't pass a list instance to the mock constructor as it will be
        # interpreted as a list of strings
        spec = list

    is_type = isinstance(spec, ClassTypes)

    kwargs = {'spec': spec}
    if spec_set:
        kwargs = {'spec_set': spec}
    elif spec is None:
        # None we mock with a normal mock without a spec
        kwargs = {}

    kwargs.update(configure)
    mock = MagicMock(parent=_parent, name=_name, **kwargs)

    if isinstance(spec, FunctionTypes):
        # should only happen at the top level because we don't
        # recurse for functions
        mock = _set_signature(mock, spec, False)
    else:
        _check_signature(spec, mock, is_type)

    if _parent is not None:
        _parent._mock_children[_name] = mock

    if is_type and inherit and not _instance:
        # XXXX could give a name to the return_value mock?
        mock.return_value = create_autospec(spec, spec_set, inherit,
                                            _instance=True)

    for entry in dir(spec):
        if _is_magic(entry):
            continue

        if isinstance(spec, FunctionTypes) and entry in FunctionAttributes:
            # allow a mock to actually be a function from mocksignature
            continue

        # XXXX do we need a better way of getting attributes
        # without triggering code execution (?) Probably not - we need the
        # actual object to mock it so we would rather trigger a property than
        # mock the property descriptor. Likewise we want to mock out
        # dynamically provided attributes.
        original = getattr(spec, entry)

        kwargs = {'spec': original}
        if spec_set:
            kwargs = {'spec_set': original}

        if not isinstance(original, FunctionTypes):
            new = _SpecState(original, spec_set, inherit, mock, entry,
                               _instance)
            mock._mock_children[entry] = new
        else:
            parent = mock
            if isinstance(spec, FunctionTypes):
                parent = mock.mock

            new = MagicMock(parent=parent, name=entry, **kwargs)
            mock._mock_children[entry] = new
            skipfirst = _must_skip(spec, entry, is_type)
            _check_signature(original, new, skipfirst=skipfirst)

        # so functions created with mocksignature become instance methods,
        # *plus* their underlying mock exists in _mock_children of the parent
        # mock. Adding to _mock_children may be unnecessary where we are also
        # setting as an instance attribute?
        if isinstance(new, FunctionTypes):
            setattr(mock, entry, new)

    return mock


def _must_skip(spec, entry, skipfirst):
    if not isinstance(spec, ClassTypes):
        if entry in getattr(spec, '__dict__', {}):
            # instance attribute - shouldn't skip
            return False
        # can't use type because of old style classes
        spec = spec.__class__
    if not hasattr(spec, '__mro__'):
        # old style class: can't have descriptors anyway
        return skipfirst

    for klass in spec.__mro__:
        result = klass.__dict__.get(entry, DEFAULT)
        if result is DEFAULT:
            continue
        if isinstance(result, (staticmethod, classmethod)):
            return False
        return skipfirst

    # shouldn't get here unless attribute dynamically provided
    return skipfirst


def _get_class(obj):
    try:
        return obj.__class__
    except AttributeError:
        # in Python 2, _sre.SRE_Pattern objects have no __class__
        return type(obj)


class _SpecState(object):

    def __init__(self, spec, spec_set=False, inherit=False, parent=None,
                 name=None, ids=None, instance=False):
        self.spec = spec
        self.ids = ids
        self.spec_set = spec_set
        self.inherit = inherit
        self.parent = parent
        self.instance = instance
        self.name = name


FunctionTypes = (
    # python function
    type(create_autospec),
    # instance method
    type(ANY.__eq__),
    # unbound method
    type(_ANY.__eq__),
)

FunctionAttributes = set([
    'func_closure',
    'func_code',
    'func_defaults',
    'func_dict',
    'func_globals',
    'func_name',
])

