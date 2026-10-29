class ClaudeUsageWidget < Formula
  desc "Desktop widget that shows real-time Claude Code usage limits and cost"
  homepage "https://github.com/bozdemir/claude-usage-widget"
  url "https://files.pythonhosted.org/packages/96/63/859d4f289953769abd5b4bfb75efb65fe9603f85f4fb5cc6c22898bed34b/claude_usage_widget-0.13.8.tar.gz"
  sha256 "f16be8d08b257567d604f5f76bf5a2a8ab19887744ab135ce1c3e32f0c079f0d"
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
    assert_match "0.13.8", shell_output("#{bin}/claude-usage --version")
  end
end
