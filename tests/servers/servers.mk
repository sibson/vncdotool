SERVERS_COMPOSE?=tests/servers/docker-compose.yml
DOCKER_COMPOSE?=docker compose
SCREENSHOT_DIR?=tests/servers/screenshots
# Which servers `screenshots` captures: docker, os, or all. See
# tests/functional/utils.py.
SCREENSHOT_GROUP?=docker

# `up --wait` only gets as far as the containers' HEALTHCHECK, which is
# liveness: the port is bound. wait_for_servers.py is the readiness gate --
# it captures until each server serves the content it should, the same
# assertion the tests make, and the same gate the OS-hosted servers use.
.PHONY: servers-up
servers-up:
	$(DOCKER_COMPOSE) -f $(SERVERS_COMPOSE) up -d --build --wait
	uv run python tests/functional/wait_for_servers.py docker

.PHONY: servers-down
servers-down:
	$(DOCKER_COMPOSE) -f $(SERVERS_COMPOSE) down

.PHONY: test-servers
test-servers:
	uv run python -m unittest discover $(UNITTEST_ARGS) -s tests/functional -t . -p 'test_server_compat_docker.py'

# The server native to this machine (UltraVNC on Windows, Screen Sharing on
# macOS, raw QEMU on Linux), set up beforehand by the scripts in
# tests/servers/ultravnc, tests/servers/screen-sharing, and
# tests/servers/qemu-kvm.
.PHONY: test-os-server
test-os-server:
	uv run python -m unittest discover $(UNITTEST_ARGS) -s tests/functional -t . -p 'test_server_compat_native.py'

# The in-process vncdotool.api lifecycle suite, against libvncserver-example
# alone. Runs on its own because one process gets one Twisted reactor -- see
# tests/functional/test_api_lifecycle.py.
.PHONY: test-api
test-api:
	uv run python -m unittest discover $(UNITTEST_ARGS) -s tests/functional -t . -p 'test_api_lifecycle.py'

# Screenshot every running test server into $(SCREENSHOT_DIR), including an
# index.html gallery of them all, for eyeballing what the servers render.
.PHONY: screenshots
screenshots:
	VNCDOTOOL_SCREENSHOT_DIR=$(SCREENSHOT_DIR) uv run python tests/functional/capture_screenshots.py $(SCREENSHOT_GROUP)
	@echo "open $(SCREENSHOT_DIR)/index.html"

.PHONY: goldens
goldens:
	uv run python -m tests.goldens.capture --pixel-format bgrx8888
	uv run python -m tests.goldens.capture --pixel-format rgbx8888

.PHONY: scenes
scenes:
	uv run python -m tests.goldens.scenes
