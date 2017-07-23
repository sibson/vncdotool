.PHONY: upload release release-test release-tag upload docs
.DEFAULT: help

help:
	@echo "release:	upload a release to pypi"
	@echo "test:		run tests"
	@echo "docs:		build documentation"

version-%: OLDVERSION:=$(shell python setup.py --version)
version-%: 
	sed -i -e s/$(OLDVERSION)/$*/ setup.py
	git ci setup.py -m"bump version to $*"

release: release-test release-tag upload

release-test:
	tox

release-tag: VERSION:=$(shell python setup.py --version)
release-tag:
	git tag -a v$(VERSION) -m"release version $(VERSION)"
	git push --tags

upload:
	python setup.py sdist
	twine upload dist/$(shell python setup.py --fullname).*

docs:
		$(MAKE) -C docs/ html

test:
	tox
