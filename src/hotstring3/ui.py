"""NiceGUI management interface, dialogs and the UI process entry point.

The UI runs in its own process as a native pywebview window.  Closing that
window only ends the UI process; the background listener and tray icon keep
running.  Edits are signalled to the listener through a Windows named event so
triggers reload immediately.
"""

from __future__ import annotations

import logging
import os
import socket
from typing import Any

from nicegui import app, ui

from . import autostart, config, db, executor, models, signals
from .icon import ensure_icon_file
from .powershell import get_powershell_info

log = logging.getLogger(__name__)

EXAMPLE_COMMANDS = [
    ("t", "Type text", "tmyname@example.com"),
    ("s", "PowerShell", "sStart-Process notepad"),
    ("a", "App action", "aopen"),
    ("r", "At startup", "rStart-Process notepad"),
]


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _trigger_error(value: str, current_id: int | None = None) -> str | None:
    """Return a validation message for a trigger, or ``None`` if it is valid."""
    try:
        models.validate_trigger(value)
    except ValueError as exc:
        return str(exc)
    existing = db.get_by_trigger(value)
    if existing is not None and existing.id != current_id:
        return f"Trigger '{value}' already exists (triggers are case-sensitive)."
    return None


def _command_error(value: str) -> str | None:
    """Return a validation message for a command, or ``None`` if it is valid."""
    try:
        executor.parse_command(value)
    except ValueError as exc:
        return str(exc)
    return None


def _event_row(event) -> dict:  # noqa: ANN001
    """Extract the row dictionary emitted by a Quasar table action."""
    args = getattr(event, "args", event)
    if isinstance(args, list):
        return args[0] if args and isinstance(args[0], dict) else {}
    return args if isinstance(args, dict) else {}


class _StatusPanel:
    """Listening badge plus the total HotString count, kept in sync by a timer."""

    def __init__(self) -> None:
        with ui.row().classes("items-center gap-2"):
            self._badge = ui.badge("Listening", color="green-7").props("rounded").classes(
                "text-xs"
            )
            self._count = ui.label("Total: 0").classes("text-xs text-slate-500 whitespace-nowrap")
        self._pause_switch: Any = None
        self._syncing_pause = False
        self.refresh()

    def bind_pause_switch(self, pause_switch: Any) -> None:
        """Keep the settings pause switch in sync with tray-driven changes."""
        self._pause_switch = pause_switch

    def refresh(self) -> None:
        """Re-read the pause flag and row count; safe to call from any UI event."""
        paused = config.is_paused()
        self._badge.set_text("Paused" if paused else "Listening")
        self._badge.props(f"color={'amber-8' if paused else 'green-7'}")
        try:
            total = db.count_hotstrings()
        except Exception:  # noqa: BLE001 - the status line must never break the page
            log.exception("Could not count HotStrings")
            total = 0
        self._count.set_text(f"Total: {total}")

        if (
            self._pause_switch is not None
            and not self._syncing_pause
            and bool(self._pause_switch.value) != paused
        ):
            self._syncing_pause = True
            try:
                self._pause_switch.value = paused
            finally:
                self._syncing_pause = False


def _close_window() -> None:
    """Close the native UI window (the tray keeps the app alive)."""
    try:
        window = getattr(app.native, "main_window", None)
        if window is not None:
            window.destroy()
        else:
            ui.run_javascript("window.close()")  # browser development mode
    except Exception as exc:  # noqa: BLE001
        log.exception("Could not close the UI window")
        ui.notify(f"Could not close the window: {exc}", type="negative")


