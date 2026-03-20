# How to release

## Overview

```
Your machine                      GitHub
─────────────────                 ─────────────────────────────
1. Edit VERSION         
2. Edit CHANGELOG.md    
3. git commit           
4. make release  ─── pushes tag ─▶  triggers release.yml
                                         │
                                         ├─ extracts CHANGELOG section
                                         └─ creates GitHub Release
```

No extra tools needed (no `gh` CLI). The tag push is the trigger.

---

## Step by step

### 1. Update `VERSION`

Edit [`VERSION`](VERSION) with the new version number:

```
1.1.0
```

### 2. Update `CHANGELOG.md`

Move the `[Unreleased]` entries into a new dated section and add a comparison link at the bottom:

```markdown
## [Unreleased]

---

## [1.1.0] - 2026-05-01

### Added
- Docker Compose support

[1.1.0]: https://github.com/guillecanizal/trips-workspace/compare/v1.0.0...v1.1.0
```

### 3. Commit

```bash
git add VERSION CHANGELOG.md
git commit -m "chore: release v1.1.0"
git push
```

### 4. Run `make release`

```bash
make release
```

This creates the git tag and pushes it. GitHub Actions (`release.yml`) picks it up and
creates the GitHub Release using the CHANGELOG section as release notes.

---

## Version numbering

This project follows [Semantic Versioning](https://semver.org):

| Change | Version bump | Example |
|---|---|---|
| New features, backwards-compatible | **minor** | `1.0.0 → 1.1.0` |
| Bug fixes only | **patch** | `1.0.0 → 1.0.1` |
| Breaking change to data format or API | **major** | `1.0.0 → 2.0.0` |

---

## If something goes wrong

**Tag already exists locally but not pushed:**
```bash
git push origin v1.1.0
```

**Tag was pushed but release was not created** (Actions failed):
```bash
# Re-run the workflow from the GitHub Actions UI,
# or delete and re-push the tag:
git push --delete origin v1.1.0
git tag -d v1.1.0
make release
```

**Accidentally tagged the wrong commit:**
```bash
git push --delete origin v1.1.0   # delete remote tag
git tag -d v1.1.0                 # delete local tag
# fix whatever is needed, then:
make release
```
