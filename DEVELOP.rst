

Running Tests
------------------------

unit tests are run with::

    make venv
    make test

The functional tests require libvncserver/examples to be on your path before
running::

    python -m unittest discover tests/functional

The RFB/VNC Protocol
------------------------
There is a community effort to document the protcol, _rfbproto_.

Preparing a Release
------------------------
  1. ensure CHANGELOG.rst contains correct version
  1. make version-new-version-number
  6. add new section to CHANGELOG.rst
  7. update vncdotool/__init__.py version
  8. blog post/twitter

.. _rfbproto: https://github.com/rfbproto/rfbproto/blob/master/rfbproto.rst
