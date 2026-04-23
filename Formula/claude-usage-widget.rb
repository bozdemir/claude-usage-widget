class ClaudeUsageWidget < Formula
  include Language::Python::Virtualenv

  desc "Desktop widget that shows real-time Claude Code usage limits and cost"
  homepage "https://github.com/bozdemir/claude-usage-widget"
  url "https://files.pythonhosted.org/packages/58/27/589c985a2eeeb47e217dfa9090f9819ac4dec3abbf9e305ca09227d8fc74/claude_usage_widget-0.4.5.tar.gz"
  sha256 "0d5f5b7e255cb516eb469e562b2fc21605f2cc26e9cd6c854434becb2f30eb52"
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
    assert_match "0.4.5", shell_output("#{bin}/claude-usage --version")
  end
end
