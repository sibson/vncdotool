SERVERS_COMPOSE?=tests/servers/docker-compose.yml
DOCKER_COMPOSE?=docker compose
PYTHON?=python3
SCREENSHOT_DIR?=tests/servers/screenshots
# Which servers `screenshots` captures: docker, os, or all. See
# tests/functional/vncservers.py.
SCREENSHOT_GROUP?=docker

# `up --wait` only gets as far as the containers' HEALTHCHECK, which is
# liveness: the port is bound. wait_for_servers.py is the readiness gate --
# it captures until each server serves the content it should, the same
# assertion the tests make, and the same gate the OS-hosted servers use.
.PHONY: servers-up
servers-up:
	$(DOCKER_COMPOSE) -f $(SERVERS_COMPOSE) up -d --build --wait
	$(PYTHON) tests/functional/wait_for_servers.py docker

.PHONY: servers-down
servers-down:
	$(DOCKER_COMPOSE) -f $(SERVERS_COMPOSE) down

.PHONY: test-servers
test-servers:
	$(PYTHON) -m unittest discover $(UNITTEST_ARGS) -s tests/functional -t . -p 'test_servers.py'

# The VNC server hosted by this OS (UltraVNC on Windows, Screen Sharing on
# macOS), set up beforehand by the scripts in tests/servers/ultravnc and
# tests/servers/screen-sharing.
.PHONY: test-os-server
test-os-server:
	$(PYTHON) -m unittest discover $(UNITTEST_ARGS) -s tests/functional -t . -p 'test_os_servers.py'

# Screenshot every running test server into $(SCREENSHOT_DIR), including an
# index.html gallery of them all, for eyeballing what the servers render.
.PHONY: screenshots
screenshots:
	VNCDOTOOL_SCREENSHOT_DIR=$(SCREENSHOT_DIR) $(PYTHON) tests/functional/capture_screenshots.py $(SCREENSHOT_GROUP)
	@echo "open $(SCREENSHOT_DIR)/index.html"