def _confirm_quit() -> None:
    """Ask for confirmation, then stop the listener, tray and UI process."""
    with ui.dialog() as dialog, ui.card().classes("max-w-md p-6 gap-3 rounded-xl"):
        ui.label("Quit HotString3?").classes("text-lg font-semibold text-slate-800")
        ui.label(
            "This stops the background hotkey listener, removes the system tray icon "
            "and closes this window. Hotkeys will stop working until you start the app again."
        ).classes("text-sm text-slate-600")

        def quit_application() -> None:
            dialog.close()
            if signals.signal_quit():
                ui.notify("Shutting down HotString3…", type="positive")
            else:
                ui.notify(
                    "No running background instance was found; closing this window only.",
                    type="warning",
                )
            ui.timer(0.8, _close_window, once=True)

        with ui.row().classes("w-full justify-end gap-2 mt-2"):
            ui.button("Cancel", on_click=dialog.close).props("flat rounded")
            ui.button(
                "Quit application",
                icon="power_settings_new",
                color="negative",
                on_click=quit_application,
            ).props("unelevated rounded")

    dialog.open()


# ---------------------------------------------------------------------------
# Page sections
# ---------------------------------------------------------------------------


def _render_header() -> _StatusPanel:
    with ui.row().classes("w-full items-center justify-between gap-4"):
        with ui.row().classes("items-center gap-3"):
            with ui.element("div").classes(
                "w-12 h-12 rounded-xl bg-blue-600 flex items-center justify-center shadow-md"
            ):
                ui.icon("bolt", size="28px").classes("text-white")
            with ui.column().classes("gap-0"):
                ui.label("HotString3").classes("text-2xl font-bold text-slate-800 leading-tight")
                ui.label("Type less. Do more.").classes("text-sm text-slate-500")
        with ui.row().classes("items-center gap-3"):
            status = _StatusPanel()
            ui.button("Log folder", icon="folder_open", on_click=_open_log_folder).props(
                "flat dense color=grey-8"
            )
    return status


def _open_log_folder() -> None:
    try:
        config.ensure_dirs()
        os.startfile(config.APP_DIR)  # type: ignore[attr-defined]  # noqa: S606 - Windows only
    except Exception as exc:  # noqa: BLE001
        ui.notify(f"Could not open the log folder: {exc}", type="negative")


