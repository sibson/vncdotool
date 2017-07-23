Tests
-----------

unit tests are run with::

    nosetests tests/unit

The functional tests require libvncserver/examples to be on your path before
running::

    nosetests tests/functional


Release
--------
  1. ensure CHANGELOG contains correct version
  1. make version-new-version-number
  6. add new section to CHANGELOG
  7. update setup.py version
  8. blog post/twitter
