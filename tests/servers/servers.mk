SERVERS_COMPOSE?=tests/servers/docker-compose.yml
DOCKER_COMPOSE?=docker compose
PYTHON?=python3
SCREENSHOT_DIR?=tests/servers/screenshots

.PHONY: servers-up
servers-up:
	$(DOCKER_COMPOSE) -f $(SERVERS_COMPOSE) up -d --build --wait

.PHONY: servers-down
servers-down:
	$(DOCKER_COMPOSE) -f $(SERVERS_COMPOSE) down

.PHONY: test-servers
test-servers:
	$(PYTHON) -m unittest discover $(UNITTEST_ARGS) -s tests/functional -t . -p 'test_servers.py'

# Screenshot every running test server into $(SCREENSHOT_DIR), including an
# index.html gallery of them all, for eyeballing what the servers render.
.PHONY: screenshots
screenshots:
	VNCDOTOOL_SCREENSHOT_DIR=$(SCREENSHOT_DIR) $(PYTHON) tests/functional/capture_screenshots.py
	@echo "open $(SCREENSHOT_DIR)/index.html"