def _render_onboarding() -> None:
    with ui.card().classes(
        "w-full rounded-2xl p-8 bg-gradient-to-br from-blue-600 to-indigo-700 text-white shadow-lg border-0"
    ):
        with ui.row().classes("items-center gap-4"):
            with ui.element("div").classes(
                "w-14 h-14 rounded-2xl bg-white/15 flex items-center justify-center"
            ):
                ui.icon("bolt", size="32px").classes("text-white")
            with ui.column().classes("gap-1"):
                ui.label("Welcome to HotString3").classes("text-3xl font-bold")
                ui.label(
                    "Type a short trigger anywhere on Windows and HotString3 does the rest."
                ).classes("text-blue-100")
        with ui.row().classes("gap-2 mt-6 flex-wrap"):
            for prefix, label, _example in EXAMPLE_COMMANDS:
                ui.badge(f"{prefix} · {label}", color="white", text_color="blue-9").props(
                    "rounded"
                ).classes("text-xs")

    with ui.row().classes("w-full gap-6 flex-col lg:flex-row items-stretch"):
        with ui.card().classes("flex-1 rounded-xl p-6 border border-slate-200 shadow-sm"):
            ui.label("How it works").classes("text-lg font-semibold text-slate-800")
            steps = [
                ("1", "Pick a trigger", "2–8 characters, no spaces. Example: ;hs"),
                ("2", "Attach a command", "Type text, run PowerShell, or open this window."),
                ("3", "Type it anywhere", "HotString3 erases the trigger and runs the command."),
            ]
            for number, title, description in steps:
                with ui.row().classes("items-start gap-3 mt-3"):
                    with ui.element("div").classes(
                        "w-7 h-7 shrink-0 rounded-full bg-blue-100 text-blue-700 "
                        "flex items-center justify-center text-sm font-bold"
                    ):
                        ui.label(number)
                    with ui.column().classes("gap-0"):
                        ui.label(title).classes("font-medium text-slate-800")
                        ui.label(description).classes("text-sm text-slate-500")

        with ui.card().classes("flex-1 rounded-xl p-6 border border-slate-200 shadow-sm"):
            ui.label("Command format").classes("text-lg font-semibold text-slate-800")
            ui.label("The first character decides what happens.").classes(
                "text-sm text-slate-500 mb-2"
            )
            for prefix, label, example in EXAMPLE_COMMANDS:
                with ui.row().classes(
                    "items-center justify-between gap-3 py-2 border-b border-slate-100 last:border-0"
                ):
                    with ui.row().classes("items-center gap-2"):
                        ui.label(prefix).classes(
                            "font-mono font-bold text-blue-700 bg-blue-50 rounded px-2 py-0.5"
                        )
                        ui.label(label).classes("text-sm text-slate-700")
                    ui.label(example).classes("font-mono text-xs text-slate-500")

    with ui.card().classes("w-full rounded-xl p-6 border border-slate-200 shadow-sm"):
        ui.label("Create your first HotString").classes("text-lg font-semibold text-slate-800")
        ui.label(
            "This one opens the management window. A space or colon after the prefix is optional, "
            "so aopen and a:open are the same."
        ).classes("text-sm text-slate-500")

        with ui.row().classes("w-full gap-4 mt-2 flex-col sm:flex-row"):
            trigger = (
                ui.input("Trigger", value=";hs")
                .props("outlined dense maxlength=8")
                .classes("w-full sm:w-40")
            )
            description = (
                ui.input("Description", value="Open HotString3")
                .props("outlined dense")
                .classes("flex-1")
            )
        command = (
            ui.input("Command", value="aopen")
            .props("outlined dense")
            .classes("w-full font-mono")
        )
        start_with_windows = ui.checkbox("Start HotString3 when Windows starts", value=True)

        def create_first() -> None:
            error = _trigger_error(trigger.value or "") or _command_error(command.value or "")
            if error:
                ui.notify(error, type="negative")
                return
            try:
                saved = db.upsert_hotstring(
                    trigger.value,
                    description.value or "",
                    command.value,
                    enabled=True,
                    update_existing=False,
                )
            except ValueError as exc:
                ui.notify(str(exc), type="negative")
                return

            if not saved.created:
                ui.notify(
                    f"Trigger '{trigger.value}' already exists. Choose a different one.",
                    type="warning",
                )
                return

            if start_with_windows.value:
                if not autostart.enable():
                    ui.notify(
                        "HotString3 was created, but the start-with-Windows entry could not be written.",
                        type="warning",
                    )
            signals.signal_reload()
            ui.notify("HotString3 created. Try typing ;hs anywhere!", type="positive")
            ui.navigate.reload()

        ui.button("Create HotString", icon="check", on_click=create_first).props(
            "unelevated rounded"
        ).classes("mt-2")

    ui.label(
        "Closing this window hides the UI — HotString3 keeps running in the system tray. "
        "Use the pencil icon to edit triggers or the trash icon to delete them."
    ).classes("text-xs text-slate-500")


