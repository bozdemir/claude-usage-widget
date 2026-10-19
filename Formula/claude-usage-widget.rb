class ClaudeUsageWidget < Formula
  desc "Desktop widget that shows real-time Claude Code usage limits and cost"
  homepage "https://github.com/bozdemir/claude-usage-widget"
  url "https://files.pythonhosted.org/packages/2e/a1/a696ea831bf1b5676ba5d04eff3345e22d155c39c63b5f99fc6d6f5883b2/claude_usage_widget-0.13.3.tar.gz"
  sha256 "0e50a3fa54ebc394ce7dd9ab4c1e2b3aa949e6a0cd602d2f1be8ac29cf684803"
  license "MIT"

  depends_on "python@3.12"

  def install
    # NOTE: Homebrew's `Language::Python::Virtualenv.pip_install` helper
    # passes `--no-binary=:all:` to enforce source-only installs, but
    # PySide6 is distributed exclusively as binary wheels (no sdist) —
    # there's literally nothing pip can build. So we create the venv
    # manually and call pip without the brew wrapper to allow wheels.
    python = Formula["python@3.12"].opt_bin/"python3.12"
    system python, "-m", "venv", libexec
    pip = libexec/"bin/pip"
    system pip, "install", "--upgrade", "pip", "wheel"
    system pip, "install", "PySide6-Essentials>=6.5,<7,!=6.12.0"
    system pip, "install", buildpath
    bin.install_symlink libexec/"bin/claude-usage"
  end

  test do
    assert_match "0.13.3", shell_output("#{bin}/claude-usage --version")
  end
end
