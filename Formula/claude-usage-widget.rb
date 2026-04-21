class ClaudeUsageWidget < Formula
  include Language::Python::Virtualenv

  desc "Desktop widget that shows real-time Claude Code usage limits and cost"
  homepage "https://github.com/bozdemir/claude-usage-widget"
  url "https://files.pythonhosted.org/packages/source/c/claude-usage-widget/claude-usage-widget-0.2.0.tar.gz"
  # Replace the placeholder SHA after the first PyPI release is published.
  sha256 "REPLACE_WITH_TARBALL_SHA256"
  license "MIT"

  depends_on "python@3.12"

  resource "rumps" do
    url "https://files.pythonhosted.org/packages/source/r/rumps/rumps-0.4.0.tar.gz"
    sha256 "REPLACE_WITH_RUMPS_SHA256"
  end

  resource "pyobjc-core" do
    url "https://files.pythonhosted.org/packages/source/p/pyobjc-core/pyobjc-core-10.0.tar.gz"
    sha256 "REPLACE_WITH_PYOBJC_CORE_SHA256"
  end

  resource "pyobjc-framework-Cocoa" do
    url "https://files.pythonhosted.org/packages/source/p/pyobjc-framework-Cocoa/pyobjc-framework-Cocoa-10.0.tar.gz"
    sha256 "REPLACE_WITH_PYOBJC_COCOA_SHA256"
  end

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match "0.2.0", shell_output("#{bin}/claude-usage --version")
  end
end