def _render_management(status: _StatusPanel) -> None:
    with ui.row().classes("w-full items-center justify-between gap-3 flex-wrap"):
        search = (
            ui.input(placeholder="Search triggers, descriptions or commands…")
            .props("outlined dense clearable")
            .classes("w-full sm:w-96")
        )
        with ui.row().classes("items-center gap-2"):
            ui.button("Add HotString", icon="add", on_click=lambda: open_editor()).props(
                "unelevated rounded"
            )

    columns = [
        {"name": "trigger", "label": "Trigger", "field": "trigger", "align": "left", "sortable": True},
        {"name": "description", "label": "Description", "field": "description", "align": "left", "sortable": True},
        {"name": "command", "label": "Command", "field": "command", "align": "left", "sortable": True},
        {"name": "enabled", "label": "Enabled", "field": "enabled", "align": "center"},
        {"name": "actions", "label": "Actions", "field": "actions", "align": "right"},
    ]
    table = (
        ui.table(columns=columns, rows=[], row_key="id", pagination=10)
        .props("flat bordered separator=horizontal wrap-cells")
        .classes("w-full rounded-xl")
    )
    table.add_slot(
        "body-cell-trigger",
        """
        <q-td key="trigger" :props="props">
          <span class="font-mono font-bold text-blue-700 bg-blue-50 px-2 py-0.5 rounded">
            {{ props.row.trigger }}
          </span>
        </q-td>
        """,
    )
    table.add_slot(
        "body-cell-command",
        """
        <q-td key="command" :props="props">
          <span class="font-mono text-xs text-slate-600 break-all">{{ props.row.command }}</span>
        </q-td>
        """,
    )
    table.add_slot(
        "body-cell-enabled",
        """
        <q-td key="enabled" :props="props">
          <q-icon :name="props.row.enabled ? 'check_circle' : 'cancel'"
                  :color="props.row.enabled ? 'positive' : 'grey-5'" size="20px">
            <q-tooltip>{{ props.row.enabled ? 'Active' : 'Disabled' }}</q-tooltip>
          </q-icon>
        </q-td>
        """,
    )
    table.add_slot(
        "body-cell-actions",
        """
        <q-td key="actions" :props="props">
          <q-btn flat round dense icon="edit" color="primary"
                 @click="$parent.$emit('edit', props.row)">
            <q-tooltip>Edit</q-tooltip>
          </q-btn>
          <q-btn flat round dense icon="delete" color="negative"
                 @click="$parent.$emit('delete', props.row)">
            <q-tooltip>Delete</q-tooltip>
          </q-btn>
        </q-td>
        """,
    )

    empty_label = ui.label("No HotStrings yet. Add one to get started.").classes(
        "text-sm text-slate-500 w-full text-center py-4"
    )
    empty_label.set_visibility(False)

    all_triggers: list[str] = []

    def load_rows() -> list[dict]:
        nonlocal all_triggers
        items = db.list_hotstrings()
        all_triggers = [item.trigger for item in items if item.trigger]
        return [
            {
                "id": item.id,
                "trigger": item.trigger,
                "description": item.description,
                "command": item.command,
                "enabled": item.enabled,
            }
            for item in items
        ]

    def refresh() -> None:
        rows = load_rows()
        query = (search.value or "").strip().lower()
        if query:
            rows = [
                row
                for row in rows
                if query in row["trigger"].lower()
                or query in row["description"].lower()
                or query in row["command"].lower()
            ]
        table.rows = rows
        table.update()
        empty_label.set_visibility(not rows)
        status.refresh()

    def open_editor(existing: dict | None = None) -> None:
        is_edit = existing is not None
        existing_id = existing.get("id") if existing else None

        with ui.dialog() as dialog, ui.card().classes("w-full max-w-xl p-6 gap-3 rounded-xl"):
            ui.label("Edit HotString" if is_edit else "New HotString").classes(
                "text-xl font-semibold text-slate-800"
            )
            trigger = (
                ui.input("Trigger", value=existing.get("trigger", "") if existing else "")
                .props("outlined dense maxlength=8 autofocus")
                .classes("w-full")
                .tooltip("2–8 characters, no spaces, case-sensitive. Example: ;em")
            )
            description = (
                ui.input("Description", value=existing.get("description", "") if existing else "")
                .props("outlined dense")
                .classes("w-full")
            )
            command = (
                ui.textarea("Command", value=existing.get("command", "") if existing else "")
                .props("outlined dense autogrow")
                .classes("w-full font-mono")
                .tooltip("t<text>, s<script>, aopen or r<script>")
            )
            enabled = ui.switch("Enabled", value=bool(existing.get("enabled", True)) if existing else True)
            warning = ui.label("").classes("text-xs text-amber-700")

            def update_warning() -> None:
                value = trigger.value or ""
                if not value:
                    warning.set_text("")
                    return
                conflicts = [
                    other
                    for other in all_triggers
                    if other != (existing.get("trigger") if existing else None)
                    and other.endswith(value)
                ]
                if conflicts:
                    warning.set_text(
                        f"Heads up: {', '.join(sorted(conflicts))} ends with this trigger, "
                        "so this shorter trigger will always fire first."
                    )
                else:
                    warning.set_text("")

            trigger.on_value_change(lambda _event: update_warning())
            update_warning()

            with ui.row().classes("w-full justify-between items-center mt-1"):
                def test_command() -> None:
                    try:
                        parsed = executor.parse_command(command.value or "")
                    except ValueError as exc:
                        ui.notify(str(exc), type="negative")
                        return

                    if parsed.kind == "type":
                        with ui.dialog() as preview, ui.card().classes("max-w-lg p-6 gap-3"):
                            ui.label("Preview (nothing is typed during a test)").classes(
                                "text-sm font-medium text-slate-600"
                            )
                            ui.label(parsed.payload).classes(
                                "font-mono text-sm bg-slate-50 border border-slate-200 "
                                "rounded-lg p-3 whitespace-pre-wrap break-words w-full"
                            )
                            ui.button("Close", on_click=preview.close).props("flat").classes("self-end")
                        preview.open()
                    elif parsed.kind in ("powershell", "startup"):
                        runner = executor.CommandExecutor(
                            on_error=lambda message: ui.notify(message, type="negative")
                        )
                        runner.run_powershell(parsed.payload)
                        ui.notify(
                            "PowerShell command started. Output is written to the log.",
                            type="info",
                        )
                    elif parsed.payload == "open":
                        signals.signal_show_ui()
                        ui.notify("The management window is already open.", type="info")
                    else:
                        ui.notify(f"Unknown internal action '{parsed.payload}'.", type="negative")

                ui.button("Test", icon="play_arrow", on_click=test_command).props("flat rounded")

                def save() -> None:
                    error = _trigger_error(trigger.value or "", existing_id) or _command_error(
                        command.value or ""
                    )
                    if error:
                        ui.notify(error, type="negative")
                        return
                    try:
                        if is_edit and existing_id is not None:
                            db.update_hotstring(
                                existing_id,
                                trigger=trigger.value,
                                description=description.value or "",
                                command=command.value,
                                enabled=bool(enabled.value),
                            )
                            message = "HotString3 updated."
                        else:
                            db.create_hotstring(
                                trigger.value,
                                description.value or "",
                                command.value,
                                enabled=bool(enabled.value),
                            )
                            message = "HotString3 created."
                    except ValueError as exc:
                        ui.notify(str(exc), type="negative")
                        return

                    signals.signal_reload()
                    refresh()
                    dialog.close()
                    ui.notify(message, type="positive")

                ui.button("Cancel", on_click=dialog.close).props("flat rounded")
                ui.button("Save", icon="save", on_click=save).props("unelevated rounded")

        dialog.open()

    def confirm_delete(row: dict) -> None:
        trigger = row.get("trigger", "")

        with ui.dialog() as dialog, ui.card().classes("max-w-md p-6 gap-3 rounded-xl"):
            ui.label(f"Delete '{trigger}'?").classes("text-lg font-semibold text-slate-800")
            ui.label("This HotString3 will stop working immediately. This cannot be undone.").classes(
                "text-sm text-slate-600"
            )

            def delete() -> None:
                ok = db.delete_hotstring(int(row["id"]))
                signals.signal_reload()
                refresh()
                dialog.close()
                ui.notify(
                    "HotString3 deleted." if ok else "HotString3 was already deleted.",
                    type="info" if ok else "warning",
                )

            with ui.row().classes("w-full justify-end gap-2 mt-2"):
                ui.button("Cancel", on_click=dialog.close).props("flat rounded")
                ui.button("Delete", icon="delete", color="negative", on_click=delete).props(
                    "unelevated rounded"
                )

        dialog.open()

    table.on("edit", lambda event: open_editor(_event_row(event)))
    table.on("delete", lambda event: confirm_delete(_event_row(event)))
    search.on_value_change(lambda _event: refresh())

    with ui.card().classes("w-full rounded-xl p-6 border border-slate-200 shadow-sm mt-2"):
        ui.label("Settings").classes("text-lg font-semibold text-slate-800")
        with ui.row().classes("w-full gap-8 flex-col sm:flex-row"):
            start_switch = ui.switch(
                "Start HotString3 when Windows starts", value=autostart.is_enabled()
            )

            def toggle_autostart(event) -> None:  # noqa: ANN001
                wanted = bool(event.value)
                ok = autostart.set_enabled(wanted)
                if not ok:
                    ui.notify("Could not update the Windows startup entry.", type="negative")
                else:
                    ui.notify(
                        "HotString3 will start with Windows."
                        if wanted
                        else "HotString3 will no longer start with Windows.",
                        type="positive",
                    )
                start_switch.value = autostart.is_enabled()

            start_switch.on_value_change(toggle_autostart)

            pause_switch = ui.switch("Pause listening", value=config.is_paused())
            status.bind_pause_switch(pause_switch)

            def toggle_pause(event) -> None:  # noqa: ANN001
                paused = bool(event.value)
                config.set_paused(paused)
                signals.signal_reload()
                status.refresh()
                ui.notify(
                    "Listening paused. Triggers will not fire." if paused else "Listening resumed.",
                    type="info",
                )

            pause_switch.on_value_change(toggle_pause)

        ui.separator().classes("my-2")
        with ui.row().classes("w-full items-center justify-between gap-3 flex-wrap"):
            ui.label(
                "Hiding the window removes it from the taskbar; the listener and tray icon keep running."
            ).classes("text-sm text-slate-500")
            with ui.row().classes("items-center gap-2"):
                ui.button("Hide to tray", icon="visibility_off", on_click=_close_window).props(
                    "flat rounded"
                )
                ui.button(
                    "Quit HotString3",
                    icon="power_settings_new",
                    color="negative",
                    on_click=_confirm_quit,
                ).props("unelevated rounded")

    with ui.column().classes("w-full gap-1 pt-2"):
        ui.label(f"Database: {db.current_db_path()}").classes("text-xs text-slate-400 font-mono")
        ui.label(f"Log: {config.LOG_PATH}").classes("text-xs text-slate-400 font-mono")
        powershell_info = get_powershell_info()
        ui.label(powershell_info.status_text()).classes("text-xs text-slate-400 font-mono")
        ui.label(f"HotString3 {config.APP_VERSION} · Closing this window keeps the app in the tray.").classes(
            "text-xs text-slate-400"
        )

    refresh()


