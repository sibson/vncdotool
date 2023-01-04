#!/usr/bin/make -f
.PHONY: upload release release-test release-tag upload docs test
.DEFAULT: help

VERSION_FILE?=vncdotool/__init__.py


help:
	@echo "test:		run unit tests"
	@echo "test-func:	run functional tests"
	@echo "docs:		build documentation"
	@echo ""
	@echo "version:	show current version"
	@echo "version-M.m.p:	update version to M.m.p"
	@echo "release:	upload a release to pypi"

version:
	python setup.py --version

version-%: OLDVERSION:=$(shell python setup.py --version)
version-%: NEWVERSION=$(subst -,.,$*)
version-%:
	sed -i '' -e s/$(OLDVERSION)/$(NEWVERSION)/ $(VERSION_FILE)
	git ci $(VERSION_FILE) -m"bump version to $*"

release: release-test release-tag upload

release-test: test-unit test-func

release-tag: VERSION:=$(shell python setup.py --version)
release-tag:
	git tag -a v$(VERSION) -m"release version $(VERSION)"
	git push --tags

upload:
	python setup.py sdist
	twine upload dist/$(shell python setup.py --fullname).*

docs:
	$(MAKE) -C docs/ html

test: test-unit
testall: test-unit test-func

test-unit:
	python -m unittest discover tests/unit

include libvncserver.mk

test-func: libvnc-examples test-libvnc
