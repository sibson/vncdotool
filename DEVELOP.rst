Tests
-----------

Unit tests are run with::

    nosetests tests/unit

The functional tests require libvncserver/examples to be on your path before
running::

    nosetests tests/functional


Release
--------
  1. update setup.py with version
  2. ensure CHANGELOG contains correct version
  3. git commit -m"set version"
  4. git tag -a v$VERSION -m "release $VERSION"
  5. python setup.py sdist bdist_wheel register upload
  6. add new section to CHANGELOG
  7. update setup.py version
  8. blog post/twitter
