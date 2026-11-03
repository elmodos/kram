# COPR "make srpm" build method (Copr project → Packages → SCM, SRPM build method: make_srpm).
# Builds a source RPM from the checked-out commit, with a snapshot release so every build sorts newer.
# Local use: make -f .copr/Makefile srpm outdir=/tmp/kram-srpm
spec ?= packaging/kram.spec
outdir ?= $(CURDIR)/dist
version := $(shell sed -n 's/^Version:[[:space:]]*//p' $(spec))

srpm:
	dnf -y install git-core rpm-build >/dev/null || true
	git config --global --add safe.directory '*'
	mkdir -p $(outdir)
	git archive --format=tar.gz --prefix=kram-$(version)/ -o $(outdir)/kram-$(version).tar.gz HEAD
	# written into the SRPM's spec (a --define would be lost when COPR rebuilds the SRPM)
	sed "1i %global snapshot .$$(git log -1 --format=%cd --date=format:%Y%m%d)git$$(git rev-parse --short HEAD)" \
		$(spec) > $(outdir)/kram.spec
	rpmbuild -bs $(outdir)/kram.spec --define "_sourcedir $(outdir)" --define "_srcrpmdir $(outdir)"

.PHONY: srpm
