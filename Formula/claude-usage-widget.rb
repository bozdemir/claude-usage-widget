class ClaudeUsageWidget < Formula
  include Language::Python::Virtualenv

  desc "Desktop widget that shows real-time Claude Code usage limits and cost"
  homepage "https://github.com/bozdemir/claude-usage-widget"
  url "https://files.pythonhosted.org/packages/a9/54/13a38aa7454ed4edebb6084d65573a50f649a57bb8741ff0cdf3cefe52c9/claude_usage_widget-0.4.3.tar.gz"
  sha256 "51d32c3d588bc941efe5d71f56c02a52bc629d25b36cce200d880574c6bc547f"
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
    assert_match "0.4.3", shell_output("#{bin}/claude-usage --version")
  end
end
