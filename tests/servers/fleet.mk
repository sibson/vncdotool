FLEET_COMPOSE?=tests/servers/docker-compose.yml
DOCKER_COMPOSE?=docker compose
PYTHON?=python3

.PHONY: servers-up
servers-up:
	$(DOCKER_COMPOSE) -f $(FLEET_COMPOSE) up -d --build --wait

.PHONY: servers-down
servers-down:
	$(DOCKER_COMPOSE) -f $(FLEET_COMPOSE) down

.PHONY: test-fleet
test-fleet:
	$(PYTHON) -m unittest discover $(UNITTEST_ARGS) -s tests/functional -t . -p 'test_fleet.py'
