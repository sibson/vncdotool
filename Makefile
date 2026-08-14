#!/usr/bin/make -f
.DEFAULT: help

REQUIREMENTS_TXT?=requirements-dev.txt

.PHONY: help
help:
	@echo "test:		run unit tests"
	@echo "test-func:	run functional tests"
	@echo "servers-up:	start the docker VNC test servers"
	@echo "servers-down:	stop the docker VNC test servers"
	@echo "test-servers:	run functional tests against the VNC test servers"
	@echo "test-os-server:	run functional tests against this OS's VNC server"
	@echo "screenshots:	screenshot each running VNC test server into a gallery"
	@echo "docs:		build documentation"
	@echo "release:	tag and push current version to trigger PyPI release"

VERSION := $(shell python -c "import vncdotool; print(vncdotool.__version__.split('.dev')[0])")
NEXT_VERSION := $(shell python -c "v='$(VERSION)'.split('.'); v[-1]=str(int(v[-1])+1); print('.'.join(v)+'.dev0')")

.PHONY: release
release: test-unit
	@echo "Releasing $(VERSION)"
	sed -i'' "s/^$(VERSION) (UNRELEASED)/$(VERSION) ($(shell date +%Y-%m-%d))/" CHANGELOG.rst
	git add CHANGELOG.rst
	git commit -m "Release $(VERSION)"
	git tag v$(VERSION)
	git push origin main v$(VERSION)
	sed -i'' "s/__version__ = .*/__version__ = \"$(NEXT_VERSION)\"/" vncdotool/__init__.py
	printf '$(NEXT_VERSION) (UNRELEASED)\n----------------------\n\n' | cat - CHANGELOG.rst > CHANGELOG.rst.tmp && mv CHANGELOG.rst.tmp CHANGELOG.rst
	git add vncdotool/__init__.py CHANGELOG.rst
	git commit -m "Bump version to $(NEXT_VERSION)"
	git push origin main

.PHONY: docs
docs:
	$(MAKE) -C docs/ html

.PHONY: test testall test-unit
test: test-unit
testall: test-unit test-func
test-unit:
	$(VENV)/python -m unittest discover tests/unit

# Needs `make servers-up`; unreachable servers skip rather than fail, so
# this still runs without docker.
.PHONY: test-func
test-func:
	$(PYTHON) -m unittest discover -s tests/functional -t .

include tests/servers/servers.mk

include Makefile.venv
