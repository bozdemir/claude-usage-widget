class ClaudeUsageWidget < Formula
  include Language::Python::Virtualenv

  desc "Desktop widget that shows real-time Claude Code usage limits and cost"
  homepage "https://github.com/bozdemir/claude-usage-widget"
  url "https://files.pythonhosted.org/packages/a0/cc/a04fcecfad536abd50d3e50b695bc449ca907afc210d7c249fae63905bf5/claude_usage_widget-0.4.2.tar.gz"
  sha256 "c4ddea9de8367f71c19cd57cf5f78b73fdf96ce737530040bc0e4ab94886c512"
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
    assert_match "0.4.2", shell_output("#{bin}/claude-usage --version")
  end
end
