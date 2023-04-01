#!/usr/bin/make -f
.DEFAULT: help

VERSION_FILE?=vncdotool/__init__.py
PYTHON?=python3


.PHONY: help
help:
	@echo "test:		run unit tests"
	@echo "test-func:	run functional tests"
	@echo "docs:		build documentation"
	@echo ""
	@echo "version:	show current version"
	@echo "version-M.m.p:	update version to M.m.p"
	@echo "release:	upload a release to pypi"

.PHONY: version
version:
	$(PYTHON) setup.py --version

version-%: OLDVERSION:=$(shell $(PYTHON) setup.py --version)
version-%: NEWVERSION=$(subst -,.,$*)
version-%:
	sed -i '' -e s/$(OLDVERSION)/$(NEWVERSION)/ $(VERSION_FILE)
	git ci $(VERSION_FILE) -m"bump version to $*"

.PHONY: release
release: release-test release-tag upload

.PHONY: release-test
release-test: test-unit #test-func

.PHONY: release-tag
release-tag: VERSION:=$(shell $(PYTHON) setup.py --version)
release-tag:
	git tag -a v$(VERSION) -m"release version $(VERSION)"
	git push --tags

.PHONY: upload
upload:
	$(PYTHON) setup.py sdist
	twine upload dist/$(shell $(PYTHON) setup.py --fullname).*

.PHONY: docs
docs:
	$(MAKE) -C docs/ html

.PHONY: test
test: test-unit
.PHONY: testall
testall: test-unit test-func

.PHONY: test-unit
test-unit:
	$(PYTHON) -m unittest discover tests/unit

include libvncserver.mk

.PHONY: test-func
test-func: libvnc-examples test-libvnc
