class ClaudeUsageWidget < Formula
  desc "Desktop widget that shows real-time Claude Code usage limits and cost"
  homepage "https://github.com/bozdemir/claude-usage-widget"
  url "https://files.pythonhosted.org/packages/e3/f0/217de664e65623ff2c1d2a9a12376b267f39def6be5cb319fa793a953352/claude_usage_widget-0.9.1.tar.gz"
  sha256 "9e728a3f0c325d0d83f60c58c53a7d50760f9994f8f32775fc0e2d5307239d14"
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
    system pip, "install", "PySide6-Essentials>=6.5,<7"
    system pip, "install", buildpath
    bin.install_symlink libexec/"bin/claude-usage"
  end

  test do
    assert_match "0.9.1", shell_output("#{bin}/claude-usage --version")
  end
end
