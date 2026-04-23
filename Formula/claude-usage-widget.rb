class ClaudeUsageWidget < Formula
  include Language::Python::Virtualenv

  desc "Desktop widget that shows real-time Claude Code usage limits and cost"
  homepage "https://github.com/bozdemir/claude-usage-widget"
  url "https://files.pythonhosted.org/packages/bd/5d/c8e25e12a66e538738ab24673632d6e0ddb55f3123b6f9f3e6acaf020558/claude_usage_widget-0.4.4.tar.gz"
  sha256 "91cf023d25940d34d51ba6d3becb664fb4815e345e6d6aa6a80d1289018f9d55"
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
    assert_match "0.4.4", shell_output("#{bin}/claude-usage --version")
  end
end
