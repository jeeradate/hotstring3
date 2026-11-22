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

from nicegui import ui

from . import autostart, config, db, executor, models, signals
from .tray import ensure_icon_file

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


def _status_badge() -> None:
    paused = config.is_paused()
    if paused:
        ui.badge("Paused", color="amber-8").props("rounded").classes("text-xs")
    else:
        ui.badge("Listening", color="green-7").props("rounded").classes("text-xs")


# ---------------------------------------------------------------------------
# Page sections
# ---------------------------------------------------------------------------


def _render_header() -> None:
    with ui.row().classes("w-full items-center justify-between gap-4"):
        with ui.row().classes("items-center gap-3"):
            with ui.element("div").classes(
                "w-12 h-12 rounded-xl bg-blue-600 flex items-center justify-center shadow-md"
            ):
                ui.icon("keyboard_alt", size="28px").classes("text-white")
            with ui.column().classes("gap-0"):
                ui.label("HotString").classes("text-2xl font-bold text-slate-800 leading-tight")
                ui.label("Type less. Do more.").classes("text-sm text-slate-500")
        with ui.row().classes("items-center gap-3"):
            _status_badge()
            ui.button("Log folder", icon="folder_open", on_click=_open_log_folder).props(
                "flat dense color=grey-8"
            )


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
                ui.label("Welcome to HotString").classes("text-3xl font-bold")
                ui.label(
                    "Type a short trigger anywhere on Windows and HotString does the rest."
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
                ("3", "Type it anywhere", "HotString erases the trigger and runs the command."),
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
                ui.input("Description", value="Open HotString")
                .props("outlined dense")
                .classes("flex-1")
            )
        command = (
            ui.input("Command", value="aopen")
            .props("outlined dense")
            .classes("w-full font-mono")
        )
        start_with_windows = ui.checkbox("Start HotString when Windows starts", value=True)

        def create_first() -> None:
            error = _trigger_error(trigger.value or "") or _command_error(command.value or "")
            if error:
                ui.notify(error, type="negative")
                return
            try:
                db.create_hotstring(
                    trigger.value,
                    description.value or "",
                    command.value,
                    enabled=True,
                )
            except ValueError as exc:
                ui.notify(str(exc), type="negative")
                return

            if start_with_windows.value:
                if not autostart.enable():
                    ui.notify(
                        "HotString was created, but the start-with-Windows entry could not be written.",
                        type="warning",
                    )
            signals.signal_reload()
            ui.notify("HotString created. Try typing ;hs anywhere!", type="positive")
            ui.navigate.reload()

        ui.button("Create HotString", icon="check", on_click=create_first).props(
            "unelevated rounded"
        ).classes("mt-2")

    ui.label(
        "Closing this window hides the UI — HotString keeps running in the system tray. "
        "Use the pencil icon to edit triggers or the trash icon to delete them."
    ).classes("text-xs text-slate-500")


def _render_management() -> None:
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
                            message = "HotString updated."
                        else:
                            db.create_hotstring(
                                trigger.value,
                                description.value or "",
                                command.value,
                                enabled=bool(enabled.value),
                            )
                            message = "HotString created."
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
            ui.label("This HotString will stop working immediately. This cannot be undone.").classes(
                "text-sm text-slate-600"
            )

            def delete() -> None:
                ok = db.delete_hotstring(int(row["id"]))
                signals.signal_reload()
                refresh()
                dialog.close()
                ui.notify(
                    "HotString deleted." if ok else "HotString was already deleted.",
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
                "Start HotString when Windows starts", value=autostart.is_enabled()
            )

            def toggle_autostart(event) -> None:  # noqa: ANN001
                wanted = bool(event.value)
                ok = autostart.set_enabled(wanted)
                if not ok:
                    ui.notify("Could not update the Windows startup entry.", type="negative")
                else:
                    ui.notify(
                        "HotString will start with Windows."
                        if wanted
                        else "HotString will no longer start with Windows.",
                        type="positive",
                    )
                start_switch.value = autostart.is_enabled()

            start_switch.on_value_change(toggle_autostart)

            pause_switch = ui.switch("Pause listening", value=config.is_paused())

            def toggle_pause(event) -> None:  # noqa: ANN001
                paused = bool(event.value)
                config.set_paused(paused)
                signals.signal_reload()
                ui.notify(
                    "Listening paused. Triggers will not fire." if paused else "Listening resumed.",
                    type="info",
                )

            pause_switch.on_value_change(toggle_pause)

    with ui.column().classes("w-full gap-1 pt-2"):
        ui.label(f"Database: {db.current_db_path()}").classes("text-xs text-slate-400 font-mono")
        ui.label(f"Log: {config.LOG_PATH}").classes("text-xs text-slate-400 font-mono")
        ui.label(f"HotString {config.APP_VERSION} · Closing this window keeps the app in the tray.").classes(
            "text-xs text-slate-400"
        )

    refresh()


# ---------------------------------------------------------------------------
# Process entry point
# ---------------------------------------------------------------------------


def _native_available() -> bool:
    """Return whether a native pywebview window can be opened."""
    if os.environ.get("HOTSTRING_NO_NATIVE") == "1":
        return False
    try:
        import webview  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return True


def _choose_port() -> int:
    """Pick a free local port for the NiceGUI server."""
    override = os.environ.get("HOTSTRING_UI_PORT")
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
            _render_header()
            if onboarding and db.is_first_run():
                _render_onboarding()
            else:
                _render_management()


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
        title="HotString",
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
