# Releasing (maintainer checklist)

User-facing install instructions live in the [README](../README.md#installation).
This is the maintainer ritual for cutting a release — every step matters, in order.

1. **Bump the version** in `claude_usage/__init__.py` (`__version__`), the
   `claude-usage --version # X.Y.Z` line in the README install snippet, and add
   the `CHANGELOG.md` section. Patch for fixes, minor for user-visible features.
2. **Run the suite**: `QT_QPA_PLATFORM=offscreen python -m pytest -q`.
3. **Commit, tag, push**:
   ```bash
   git tag -a vX.Y.Z -m "vX.Y.Z — <headline>"
   git push origin main && git push origin vX.Y.Z
   ```
   The tag triggers `.github/workflows/publish.yml`, which builds the sdist +
   wheel and uploads to PyPI (OIDC, no token to manage). Wait for the run to go
   green and for `pip index`/pypi.org to show the new version (~1–2 min of CDN lag).
4. **Create the GitHub Release** for the tag (`gh release create vX.Y.Z --title … --notes …`).
   **Do not skip this**: the in-app update checker polls `releases/latest`, so a
   tag without a Release means users are never notified of the version.
5. **Mirror the Homebrew formula.** Get the sdist URL + SHA straight from PyPI
   (note the *underscored* filename — `claude_usage_widget-X.Y.Z.tar.gz`, not the
   hyphenated project name):
   ```bash
   curl -s https://pypi.org/pypi/claude-usage-widget/X.Y.Z/json \
     | python3 -c "import sys,json; u=[u for u in json.load(sys.stdin)['urls'] if u['packagetype']=='sdist'][0]; print(u['url']); print(u['digests']['sha256'])"
   ```
   (If you must hash by hand, use `curl -fL <url> | shasum -a 256` — the `-f`
   makes a 404 fail loudly instead of hashing the error page.)
   Update `url` + `sha256` + the version in the `test do` block in **both** copies
   of `Formula/claude-usage-widget.rb`:
   - this repo (commit as `build(homebrew): mirror X.Y.Z bump`), and
   - the tap repository (`bozdemir/homebrew-tap`).

   Always bump the formula *after* PyPI serves the version, never before.
