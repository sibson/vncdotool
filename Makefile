#!/usr/bin/make -f
.DEFAULT: help

ifeq ($(shell command -v uv 2>/dev/null),)
$(error uv is required. Install it with `brew install uv`, `winget install astral-sh.uv`, or https://astral.sh/uv/install.sh)
endif

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
	@echo "goldens:	capture decoder golden fixtures from the fleet"
	@echo "scenes:		regenerate the committed scene PNGs from tests/goldens/scenes.py"
	@echo "coverage:	run both suites under coverage and report"
	@echo "docs:		build documentation"
	@echo "release:	tag and push current version to trigger PyPI release"

VERSION := $(shell uv version --bump stable --dry-run --short --no-sync 2>/dev/null)
NEXT_VERSION := $(shell uv version --bump patch --bump dev=0 --dry-run --short --no-sync 2>/dev/null)

.PHONY: release
release: test-unit
	@echo "Releasing $(VERSION)"
	uv version --bump stable --no-sync
	sd "^$(VERSION) \(UNRELEASED\)" "$(VERSION) ($(shell date +%Y-%m-%d))" CHANGELOG.rst
	git add pyproject.toml CHANGELOG.rst
	git commit -m "Release $(VERSION)"
	git tag v$(VERSION)
	git push origin main v$(VERSION)
	uv version --bump patch --bump dev=0 --no-sync
	printf '$(NEXT_VERSION) (UNRELEASED)\n----------------------\n\n' | cat - CHANGELOG.rst > CHANGELOG.rst.tmp && mv CHANGELOG.rst.tmp CHANGELOG.rst
	git add pyproject.toml CHANGELOG.rst
	git commit -m "Bump version to $(NEXT_VERSION)"
	git push origin main

.PHONY: docs
docs:
	uv run $(MAKE) -C docs/ html

.PHONY: test testall test-unit
test: test-unit
testall: test-unit test-func
test-unit:
	uv run python -m unittest discover tests/unit

# Needs `make servers-up`: an unreachable server fails its tests rather
# than skipping them, so a down fleet cannot pass as green.
.PHONY: test-func
test-func:
	uv run python -m unittest discover -s tests/functional -t .

include tests/servers/servers.mk

# Coverage, kept off the plain `test` targets because measuring costs
# runtime not worth paying on every edit-run loop. See DEVELOP.rst.
.PHONY: coverage coverage-unit coverage-func coverage-report
coverage: coverage-unit coverage-func coverage-report

coverage-unit:
	uv run coverage run --parallel-mode -m unittest discover tests/unit

coverage-func:
	uv run coverage run --parallel-mode -m unittest discover -s tests/functional -t .

coverage-report:
	uv run coverage combine
	uv run coverage report
	uv run coverage html
	@echo "open htmlcov/index.html"
