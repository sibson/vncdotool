Contributing
=============

Code and Issue tracking is provided by Github_.  There is also a mailing list setup via `Google Groups`_.

Development environment
------------------------

``make`` builds a virtualenv in ``.venv`` beside the ``Makefile`` and
installs vncdotool into it in editable mode::

    make test        # unit tests
    make test-func   # functional tests, needs `make servers-up`

Python 3.10 or newer is required. ``make`` uses the first ``python3`` on
``PATH``; pass ``PY`` to choose another::

    make test PY=python3.13

Working with more than one checkout
------------------------------------

Each working tree needs **its own** ``.venv``. Run ``make`` in it and one
is built.

Do not symlink or reuse another checkout's ``.venv``. An editable install
records the path it was created from, so its ``vncdotool``, and the
``vncdo`` console script beside it, still point at the original checkout.
Tests then pass against code from somewhere else, and a change looks
landed when it was never exercised.

The functional suite checks this before it runs anything and fails with
both paths named, because nothing else notices.

.. _Github: https://github.com/sibson/vncdotool
.. _Google Groups: https://groups.google.com/forum/#!forum/vncdotool
