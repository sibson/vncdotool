.PHONY: upload release release-test release-tag upload docs
.DEFAULT: help

help:
	@echo "test:		run tests"
	@echo "docs:		build documentation"
	@echo ""
	@echo "version:	show current version"
	@echo "version-M-m-p:	update version to M.m.p"
	@echo "release:	upload a release to pypi"

version:
	python setup.py --version

version-%: OLDVERSION:=$(shell python setup.py --version)
version-%: NEWVERSION=$(subst -,.,$*)
version-%:
	sed -i -e s/$(OLDVERSION)/$(NEWVERSION)/ setup.py
	git ci setup.py -m"bump version to $*"

release: release-test release-tag upload

release-test: test

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
	nosetests tests/unit