# ---------------------------------------------------------------------------
# Process entry point
# ---------------------------------------------------------------------------


def _native_available() -> bool:
    """Return whether a native pywebview window can be opened."""
    if config.get_env("NO_NATIVE") == "1":
        return False
    try:
        import webview  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return True


def _choose_port() -> int:
    """Pick a free local port for the NiceGUI server."""
    override = config.get_env("UI_PORT")
    if override:
        return int(override)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def register_page(onboarding: bool = False) -> None:
    """Register the ``/`` page that renders the management UI."""

    @ui.page("/")
    def index() -> None:
        with ui.column().classes("w-full max-w-6xl mx-auto p-4 md:p-8 gap-6"):
            status = _render_header()
            ui.timer(1.0, status.refresh)
            if onboarding and db.is_first_run():
                _render_onboarding()
            else:
                _render_management(status)


def run_ui_process(onboarding: bool = False) -> None:
    """Run the NiceGUI UI in a native desktop window (blocking)."""
    config.setup_logging()
    db.init_db()
    icon_path = ensure_icon_file()
    register_page(onboarding)

    native = _native_available()
    port = _choose_port()
    log.info("Starting UI on port %s (native=%s)", port, native)

    ui.run(
        host="127.0.0.1",
        port=port,
        title="HotString3",
        favicon=icon_path or None,
        native=native,
        window_size=config.WINDOW_SIZE,
        reload=False,
        show=not native,
        show_welcome_message=False,
        uvicorn_logging_level="warning",
        dark=False,
        language="en",
    )
