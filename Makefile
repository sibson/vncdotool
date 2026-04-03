#!/usr/bin/make -f
.DEFAULT: help

REQUIREMENTS_TXT?=requirements-dev.txt

.PHONY: help
help:
	@echo "test:		run unit tests"
	@echo "test-func:	run functional tests"
	@echo "docs:		build documentation"
	@echo "release:	tag and push current version to trigger PyPI release"

VERSION := $(shell python -c "import vncdotool; print(vncdotool.__version__)")

.PHONY: release
release: test-unit
	@echo "Releasing $(VERSION)"
	git tag v$(VERSION)
	git push origin main v$(VERSION)

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
