"""
Thin wrapper around `lark-cli im +messages-send` for cursor_manager alerts.

Integration: `from lib.lark_notify import LarkNotifier, LarkRecipient, StubLarkNotifier`

See docs/sub_agents_contract.md MODULE C.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass

# Valid kinds for LarkRecipient.value (CLI mapping differs per kind; see _recipient_cli_args).
RecipientKind = str


@dataclass
class LarkRecipient:
    """Alert destination — kind matches how the value should be used with lark-cli."""

    kind: RecipientKind  # "user_id" | "chat_id" | "open_id" | "email"
    value: str


def _recipient_cli_args(recipient: LarkRecipient) -> list[str] | None:
    """Return extra argv fragment: [--user-id X | --chat-id X]. None if unsupported."""
    k = recipient.kind
    v = recipient.value
    if k in ("user_id", "open_id"):
        return ["--user-id", v]
    if k == "chat_id":
        return ["--chat-id", v]
    if k == "email":
        print(
            "LarkNotifier: kind=email is not supported by im +messages-send "
            "(resolve to user open_id via lark-cli contact, then use user_id).",
            file=sys.stderr,
        )
        return None
    print(f"LarkNotifier: unknown recipient.kind={k!r}", file=sys.stderr)
    return None


class LarkNotifier:
    """Wrapper around `lark-cli im +messages-send`. No-op with stderr warning if lark-cli missing."""

    def __init__(
        self,
        cli_path: str = "lark-cli",
        identity: str = "user",
        dry_run: bool = False,
    ):
        self.cli_path = cli_path
        self.identity = identity
        self.dry_run = dry_run

    def is_available(self) -> bool:
        """True if `lark-cli` is on PATH and `lark-cli --version` exits 0 (5s timeout)."""
        if not shutil.which(self.cli_path):
            return False
        try:
            proc = subprocess.run(
                [self.cli_path, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return proc.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False

    def send_text(self, recipient: LarkRecipient, text: str) -> bool:
        return self._send(recipient, text, markdown_mode=False)

    def send_markdown(self, recipient: LarkRecipient, markdown: str) -> bool:
        return self._send(recipient, markdown, markdown_mode=True)

    def _send(self, recipient: LarkRecipient, body: str, *, markdown_mode: bool) -> bool:
        if self.dry_run:
            mode = "markdown" if markdown_mode else "text"
            print(
                f"[dry-run] lark-cli im +messages-send --as {self.identity} "
                f"<{recipient.kind}={recipient.value!r}> --{mode} <{len(body)} chars>",
                file=sys.stderr,
            )
            return True

        if not shutil.which(self.cli_path):
            print(
                f"LarkNotifier: {self.cli_path!r} not on PATH; skipping send.",
                file=sys.stderr,
            )
            return False

        dest = _recipient_cli_args(recipient)
        if dest is None:
            return False

        cmd = [
            self.cli_path,
            "im",
            "+messages-send",
            "--as",
            self.identity,
            *dest,
        ]
        if markdown_mode:
            cmd.extend(["--markdown", body])
        else:
            cmd.extend(["--text", body])

        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired) as e:
            print(f"LarkNotifier: send failed: {e}", file=sys.stderr)
            return False

        if proc.stderr:
            sys.stderr.write(proc.stderr)
        if proc.returncode != 0:
            if proc.stdout:
                sys.stderr.write(proc.stdout)
            return False
        return True


class StubLarkNotifier:
    """Offline stand-in: records last payload, never calls lark-cli."""

    def __init__(self):
        self.last_kind: str | None = None
        self.last_body: str | None = None
        self.last_markdown: bool = False

    def is_available(self) -> bool:
        return True

    def send_text(self, recipient: LarkRecipient, text: str) -> bool:
        self.last_kind = "text"
        self.last_body = text
        self.last_markdown = False
        return True

    def send_markdown(self, recipient: LarkRecipient, markdown: str) -> bool:
        self.last_kind = "markdown"
        self.last_body = markdown
        self.last_markdown = True
        return True


if __name__ == "__main__":
    n = LarkNotifier(dry_run=True)
    ok = n.send_text(LarkRecipient("user_id", "ou_dummy"), "smoke")
    print("OK: lark_notify dry_run" if ok else "FAIL: dry_run")
