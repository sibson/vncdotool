#!/usr/bin/make -f
.PHONY: upload release release-test release-tag upload docs test
.DEFAULT: help

VERSION_FILE?=vncdotool/__init__.py
PYTHON?=python3


help:
	@echo "test:		run unit tests"
	@echo "test-func:	run functional tests"
	@echo "docs:		build documentation"
	@echo ""
	@echo "version:	show current version"
	@echo "version-M.m.p:	update version to M.m.p"
	@echo "release:	upload a release to pypi"

version:
	$(PYTHON) setup.py --version

version-%: OLDVERSION:=$(shell $(PYTHON) setup.py --version)
version-%: NEWVERSION=$(subst -,.,$*)
version-%:
	sed -i '' -e s/$(OLDVERSION)/$(NEWVERSION)/ $(VERSION_FILE)
	git ci $(VERSION_FILE) -m"bump version to $*"

release: release-test release-tag upload

release-test: test-unit test-func

release-tag: VERSION:=$(shell $(PYTHON) setup.py --version)
release-tag:
	git tag -a v$(VERSION) -m"release version $(VERSION)"
	git push --tags

upload:
	$(PYTHON) setup.py sdist
	twine upload dist/$(shell $(PYTHON) setup.py --fullname).*

docs:
	$(MAKE) -C docs/ html

test: test-unit
testall: test-unit test-func

test-unit:
	$(PYTHON) -m unittest discover tests/unit

include libvncserver.mk

test-func: libvnc-examples test-libvnc
