SERVERS_COMPOSE?=tests/servers/docker-compose.yml
DOCKER_COMPOSE?=docker compose
PYTHON?=python3
SCREENSHOT_DIR?=tests/servers/screenshots
# Which servers `screenshots` captures: docker, os, or all. See
# tests/functional/vncservers.py.
SCREENSHOT_GROUP?=docker

.PHONY: servers-up
servers-up:
	$(DOCKER_COMPOSE) -f $(SERVERS_COMPOSE) up -d --build --wait

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
