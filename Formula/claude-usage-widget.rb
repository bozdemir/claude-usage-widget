class ClaudeUsageWidget < Formula
  include Language::Python::Virtualenv

  desc "Desktop widget that shows real-time Claude Code usage limits and cost"
  homepage "https://github.com/bozdemir/claude-usage-widget"
  url "https://files.pythonhosted.org/packages/58/b0/acf4d04cbb45170d4ce73a50fcf1c9f5dd90db13d3867739d397cdcda63b/claude_usage_widget-0.4.1.tar.gz"
  sha256 "b47bcc8e52c8a584acd9d3a30420dd821fd12f979a25f429a67170bbb3334eea"
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
    assert_match "0.4.1", shell_output("#{bin}/claude-usage --version")
  end
end
