VERSION := $(shell cat VERSION)

.PHONY: help version release

help:
	@echo "Trip Planner – release targets"
	@echo ""
	@echo "  make version    Show current version"
	@echo "  make release    Tag and push — GitHub Actions will create the release"
	@echo ""
	@echo "Before running 'make release':"
	@echo "  1. Update VERSION with the new version number"
	@echo "  2. Move [Unreleased] entries to a dated section in CHANGELOG.md"
	@echo "  3. Commit both files"

version:
	@echo "Current version: v$(VERSION)"

release: _check-clean
	@echo "→ Tagging v$(VERSION)..."
	git tag -a v$(VERSION) -m "Release v$(VERSION)"
	git push origin v$(VERSION)
	@echo "✓ Tag v$(VERSION) pushed. GitHub Actions will create the release automatically."
	@echo "  → https://github.com/guillecanizal/trips-workspace/releases"

# ── internal guards ────────────────────────────────────────────────────────────

_check-clean:
	@git diff --quiet && git diff --cached --quiet || { echo "Error: you have uncommitted changes. Commit or stash them first."; exit 1; }
