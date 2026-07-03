import asyncio
import contextlib
import os
from collections.abc import AsyncGenerator, AsyncIterable
from datetime import datetime
from hashlib import md5
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.application import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import ANSI, FormattedText, to_formatted_text
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.containers import HSplit, VSplit, Window
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.layout.scrollable_pane import ScrollablePane
from prompt_toolkit.mouse_events import MouseEvent, MouseEventType
from prompt_toolkit.styles import Style
from prompt_toolkit.utils import get_cwidth
from rich import get_console
from rich.live import Live

from backend.agent.agent import Agent
from backend.channels.base import Channel
from backend.channels.message import ChannelMessage
from backend.channels.renderer import CliRenderer
from backend.core.events import StreamEvent
from backend.memory.tape import TapeInfo
from backend.tools.tools import REGISTRY
from backend.utils.envelope import field_of
from backend.utils.types import MessageHandler

Fragments = list[tuple[str, str]]

# How many lines one mouse-wheel notch scrolls the history.
WHEEL_STEP = 3
# Background for the echoed user-input line, to set it apart from model output.
ECHO_BG = "#3a3a3a"
# Foreground for the cwd prefix (grayish-white) — both the live input line and
# the echoed history line.
PREFIX_FG = "#d0d0d0"


class _ScrollableWindow(Window):
    """Inner history ``Window`` that routes mouse-wheel scroll through a callback."""

    def __init__(self, *args, on_scroll, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._on_scroll = on_scroll

    def _mouse_handler(self, mouse_event: MouseEvent):
        if mouse_event.event_type == MouseEventType.SCROLL_UP:
            self._on_scroll(-WHEEL_STEP)
            return None
        if mouse_event.event_type == MouseEventType.SCROLL_DOWN:
            self._on_scroll(WHEEL_STEP)
            return None
        return super()._mouse_handler(mouse_event)


class _HistoryPane(ScrollablePane):
    """Scrollable viewport for the conversation history.

    A plain ``Window`` cannot scroll read-only content: its render forces
    ``vertical_scroll`` back to 0 to keep the (top-left) cursor of a
    non-focusable ``FormattedTextControl`` visible, so ``vertical_scroll`` never
    sticks. ``ScrollablePane`` renders the child onto an off-screen canvas and
    copies a slice, so an explicit ``vertical_scroll`` actually moves the view.

    We disable its cursor/focus auto-scroll (the focused element is the input
    box, which lives outside this pane — so the pane would otherwise never
    clamp), and clamp ``vertical_scroll`` ourselves each render. ``follow``
    (set by the channel) pins the view to the bottom for live output.
    """

    def __init__(self, content, follow) -> None:
        super().__init__(
            content,
            keep_cursor_visible=False,
            keep_focused_window_visible=False,
            show_scrollbar=True,
            height=Dimension(weight=1),  # fill the space the HSplit leaves us
        )
        self._follow = follow
        self.max_scroll = 0
        self.visible_height = 0
        self.content_width = 0

    def write_to_screen(self, screen, mouse_handlers, write_position, parent_style, erase_bg, z_index) -> None:
        virtual_width = write_position.width - (1 if self.show_scrollbar() else 0)
        virtual_height = self.content.preferred_height(virtual_width, self.max_available_height).preferred
        virtual_height = max(virtual_height, write_position.height)
        virtual_height = min(virtual_height, self.max_available_height)
        self.visible_height = write_position.height
        self.content_width = virtual_width
        self.max_scroll = max(0, virtual_height - write_position.height)
        if self._follow():
            self.vertical_scroll = self.max_scroll
        else:
            self.vertical_scroll = max(0, min(self.vertical_scroll, self.max_scroll))
        super().write_to_screen(screen, mouse_handlers, write_position, parent_style, erase_bg, z_index)


class CliChannel(Channel):
    """Interactive CLI channel.

    Default is a full-screen TUI (clean on resize, in-app scrollback). Set
    ApexTran_SIMPLE=1 for a plain line-based REPL that uses the terminal's native
    scrollback instead (but leaves duplicate prompts when the window is resized).
    """

    name = "cli"
    _stop_event: asyncio.Event

    def __init__(self, on_receive: MessageHandler, agent: Agent) -> None:
        self._on_receive = on_receive
        self._agent = agent
        self._message_template = {
            "chat_id": "cli_chat",
            "channel": self.name,
            "session_id": "cli_session",
        }
        self._mode = "auto"  # or "shell"
        self._main_task: asyncio.Task | None = None
        self._renderer = CliRenderer(get_console())
        self._last_tape_info: TapeInfo | None = None
        self._workspace = self._agent.framework.workspace
        # Full-screen TUI state.
        self._tui = False
        self._tui_app: Application | None = None
        self._tui_buffer: Buffer | None = None
        self._tui_history_pane: _HistoryPane | None = None
        self._tui_lines: list[Fragments] = []
        self._tui_stream_idx: int | None = None
        self._follow_bottom = True
        # Mouse capture is OFF by default so the terminal's own click-drag text
        # Default on for wheel scrolling; Ctrl-T flips it off so native
        # selection / copy works.
        self._mouse_capture = True

    async def _refresh_tape_info(self) -> None:
        tape = self._agent.tapes.session_tape(self._message_template["session_id"], self._workspace)
        info = await self._agent.tapes.info(tape.name)
        self._last_tape_info = info

    def set_metadata(self, session_id: str | None = None, chat_id: str | None = None) -> None:
        if session_id is not None:
            self._message_template["session_id"] = session_id
        if chat_id is not None:
            self._message_template["chat_id"] = chat_id

    async def start(self, stop_event: asyncio.Event) -> None:
        self._stop_event = stop_event
        self._main_task = asyncio.create_task(self._main_loop())

    async def stop(self) -> None:
        if self._main_task is not None:
            self._main_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._main_task

    async def send(self, message: ChannelMessage) -> None:
        if message.kind != "error":
            return
        if self._tui:
            self._tui_lines.append(self._tui_message_fragments("error", message.content))
            self._tui_refresh()
            return
        self._renderer.error(message.content)

    async def _main_loop(self) -> None:
        if os.getenv("ApexTran_SIMPLE"):
            await self._run_simple()
        else:
            await self._run_tui()

    @contextlib.asynccontextmanager
    async def message_lifespan(self, request_completed: asyncio.Event) -> AsyncGenerator[None, None]:
        try:
            yield
        finally:
            await self._refresh_tape_info()
            request_completed.set()
            if self._tui:
                self._tui_refresh()

    def _normalize_input(self, raw: str) -> str:
        if self._mode != "shell":
            return raw
        if raw.startswith("/"):
            return raw
        return f"/{raw}"

    def _prompt_styles(self) -> tuple[str, str]:
        if self._mode == "auto":
            return "fg:ansimagenta bold", "› "
        return "fg:ansiyellow bold", "» "

    def _status_text(self) -> str:
        info = self._last_tape_info
        now = datetime.now().strftime("%H:%M")
        session = field_of(info, "name", None) or self._message_template["session_id"]
        session = session.split("__")[-1]  # tape name is <workspace_hash>__<session_hash>
        parts = [
            now,
            f"model:{self._agent.settings.model}",
            f"mode:{self._mode}",
            f"mouse:{'scroll' if self._mouse_capture else 'select'}",
            f"session:{session}",
        ]
        return "  ·  ".join(parts)

    async def stream_events(
        self, message: ChannelMessage, stream: AsyncIterable[StreamEvent]
    ) -> AsyncIterable[StreamEvent]:
        if self._tui:
            async for event in self._stream_events_tui(message, stream):
                yield event
            return
        live: Live | None = None
        text = ""
        try:
            async for event in stream:
                if event.kind == "text":
                    content = str(event.data.get("delta", ""))
                    if not content.strip() and not text:
                        continue  # skip leading whitespace-only events
                    if live is None:
                        live = self._renderer.start_stream(message.kind)
                    text += content
                    self._renderer.update_stream(live, kind=message.kind, text=text)
                yield event
        finally:
            if live is not None:
                self._renderer.finish_stream(live, kind=message.kind, text=text)

    # ── Full-screen TUI (default) ───────────────────────────────────────────
    async def _run_tui(self) -> None:
        from backend.observability.logging import disable_console_logging

        # Logs to stderr would corrupt the full-screen TUI; keep them in the file sink only.
        disable_console_logging()
        self._tui = True
        await self._refresh_tape_info()

        self._tui_buffer = Buffer(
            completer=self._tool_completer(),
            complete_while_typing=True,
            history=self._file_history(),
            multiline=False,
        )
        self._tui_lines.append(self._tui_welcome_fragments())

        kb = KeyBindings()

        @kb.add("c-x", eager=True)
        def _toggle(event) -> None:
            self._mode = "shell" if self._mode == "auto" else "auto"
            event.app.invalidate()

        @kb.add("c-t", eager=True)
        def _toggle_mouse(event) -> None:
            # Flip between native-selection mode (mouse off → drag-copy works)
            # and scroll mode (mouse on → wheel scrolls the history).
            self._mouse_capture = not self._mouse_capture
            event.app.invalidate()

        @kb.add("c-c")
        def _ctrl_c(event) -> None:
            event.app.exit()

        @kb.add("c-d")
        def _ctrl_d(event) -> None:
            if self._tui_buffer is not None and not self._tui_buffer.text:
                event.app.exit()

        @kb.add("enter")
        def _enter(event) -> None:
            self._tui_accept()

        @kb.add("pageup")
        def _pageup(event) -> None:
            self._scroll(-self._page())

        @kb.add("pagedown")
        def _pagedown(event) -> None:
            self._scroll(self._page())

        input_window = Window(BufferControl(buffer=self._tui_buffer), height=1, wrap_lines=False)
        history_window = _ScrollableWindow(
            FormattedTextControl(self._tui_history_text, focusable=False),
            wrap_lines=True,
            on_scroll=self._scroll,
        )
        self._tui_history_pane = _HistoryPane(history_window, follow=lambda: self._follow_bottom)
        root = HSplit([
            self._tui_history_pane,
            Window(char="─", style="fg:#a8a8a8", height=1),
            VSplit([
                Window(FormattedTextControl(self._tui_line_prefix), dont_extend_width=True, height=1),
                input_window,
            ]),
            VSplit([
                Window(FormattedTextControl(self._tui_status_fragments), dont_extend_width=True, height=1),
                Window(char="─", style="fg:#a8a8a8", height=1),
            ]),
            Window(height=2),  # spacer below the status bar, lifting it off the terminal's bottom edge
        ])
        self._tui_app = Application(
            layout=Layout(root, focused_element=input_window),
            key_bindings=kb,
            full_screen=True,
            mouse_support=Condition(lambda: self._mouse_capture),
        )
        self._tui_refresh()
        try:
            await self._tui_app.run_async()
        finally:
            self._stop_event.set()

    def _tui_accept(self) -> None:
        buff = self._tui_buffer
        if buff is None:
            return
        text = (buff.text or "").strip()
        if text:
            buff.append_to_history()
        buff.reset()
        if not text:
            return
        if text in {"/quit", "/exit"}:
            if self._tui_app is not None:
                self._tui_app.exit()
            return
        self._tui_lines.append(self._tui_echo_fragments(text))
        self._tui_stream_idx = None
        self._follow_bottom = True
        request = self._normalize_input(text)
        message = ChannelMessage(
            session_id=self._message_template["session_id"],
            channel=self._message_template["channel"],
            chat_id=self._message_template["chat_id"],
            content=request,
            lifespan=self.message_lifespan(asyncio.Event()),
        )
        asyncio.create_task(self._on_receive(message))  # noqa: RUF006 - fire-and-forget TUI input dispatch
        self._tui_refresh()

    async def _stream_events_tui(
        self, message: ChannelMessage, stream: AsyncIterable[StreamEvent]
    ) -> AsyncIterable[StreamEvent]:
        text = ""
        idx: int | None = None
        async for event in stream:
            if event.kind == "text":
                content = str(event.data.get("delta", ""))
                if not content.strip() and not text:
                    yield event
                    continue
                text += content
                frags = self._tui_message_fragments(message.kind, text)
                if idx is None:
                    self._tui_lines.append(frags)
                    idx = len(self._tui_lines) - 1
                else:
                    self._tui_lines[idx] = frags
                self._tui_refresh()
            yield event

    def _page(self) -> int:
        pane = self._tui_history_pane
        if pane is not None and pane.visible_height:
            return max(1, pane.visible_height - 1)
        return 10

    def _scroll(self, delta: int) -> None:
        pane = self._tui_history_pane
        if pane is None:
            return
        new = pane.vertical_scroll + delta
        # Re-engage follow-mode only when the user scrolls down to the bottom.
        if new >= pane.max_scroll:
            new = pane.max_scroll
            self._follow_bottom = True
        else:
            self._follow_bottom = False
        pane.vertical_scroll = max(0, new)
        if self._tui_app is not None:
            self._tui_app.invalidate()

    def _tui_refresh(self) -> None:
        # Follow-bottom pinning is applied in _HistoryPane.write_to_screen via the
        # `follow` callback; here we just request a repaint.
        app = self._tui_app
        if app is not None and app.is_running:
            app.invalidate()

    def _tui_history_text(self) -> Fragments:
        out: Fragments = []
        for i, block in enumerate(self._tui_lines):
            if i:
                out.append(("", "\n\n"))
            out.extend(block)
        return out

    def _tui_line_prefix(self) -> Fragments:
        symbol_style, symbol = self._prompt_styles()
        return [(f"fg:{PREFIX_FG}", f"{Path.cwd().name} "), (symbol_style, symbol)]

    def _tui_status_fragments(self) -> Fragments:
        return [("fg:#a8a8a8", "─ "), ("fg:ansimagenta", self._status_text()), ("fg:#a8a8a8", " ")]

    def _tui_echo_fragments(self, text: str) -> Fragments:
        # Echo the user's own input on a gray-background line so it reads as
        # "what I typed", distinct from the model's output (Claude-style).
        symbol_style, symbol = self._prompt_styles()
        bg = f"bg:{ECHO_BG}"
        prefix = f"{Path.cwd().name} "
        frags: Fragments = [
            (f"fg:{PREFIX_FG} {bg}", prefix),
            (f"{symbol_style} {bg}", symbol),
            (bg, text),
        ]
        # Pad with spaces so the background fills the whole row (incl. the last
        # row when the line wraps). Width comes from the pane's last render.
        width = self._tui_history_pane.content_width if self._tui_history_pane else 0
        if width:
            used = get_cwidth(prefix) + get_cwidth(symbol) + get_cwidth(text)
            remainder = used % width
            pad = width - remainder if remainder else 0
            if pad:
                frags.append((bg, " " * pad))
        return frags

    def _tui_message_fragments(self, kind: str, text: str) -> Fragments:
        if kind == "error":
            return [("bold ansired", "✖ "), ("ansired", text)]
        if kind == "command":
            return [("bold ansigreen", "$ "), ("ansigreen", text)]
        lines = text.split("\n")
        frags: Fragments = [("", "🍦 "), ("", lines[0])]
        for line in lines[1:]:
            frags.append(("", "\n   " + line))
        return frags

    def _tui_welcome_fragments(self) -> Fragments:
        # Render the rich welcome panel to ANSI and fold it into the history as
        # prompt_toolkit fragments (full-screen apps can't print to the console).
        # Width = terminal width minus the history scrollbar column.
        width = max(20, get_console().width - 1)
        ansi = self._renderer.welcome_ansi(
            model=self._agent.settings.model, workspace=str(self._workspace), width=width
        )
        return list(to_formatted_text(ANSI(ansi.rstrip("\n"))))  # type: ignore[arg-type]

    # ── Plain REPL (opt-in via ApexTran_SIMPLE) ───────────────────────────────
    async def _run_simple(self) -> None:
        self._prompt = self._build_prompt(self._workspace)
        self._renderer.welcome(model=self._agent.settings.model, workspace=str(self._workspace))
        await self._refresh_tape_info()
        request_completed = asyncio.Event()

        while not self._stop_event.is_set():
            try:
                raw = (await self._prompt.prompt_async(self._prompt_message)).strip()
            except KeyboardInterrupt:
                self._renderer.info("Interrupted. Use '/quit' to exit.")
                continue
            except EOFError:
                break

            if not raw:
                continue
            if raw in {"/quit", "/exit"}:
                break

            self._renderer.console.print()
            request = self._normalize_input(raw)
            message = ChannelMessage(
                session_id=self._message_template["session_id"],
                channel=self._message_template["channel"],
                chat_id=self._message_template["chat_id"],
                content=request,
                lifespan=self.message_lifespan(request_completed),
            )
            await self._on_receive(message)
            await request_completed.wait()
            request_completed.clear()

        self._renderer.info("Bye.")
        self._stop_event.set()

    def _prompt_message(self) -> FormattedText:
        symbol_style, symbol = self._prompt_styles()
        return FormattedText([
            ("fg:ansibrightblack", f"{Path.cwd().name} "),
            (symbol_style, symbol),
        ])

    def _render_bottom_toolbar(self) -> FormattedText:
        return FormattedText([("fg:ansibrightblack", f"  {self._status_text()}")])

    def _build_prompt(self, workspace: Path) -> PromptSession[str]:
        kb = KeyBindings()

        @kb.add("c-x", eager=True)
        def _toggle_mode(event) -> None:
            self._mode = "shell" if self._mode == "auto" else "auto"
            event.app.invalidate()

        return PromptSession(
            completer=self._tool_completer(),
            complete_while_typing=True,
            key_bindings=kb,
            history=self._file_history(),
            bottom_toolbar=self._render_bottom_toolbar,
            style=Style.from_dict({"bottom-toolbar": "noreverse bg:default"}),
        )

    # ── Shared helpers ──────────────────────────────────────────────────────
    def _tool_completer(self) -> WordCompleter:
        def _sort_key(tool_name: str) -> tuple[str, str]:
            section, _, name = tool_name.rpartition(".")
            return (section, name)

        tool_names = sorted((f",{name}" for name in REGISTRY), key=_sort_key)
        return WordCompleter(tool_names, ignore_case=True, sentence=True)

    def _file_history(self) -> FileHistory:
        history_file = self._history_file(self._agent.settings.home, self._workspace)
        history_file.parent.mkdir(parents=True, exist_ok=True)
        return FileHistory(str(history_file))

    @staticmethod
    def _history_file(home: Path, workspace: Path) -> Path:
        workspace_hash = md5(str(workspace).encode("utf-8"), usedforsecurity=False).hexdigest()
        return home / "history" / f"{workspace_hash}.history"
