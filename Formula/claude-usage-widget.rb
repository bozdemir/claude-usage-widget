class ClaudeUsageWidget < Formula
  desc "Desktop widget that shows real-time Claude Code usage limits and cost"
  homepage "https://github.com/bozdemir/claude-usage-widget"
  url "https://files.pythonhosted.org/packages/26/99/fdead218d430e471cbbc3ac49b65a3809ec6bfeb9cb17acb857ed8ac1cdc/claude_usage_widget-0.9.2.tar.gz"
  sha256 "f747595250f923f61ebbe6750ac32229d3e97aab4be56f1506fdfd9e6f70fbd4"
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
    assert_match "0.9.2", shell_output("#{bin}/claude-usage --version")
  end
end
