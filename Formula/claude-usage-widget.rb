class ClaudeUsageWidget < Formula
  include Language::Python::Virtualenv

  desc "Desktop widget that shows real-time Claude Code usage limits and cost"
  homepage "https://github.com/bozdemir/claude-usage-widget"
  url "https://files.pythonhosted.org/packages/71/9a/48c692410fec46b342b5d9f011edfbbc2687c061a31d14985a98c8e7cef7/claude_usage_widget-0.4.0.tar.gz"
  sha256 "016c1104df7a19d018fa690fdddbeb5ab5cc4655eab75c964df81b2edfa60a43"
  license "MIT"

  depends_on "python@3.12"

  def install
    # PySide6-Essentials ships prebuilt Qt wheels; letting pip resolve it
    # directly is simpler than maintaining resource blocks for the dozens of
    # shiboken / Qt sub-packages.
    venv = virtualenv_create(libexec, "python3.12")
    venv.pip_install "PySide6-Essentials>=6.5,<7"
    venv.pip_install_and_link buildpath
  end

  test do
    assert_match "0.4.0", shell_output("#{bin}/claude-usage --version")
  end
end
