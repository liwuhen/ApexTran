"""CLI rendering helpers."""

from __future__ import annotations

import os
from dataclasses import dataclass

from rich import box
from rich.align import Align
from rich.cells import cell_len
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from backend.channels.message import MessageKind

# Leading marker for assistant replies (no explicit style — the emoji is colored).
ASSISTANT_MARKER = "🍦"

# Solid ice-cream logo, drawn as two tones: a scoop and a waffle cone.
# Lines are bare (no leading padding) and centered at render time.
ApexTran_SCOOP = "\n".join([
    "▄███▄",
    "███████",
    "▝█████▘",
])
ApexTran_CONE = "\n".join([
    "▜███▛",
    "▜█▛",
    "▀",
])

# Block-letter wordmark spelling "ApexTran", for the far-right of the welcome panel.
ApexTran_WORDMARK = "\n".join([
    "▄▀▀ █▀▄ █▀▀ ▄▀▄ █▄ ▄█ █ █",
    "█   █▀▄ █▀  █▀█ █▀█▀█  █ ",
    "▀▀▀ ▀ ▀ ▀▀▀ ▀ ▀ ▀   ▀  ▀ ",
])


def _ApexTran_logo() -> Text:
    logo = Text(justify="center")
    logo.append(ApexTran_SCOOP + "\n", style="bold magenta")
    logo.append(ApexTran_CONE, style="bold yellow")
    return logo


# A box that draws ONLY the inner vertical divider between columns
# (no outer border, no horizontal rules) — used inside the welcome panel.
_SPLIT_BOX = box.Box("    \n  │ \n    \n  │ \n    \n    \n  │ \n    \n")


def _ApexTran_version() -> str:
    try:
        from backend._version import __version__

        # Show only the base release (e.g. 0.1.1), dropping the
        # ".devN+gHASH.dYYYYMMDD" suffix that hatch-vcs derives from git.
        return str(__version__).split("+", 1)[0].split(".dev", 1)[0]
    except Exception:
        return "dev"


@dataclass
class CliRenderer:
    """Rich-based renderer for interactive CLI."""

    console: Console

    def _welcome_panel(self, *, model: str, workspace: str) -> Panel:
        user = os.getenv("USER") or "there"
        version = _ApexTran_version()

        # Left column: centered greeting, logo, and session identity.
        left = Group(
            Text(""),
            Align.center(Text(f"Welcome back {user}!", style="bold")),
            Text(""),
            Align.center(_ApexTran_logo()),
            Align.center(Text(model, style="cyan")),
            Align.center(Text(str(workspace), style="bright_black")),
        )

        # Right column: getting-started tips.
        tips = Text()
        tips.append("Tips for getting started\n\n", style="bold magenta")
        tips.append("• Type ", style="")
        tips.append("'/help'", style="green")
        tips.append(" to list all commands\n")
        tips.append("• Prefix a line with ", style="")
        tips.append("','", style="green")
        tips.append(" to run an internal/shell command\n")
        tips.append("• Press ", style="")
        tips.append("Ctrl-X", style="green")
        tips.append(" to toggle shell mode\n")
        tips.append("• ", style="")
        tips.append("PgUp/PgDn", style="green")
        tips.append(" scroll · ", style="")
        tips.append("Ctrl-T", style="green")
        tips.append(" mouse-scroll · drag to copy\n")
        tips.append("• Type ", style="")
        tips.append("'/quit'", style="green")
        tips.append(" (or Ctrl-D) to exit\n\n")
        tips.append("Just type your message and press Enter to chat.", style="bright_black")

        wordmark = Text(ApexTran_WORDMARK, style="bold magenta", justify="center")

        # Right side = tips + the "ApexTran" wordmark, side by side with NO divider
        # (a borderless grid), so only the info│right split line is drawn.
        right = Table.grid(expand=True, padding=0)
        right.add_column(ratio=1, vertical="middle")
        right.add_column(justify="center", width=27, vertical="middle")
        right.add_row(tips, Align.center(wordmark, vertical="middle"))

        body = Table(box=_SPLIT_BOX, show_header=False, show_edge=False, expand=True, pad_edge=False)
        body.add_column(justify="center", ratio=1, vertical="middle")
        body.add_column(ratio=2, vertical="middle")
        body.add_row(left, right)

        return Panel(
            body,
            title=f"ApexTran v{version}",
            title_align="left",
            border_style="magenta",
            padding=(0, 2),
        )

    def welcome(self, *, model: str, workspace: str) -> None:
        self.console.print(self._welcome_panel(model=model, workspace=workspace))

    def welcome_ansi(self, *, model: str, workspace: str, width: int) -> str:
        """Render the welcome panel to an ANSI string (for the full-screen TUI,
        which can't print to the console — it feeds this through prompt_toolkit's
        ``ANSI`` converter instead)."""
        tmp = Console(width=width, force_terminal=True, color_system="standard")
        with tmp.capture() as cap:
            tmp.print(self._welcome_panel(model=model, workspace=workspace))
        return cap.get()

    def info(self, text: str) -> None:
        if not text.strip():
            return
        self.console.print(Text(text, style="bright_black"))

    def panel(self, kind: MessageKind, text: str) -> Panel:
        title, border_style = self._panel_style(kind)
        return Panel(text, title=title, border_style=border_style)

    def command_output(self, text: str) -> None:
        if not text.strip():
            return
        self.console.print(self.panel("command", text))

    def assistant_output(self, text: str) -> None:
        if not text.strip():
            return
        self.console.print(self._assistant_block(text))

    def _assistant_block(self, text: str) -> Text:
        """Unboxed assistant reply: a leading marker with indented continuation."""
        block = Text()
        lines = text.splitlines() or [""]
        block.append(f"{ASSISTANT_MARKER} ")
        block.append(lines[0])
        indent = " " * (cell_len(ASSISTANT_MARKER) + 1)
        for line in lines[1:]:
            block.append("\n" + indent)
            block.append(line)
        return block

    def error(self, text: str) -> None:
        if not text.strip():
            return
        self.console.print(self.panel("error", text))

    def start_stream(self, kind: MessageKind) -> Live:
        # Stream a bounded, transient plain-text tail (never taller than the
        # viewport, so it can't scroll and leave leftover frames), then print the
        # final block/panel exactly once in finish_stream.
        live = Live(
            Text(""),
            console=self.console,
            auto_refresh=False,
            transient=True,
            vertical_overflow="crop",
        )
        live.start()
        live.refresh()
        return live

    def update_stream(self, live: Live, *, kind: MessageKind, text: str) -> None:
        max_lines = max(1, self.console.size.height - 2)
        tail = "\n".join(text.splitlines()[-max_lines:])
        live.update(Text(tail), refresh=True)

    def finish_stream(self, live: Live, *, kind: MessageKind, text: str) -> None:
        live.stop()  # clears the transient typing region
        if not text.strip():
            return
        if kind == "normal":
            self.console.print(self._assistant_block(text))
        else:
            self.console.print(self.panel(kind, text))

    @staticmethod
    def _panel_style(kind: MessageKind) -> tuple[str, str]:
        match kind:
            case "error":
                return "Error", "red"
            case "command":
                return "Command", "green"
            case _:
                return "Assistant", "blue"
