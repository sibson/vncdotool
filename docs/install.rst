Installation
=================

vncdotool is available on PyPI_, so in most cases you should be able to simply run::

    pip install vncdotool

vncdotool relies on a number of libraries, the two major ones are PIL_, the Python Imaging Library and
Twisted_, an asyncronous networking library.
While vncdotool should work with any recent version of these libraries sometimes things break.
If you are having issues getting things to work you can try using a stable set of libraries
and if you aren't already using it, and you should be, use a virtualenv_.::

    pip install virtualenv
    virtualenv venv-vncdotool
    # XXX requirements.txt from vncdotool source tree
    pip install -r requirements.txt
    pip install -e .


.. _virtualenv: http://www.virtualenv.org/
.. _PIL: http://www.pythonware.com/products/pil/
.. _Twisted: http://twistedmatrix.com/
