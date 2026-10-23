class ClaudeUsageWidget < Formula
  desc "Desktop widget that shows real-time Claude Code usage limits and cost"
  homepage "https://github.com/bozdemir/claude-usage-widget"
  url "https://files.pythonhosted.org/packages/bd/a2/0b05fb514a6ae1126e77ecd3e1555a8a6cd5927b2b97c616d0b629199c04/claude_usage_widget-0.13.5.tar.gz"
  sha256 "ff2056ffece2f5648fa6029ce627a2b15c412d3e7db02f8a152b49f35e3fc11f"
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
    assert_match "0.13.5", shell_output("#{bin}/claude-usage --version")
  end
end
