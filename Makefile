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
	@echo "test-api:	run the in-process vncdotool.api lifecycle suite"
	@echo "screenshots:	screenshot each running VNC test server into a gallery"
	@echo "coverage:	run both suites under coverage and report"
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

# Unenforced, a too-old python3 surfaces as a pip resolver error about a
# dependency's Requires-Python, which does not read as a wrong interpreter.
PYTHON_FLOOR = 3.10

.PHONY: check-python
check-python:
	@$(PY) -c 'import sys; sys.exit(sys.version_info[:2] < tuple(int(p) for p in "$(PYTHON_FLOOR)".split(".")))' \
	  || { \
	    echo "$(PY) is $$($(PY) -c 'import sys; print("%d.%d" % sys.version_info[:2])'), but this project needs >=$(PYTHON_FLOOR)."; \
	    echo "Point make at a newer one, e.g.:"; \
	    echo "    make $(MAKECMDGOALS) PY=python3.13"; \
	    echo "Do not symlink another checkout's .venv: its editable install"; \
	    echo "points at that checkout, so the tests would exercise its code."; \
	    exit 1; \
	  }

.PHONY: test testall test-unit
test: test-unit
testall: test-unit test-func
test-unit: check-python
	$(VENV)/python -m unittest discover tests/unit

# Needs `make servers-up`; unreachable servers skip rather than fail, so
# this still runs without docker.
# $(VENV) on PATH decides which `vncdo` the tests shell out to. Not
# $(PYTHON): that is a GNU make built-in, python3, not this venv.
# $(abspath ...) because $(VENV) is relative, and a test that runs the CLI
# with a cwd= of its own would resolve it against that directory instead.
.PHONY: test-func
test-func: check-python
	PATH="$(abspath $(VENV)):$$PATH" $(VENV)/python -m unittest discover -s tests/functional -t .

include tests/servers/servers.mk

include Makefile.venv

# Coverage, kept off the plain `test` targets because measuring costs
# runtime not worth paying on every edit-run loop. See DEVELOP.rst.
#
# Below the include because $(VENV) is defined there, and prerequisites
# are expanded where they are written, not where they are used.
.PHONY: coverage coverage-unit coverage-func coverage-report
coverage: coverage-unit coverage-func coverage-report

coverage-unit: check-python | $(VENV)/coverage
	$(VENV)/coverage run --parallel-mode -m unittest discover tests/unit

coverage-func: check-python $(VENV)/.coverage-subprocess-installed
	COVERAGE_PROCESS_START=$(CURDIR)/setup.cfg PATH="$(abspath $(VENV)):$$PATH" \
	  $(VENV)/coverage run --parallel-mode -m unittest discover -s tests/functional -t .

$(VENV)/.coverage-subprocess-installed: | $(VENV)/coverage
	$(VENV)/python -c "import pathlib, sysconfig; \
	  pathlib.Path(sysconfig.get_paths()['purelib'], 'coverage-subprocess.pth') \
	    .write_text('import coverage; coverage.process_startup()\n')"
	$(call touch,$@)

coverage-report: | $(VENV)/coverage
	$(VENV)/coverage combine
	$(VENV)/coverage report
	$(VENV)/coverage html
	@echo "open htmlcov/index.html"
