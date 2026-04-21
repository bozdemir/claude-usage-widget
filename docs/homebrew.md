# Homebrew tap (macOS)

```bash
brew tap bozdemir/tap
brew install claude-usage-widget
claude-usage --version
```

The formula pulls the source tarball from PyPI, so the Homebrew release
follows the PyPI release automatically. To publish a new version:

1. Tag and push (`git tag v0.x.y && git push --tags`). The
   `.github/workflows/publish.yml` action uploads to PyPI.
2. Compute the new tarball SHA:
   ```bash
   curl -L https://files.pythonhosted.org/packages/source/c/claude-usage-widget/claude-usage-widget-0.x.y.tar.gz | shasum -a 256
   ```
3. Update `Formula/claude-usage-widget.rb` (url + sha256 + version) in the
   tap repository (`bozdemir/homebrew-tap`) and push.
