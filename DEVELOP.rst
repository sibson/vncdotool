

Running Tests
------------------------

``make`` builds a virtualenv in ``.venv`` beside the ``Makefile`` and
installs vncdotool into it in editable mode, so unit tests need nothing
set up first::

    make test

Python 3.10 or newer is required. ``make`` uses the first ``python3`` on
``PATH``; pass ``PY`` to choose another::

    make test PY=python3.13

The functional tests exercise the real ``vncdo`` CLI via ``subprocess.run``
against the Docker Compose VNC test server fleet, which needs to be
running::

    make servers-up
    make test-func

``make test-func`` puts ``.venv`` on ``PATH`` so the ``vncdo`` it shells
out to is the one it just installed. A server that isn't reachable is
skipped rather than failing the run, so this also degrades gracefully
without Docker.

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


The RFB/VNC Protocol
------------------------

Two documents cover RFB, and which one answers a question depends on how
far past the baseline it sits.

`RFC 6143`_ is the normative specification. It defines RFB 3.8 and the
encodings and security types that shipped with it, and it is the one to
cite when the wire format is in dispute.

rfbproto_ is a community effort to document everything servers grew
afterwards: the later encodings and pseudo-encodings, the security types,
the message extensions, and the vendor quirks the RFC never covered.
Reach for it whenever the answer is not in the RFC -- which, for most of
what vncdotool implements, it is not.

rfbproto is a living document with no releases or version numbers, so link
a commit permalink rather than ``master`` when a comment depends on its
wording. Neither document describes how any particular server actually
behaves; where one is known to diverge, ``docs/server-compatibility-plan.md``
records what we do about it.


Preparing a Release
------------------------
  1. ensure CHANGELOG.rst contains correct version
  1. ``make version-new-version-number``
  1. ``make release``
  1. blog post/twitter

.. _RFC 6143: https://www.rfc-editor.org/rfc/rfc6143
.. _rfbproto: https://github.com/rfbproto/rfbproto/blob/master/rfbproto.rst
