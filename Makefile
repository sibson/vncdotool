#!/usr/bin/make -f
.DEFAULT: help

REQUIREMENTS_TXT?=requirements-dev.txt

.PHONY: help
help:
	@echo "test:		run unit tests"
	@echo "test-func:	run functional tests"
	@echo "docs:		build documentation"

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
