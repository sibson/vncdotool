#!/usr/bin/make -f
.DEFAULT: help

VERSION_FILE?=vncdotool/__init__.py
REQUIREMENTS_TXT?=requirements-dev.txt

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
	./setup.py --version

version-%: OLDVERSION:=$(shell ./setup.py --version)
version-%: NEWVERSION=$(subst -,.,$*)
version-%:
	sed -i '' -e s/$(OLDVERSION)/$(NEWVERSION)/ $(VERSION_FILE)
	git ci $(VERSION_FILE) -m"bump version to $*"

.PHONY: release
release: release-test release-tag upload

.PHONY: release-test
release-test: test-unit #test-func

.PHONY: release-tag
release-tag: VERSION:=$(shell ./setup.py --version)
release-tag:
	git tag -a v$(VERSION) -m"release version $(VERSION)"
	git push --tags

.PHONY: upload
upload:
	./setup.py sdist
	twine upload dist/$(shell ./setup.py --fullname).*

.PHONY: docs
docs:
	$(MAKE) -C docs/ html

.PHONY: test testall test-unit test-func
test: test-unit
testall: test-unit test-func
test-unit:
	$(VENV)/python -m unittest discover tests/unit

include libvncserver.mk

test-func: libvnc-examples test-libvnc

include Makefile.venv
