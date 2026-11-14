# COPR "make srpm" build method (Copr project → Packages → SCM, SRPM build method: make_srpm).
# Builds a source RPM from the checked-out commit. The commit tagged v<base_version> builds as a plain release
# (kram-0.1.0-2); any other commit as a snapshot, kram-0.1.0^20261104153012git1a2b3c4-2, so every build sorts newer.
# The commit time (UTC) down to the second: with the date alone, two snapshots of one day were ordered by their
# hashes, and a later one could sort older ("already installed").
# Local use: make -f .copr/Makefile srpm outdir=/tmp/kram-srpm
spec ?= packaging/kram.spec
outdir ?= $(CURDIR)/dist
version := $(shell sed -n 's/^%global base_version[[:space:]]*//p' $(spec))

srpm:
	dnf -y install git-core rpm-build >/dev/null || true
	git config --global --add safe.directory '*'
	mkdir -p $(outdir)
	git archive --format=tar.gz --prefix=kram-$(version)/ -o $(outdir)/kram-$(version).tar.gz HEAD
	# written into the SRPM's spec (a --define would be lost when COPR rebuilds the SRPM)
	if git describe --exact-match --tags --match "v$(version)" HEAD >/dev/null 2>&1; then \
		cp $(spec) $(outdir)/kram.spec; \
	else \
		sed "1i %global snapshot ^$$(TZ=UTC git log -1 --format=%cd --date=format-local:%Y%m%d%H%M%S)git$$(git rev-parse --short HEAD)" \
			$(spec) > $(outdir)/kram.spec; \
	fi
	rpmbuild -bs $(outdir)/kram.spec --define "_sourcedir $(outdir)" --define "_srcrpmdir $(outdir)"

.PHONY: srpm
