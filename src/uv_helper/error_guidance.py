"""Actionable error guidance for common failure scenarios."""

import platform
import shutil
from dataclasses import dataclass


@dataclass
class ErrorGuidance:
    """Structured error guidance with checks and suggestions."""

    title: str
    checks: list[str]  # Things to check
    fixes: list[str]  # How to fix
    examples: list[str] | None = None  # Example commands


class GuidanceProvider:
    """Provides context-aware guidance for errors."""

    @staticmethod
    def get_git_not_found() -> ErrorGuidance:
        """Guidance when git is not installed."""
        os_name = platform.system()

        fixes = {
            "Linux": [
                "Debian/Ubuntu: sudo apt-get install git",
                "RHEL/CentOS: sudo yum install git",
                "Arch: sudo pacman -S git",
            ],
            "Darwin": ["Homebrew: brew install git", "Xcode: xcode-select --install"],
            "Windows": [
                "Download from: https://git-scm.com/download/win",
                "Or use winget: winget install Git.Git",
            ],
        }.get(os_name, ["Download from: https://git-scm.com/downloads"])

        return ErrorGuidance(
            title="Git is not installed or not in PATH",
            checks=[
                "Verify git is installed: which git (Unix) or where git (Windows)",
                "Check PATH environment variable",
            ],
            fixes=fixes,
            examples=["git --version"],
        )

    @staticmethod
    def get_uv_not_found() -> ErrorGuidance:
        """Guidance when uv is not installed."""
        return ErrorGuidance(
            title="UV is not installed or not in PATH",
            checks=["Verify uv is installed: which uv", "Check PATH includes uv installation directory"],
            fixes=[
                "Install uv: curl -LsSf https://astral.sh/uv/install.sh | sh",
                "Or with pip: pip install uv",
                "Or with pipx: pipx install uv",
            ],
            examples=["uv --version"],
        )

    @staticmethod
    def get_git_clone_failed(url: str, error: str) -> ErrorGuidance:
        """Guidance when git clone fails."""
        checks = [
            f"Repository exists: curl -I {url}",
            "Network connection: ping github.com",
            "Repository is public or you have access",
        ]

        fixes = []

        # Specific guidance based on error message
        if "authentication" in error.lower() or "permission" in error.lower():
            fixes.extend(
                [
                    "For private repos, ensure SSH keys are configured:",
                    "  1. Generate key: ssh-keygen -t ed25519 -C 'your@email.com'",
                    "  2. Add to GitHub: cat ~/.ssh/id_ed25519.pub",
                    "  3. Test: ssh -T git@github.com",
                ]
            )
        elif "not found" in error.lower() or "404" in error:
            fixes.extend(
                [
                    "Verify repository URL is correct",
                    "Check for typos in username/repository name",
                    "Ensure repository exists and is accessible",
                ]
            )
        elif "timeout" in error.lower() or "network" in error.lower():
            fixes.extend(
                [
                    "Check internet connection",
                    "Try different network (VPN may block git)",
                    "Check firewall settings",
                    "Try HTTPS instead of SSH or vice versa",
                ]
            )
        else:
            fixes.extend(
                [
                    f"Try cloning manually to see full error: git clone {url}",
                    "Check git configuration: git config --list",
                ]
            )

        return ErrorGuidance(
            title="Failed to clone repository", checks=checks, fixes=fixes, examples=[f"git clone {url}"]
        )

    @staticmethod
    def get_permission_denied(path: str, operation: str = "access") -> ErrorGuidance:
        """Guidance for permission errors."""
        return ErrorGuidance(
            title=f"Permission denied for {operation}",
            checks=[
                f"Check file permissions: ls -ld {path}",
                f"Check ownership: ls -l {path}",
                "Ensure you have necessary permissions",
            ],
            fixes=[
                f"Fix permissions: chmod u+rw {path}",
                f"Fix ownership: sudo chown $USER {path}",
                "Run with appropriate privileges if needed",
            ],
            examples=[f"ls -la {path}"],
        )

    @staticmethod
    def get_disk_space_full(path: str) -> ErrorGuidance:
        """Guidance when disk is full."""
        return ErrorGuidance(
            title="No space left on device",
            checks=[
                "Check disk space: df -h",
                f"Check directory size: du -sh {path}",
                f"Find large files: du -ah {path} | sort -rh | head -20",
            ],
            fixes=[
                "Free up disk space by removing unnecessary files",
                "Clean package caches: uv cache clean",
                "Remove old repositories: rm -rf ~/.local/share/uv-helper/unused-repo",
                "Clean system: sudo apt-get clean (Debian/Ubuntu)",
            ],
        )

    @staticmethod
    def get_script_not_found(script: str, repo_path: str) -> ErrorGuidance:
        """Guidance when script file not found in repository."""
        return ErrorGuidance(
            title=f"Script '{script}' not found in repository",
            checks=[
                f"List repository files: ls -R {repo_path}",
                "Check if script is in a subdirectory",
                "Verify script name spelling",
            ],
            fixes=[
                f"List all .py files: find {repo_path} -name '*.py'",
                "Use correct path: --script subdir/script.py",
                "Check repository documentation for script locations",
            ],
            examples=[f"find {repo_path} -name '*.py' -type f"],
        )

    @staticmethod
    def get_install_dir_not_in_path(install_dir: str) -> ErrorGuidance:
        """Guidance when install directory not in PATH."""
        shell = shutil.which("bash") or shutil.which("zsh") or "shell"
        shell_name = "bash" if "bash" in shell else "zsh" if "zsh" in shell else "your shell"
        rc_file = "~/.bashrc" if "bash" in shell else "~/.zshrc" if "zsh" in shell else "~/.profile"

        return ErrorGuidance(
            title=f"{install_dir} is not in your PATH",
            checks=["Check current PATH: echo $PATH", f"Verify install directory: ls -ld {install_dir}"],
            fixes=[
                f"Add to {rc_file}:",
                f"  echo 'export PATH=\"{install_dir}:$PATH\"' >> {rc_file}",
                f"Reload {shell_name}: source {rc_file}",
                "Or start a new terminal session",
            ],
            examples=[f"echo $PATH | grep {install_dir}", f"source {rc_file}"],
        )

    @staticmethod
    def format_guidance(guidance: ErrorGuidance) -> str:
        """Format guidance as rich-compatible string."""
        lines = [f"[bold yellow]{guidance.title}[/bold yellow]\n"]

        if guidance.checks:
            lines.append("[cyan]Checks:[/cyan]")
            for check in guidance.checks:
                lines.append(f"  • {check}")
            lines.append("")

        if guidance.fixes:
            lines.append("[cyan]How to fix:[/cyan]")
            for fix in guidance.fixes:
                lines.append(f"  • {fix}")
            lines.append("")

        if guidance.examples:
            lines.append("[cyan]Try these commands:[/cyan]")
            for example in guidance.examples:
                lines.append(f"  $ {example}")

        return "\n".join(lines)
