

Running Tests
------------------------

Unit tests can be quickly run with the following commands::

    virtualenv venv
    . venv/bin/activate

    make test

The functional tests exercise the real ``vncdo`` CLI via ``subprocess.run``
against the Docker Compose VNC test server fleet, so ``vncdotool`` needs to
be installed (e.g. ``pip install -e .``) so ``vncdo`` is on your path, and
the fleet needs to be running::

    make servers-up
    make test-func

A server that isn't reachable is skipped rather than failing the run, so
``make test-func`` also degrades gracefully without Docker.


The RFB/VNC Protocol
------------------------
There is a community effort to document the protcol, _rfbproto_.


Preparing a Release
------------------------
  1. ensure CHANGELOG.rst contains correct version
  1. ``make version-new-version-number``
  1. ``make release``
  1. blog post/twitter

.. _rfbproto: https://github.com/rfbproto/rfbproto/blob/master/rfbproto.rst
