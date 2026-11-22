# HotString

**Type less. Do more.**

HotString is a lightweight Windows text expander and command launcher. Create a short trigger
(2–8 characters, for example `;em`), type it in **any** application, and HotString erases it and
runs the command you attached to it — type text, launch programs with PowerShell, or open the
HotString window itself.

Built with Python, [NiceGUI](https://nicegui.io/) (native pywebview window), SQLModel/SQLite,
`pynput` for the global keyboard hook and `pystray` for the tray icon.

![HotString management window](docs/screenshots/management.png)

![First-run onboarding](docs/screenshots/onboarding.png)

---

## Features

- **Global triggers** — works in any focused application, not just the HotString window.
- **Instant management** — add, edit, delete, enable or disable HotStrings; changes apply
  immediately, no restart.
- **Three command types** — type Unicode text, run hidden PowerShell, or trigger an app action.
- **Startup commands** — run PowerShell automatically when HotString starts.
- **First-run onboarding** — a guided screen creates the `;hs` → `aopen` rule for you.
- **System tray** — open the UI, pause/resume listening, toggle start-with-Windows, exit.
- **Single instance** — launching HotString again opens the existing instance instead of
  starting a second one.
- **Reliable Unicode typing** — Thai, emoji and multi-line text are pasted through the clipboard,
  independent of the active keyboard layout.
- **Rotating logs** — everything is written to `%APPDATA%\HotString\hotstring.log`.

---

## Requirements

- Windows 10 or Windows 11
- Python 3.11 or newer
- [`uv`](https://docs.astral.sh/uv/) for dependency management
- Microsoft Edge WebView2 Runtime (pre-installed on Windows 11 and most Windows 10 machines)

---

## Installation

```bash
git clone https://github.com/jeeradate/hotstring.git
cd hotstring
uv sync
uv run hotstring
```

The first start opens the welcome screen. It explains triggers and the command format and asks
you to create your first HotString, pre-filled with:

| Field | Value |
| --- | --- |
| Trigger | `;hs` |
| Description | Open HotString |
| Command | `aopen` |

The **Start HotString when Windows starts** checkbox is checked by default.

After that, HotString starts silently in the system tray on every launch. To open the window,
double-click the tray icon or choose **Open HotString**.

---

## Quick start

Create these HotStrings in the UI, then try them in Notepad, your browser, or any other app:

| Trigger | Command | What happens |
| --- | --- | --- |
| `;em` | `tmyname@example.com` | Types your e-mail address |
| `;np` | `sStart-Process notepad` | Opens Notepad (no console window) |
| `;hs` | `aopen` | Opens the HotString management window |
| `;th` | `tสวัสดีครับ` | Types Thai text (Unicode-safe) |

Type the trigger, and HotString removes it and runs the command.

---

## Command format

A command is plain text. Its **first character** defines its type:

| Prefix | Type | Description | Example |
| --- | --- | --- | --- |
| `t` | Type text | Pastes text into the focused application | `tHello world` |
| `s` | PowerShell | Runs a hidden PowerShell script | `sStart-Process notepad` |
| `a` | App action | Runs a built-in HotString action (`aopen` opens the UI) | `aopen` |
| `r` | Startup | Runs a hidden PowerShell script when HotString starts | `rStart-Process notepad` |

One optional separator directly after the prefix is ignored, so all of these are equivalent:

```text
tHello
t Hello
t:Hello
```

The same applies to `s`, `a` and `r` (`s:Get-Date`). Anything after the prefix is passed through
unchanged, including newlines.

Notes:

- `t` supports **Unicode (including Thai) and multi-line text**. HotString temporarily puts the
  text on the clipboard, sends `Ctrl+V`, and restores the previous text clipboard.
- `s` and `r` run
  `powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -Command "<script>"`
  with `CREATE_NO_WINDOW`, on a worker thread. stdout, stderr and the exit code are logged.
- `r` commands run **once when HotString starts**, not every time the UI opens.
- Commands with an unknown prefix are rejected by the editor and by the database layer.
- The **Test** button in the add/edit dialog validates the command. For `t` it shows a preview
  instead of typing; for `s`/`r` it runs the script.

---

## Using the management window

- **Search** filters by trigger, description or command.
- **Add HotString** opens the editor at the bottom of the list.
- **Edit** (pencil) and **Delete** (trash, with confirmation) appear on every row.
- **Enabled** controls whether a trigger fires. Disabled triggers stay in the list.
- **Settings**:
  - *Start HotString when Windows starts* — writes/removes the registry `Run` entry.
  - *Pause listening* — keeps the keyboard hook installed but stops matching.
- Closing the window only hides the UI. The listener and tray icon keep running.

Validation rules in the editor:

- Trigger length 2–8, no whitespace, unique (triggers are **case-sensitive**).
- A trigger that is the suffix of another trigger produces a warning, because the shorter one
  always fires first while typing.
- The command must start with `t`, `s`, `a` or `r` and have a body.

### Tray menu

| Item | Action |
| --- | --- |
| Open HotString | Opens the management window |
| Pause listening / Resume listening | Toggles trigger matching (persisted) |
| Start with Windows | Adds/removes the registry entry (checkmark shows current state) |
| Exit | Stops the listener, tray icon and HotString |

Only one instance can run. Starting HotString a second time signals the running instance to open
its window and then exits immediately.

---

## Start with Windows

HotString registers itself under:

```text
HKCU\Software\Microsoft\Windows\CurrentVersion\Run
Value name: HotString
```

The value launches `pythonw.exe -m hotstring` (or the packaged executable), so no console window
appears at login. Toggle it from **Settings** in the UI or from the tray menu. Removing it is
immediate and requires no restart.

---

## Keyboard layout note

Matching uses **the characters actually produced by the active keyboard layout**, compared
exactly and case-sensitively.

- A trigger typed with the English layout will not match while the Thai layout is active.
- `;EM` and `;em` are different triggers.
- Dead keys, IME composition and AltGr characters behave as typed on your layout.

The buffer is cleared on Enter, Esc, Tab, arrow keys, Home/End, PageUp/PageDown, mouse clicks and
window focus changes, so stale characters cannot trigger anything.

---

## Security warning

> **`s` and `r` commands run PowerShell with your Windows user permissions.**
>
> HotString does not sandbox, sign or review commands. A malicious or careless command can delete
> files, change settings, download software or exfiltrate data. Only add commands you understand
> and trust, keep your database file private, and never import HotStrings from an untrusted source.
> Commands run with your normal permissions — not elevated — so they cannot silently administer
> the machine unless you run HotString as administrator.

The keyboard hook also sees everything you type. HotString does not record or transmit keystrokes;
only the last eight characters are held in memory to detect triggers, and the database and logs
stay on your PC.

---

## Data locations

| What | Path |
| --- | --- |
| Database | `D:\hotbuff\hotstring.db` (created automatically, including the folder) |
| Log | `%APPDATA%\HotString\hotstring.log` (2 MB rotating, 3 backups) |
| Settings | `%APPDATA%\HotString\settings.json` |

Environment overrides are available for development and testing:
`HOTSTRING_DB`, `HOTSTRING_APP_DIR`, `HOTSTRING_SETTINGS`, `HOTSTRING_LOG`.

---

## Troubleshooting

- **A trigger does not fire.** Check that listening is not paused, the HotString is enabled, the
  trigger is not a suffix of another trigger, and the keyboard layout matches. Some elevated
  windows and games using raw input do not accept synthetic input; run HotString at the same
  privilege level if needed.
- **Nothing is typed for a `t` command.** Make sure the target control accepts `Ctrl+V`. The
  clipboard is restored to its previous text after pasting; non-text clipboard content may be
  replaced.
- **The window does not open.** Check that WebView2 is installed. Logs are in
  `%APPDATA%\HotString\hotstring.log`; the tray menu can open the log folder.
- **PowerShell fails.** Open the log to see stdout, stderr and the exit code. Test the same script
  manually with `powershell.exe -NoProfile -Command "<script>"`.
- **Two copies seem to run.** Only one background instance is allowed; a second launch asks the
  first instance to show its window.

---

## Project structure

```text
hotstring/
├── pyproject.toml
├── uv.lock
├── README.md
├── LICENSE
├── .gitignore
├── src/hotstring/
│   ├── __init__.py
│   ├── __main__.py      # uv run hotstring / python -m hotstring
│   ├── app.py           # startup, single instance, process orchestration
│   ├── models.py        # SQLModel HotString model and validation helpers
│   ├── db.py            # engine, session, CRUD
│   ├── listener.py      # global keyboard hook and rolling buffer
│   ├── executor.py      # t / s / a / r parsing and execution
│   ├── ui.py            # NiceGUI pages, dialogs, settings
│   ├── tray.py          # pystray icon and menu
│   ├── autostart.py     # registry Run key
│   ├── signals.py       # Windows named events between processes
│   └── config.py        # paths, constants, settings, logging
└── tests/
    ├── test_models.py
    ├── test_matching.py
    └── test_executor.py
```

---

## Development

```bash
uv sync                 # create the environment and install dependencies
uv run pytest           # run the test suite
uv run hotstring        # start the app
```

To capture screenshots or develop without opening a native window, set
`HOTSTRING_NO_NATIVE=1`; the UI then serves in a browser instead of pywebview.

---

## Known limitations

- Windows only (registry autostart, `pynput` hook, Win32 clipboard).
- Triggers are limited to 8 characters and are matched case-sensitively per keyboard layout.
- Typing support relies on clipboard paste, so clipboard history tools may record the pasted
  text and non-text clipboard contents are not restored.
- Python PowerShell output is decoded as UTF-8; scripts that emit text in the OEM code page may
  show replacement characters in the log.
- Elevated applications may ignore simulated input unless HotString is elevated too.

---

## License

MIT — see [LICENSE](LICENSE).

---

# HotString (ภาษาไทย)

**พิมพ์น้อยลง ทำได้มากขึ้น**

HotString คือโปรแกรมขยายข้อความและเรียกคำสั่งสำหรับ Windows ขนาดเล็ก สร้าง "ทริกเกอร์" สั้น ๆ
(2–8 ตัวอักษร เช่น `;em`) แล้วพิมพ์ทริกเกอร์นั้นในแอปใดก็ได้ HotString จะลบข้อความที่พิมพ์และรัน
คำสั่งที่ผูกไว้ทันที — พิมพ์ข้อความ เปิดโปรแกรมด้วย PowerShell หรือเปิดหน้าต่างจัดการ HotString

สร้างด้วย Python, [NiceGUI](https://nicegui.io/) (หน้าต่างเดสก์ท็อปผ่าน pywebview),
SQLModel/SQLite, `pynput` สำหรับดักคีย์บอร์ดทั่วระบบ และ `pystray` สำหรับไอคอนถาดระบบ

![หน้าต่างจัดการ HotString](docs/screenshots/management.png)

![หน้าเริ่มต้นใช้งานครั้งแรก](docs/screenshots/onboarding.png)

---

## คุณสมบัติ

- **ทริกเกอร์ใช้ได้ทั่วระบบ** — ทำงานในแอปที่กำลังโฟกัส ไม่จำกัดเฉพาะหน้าต่าง HotString
- **จัดการได้ทันที** — เพิ่ม แก้ไข ลบ เปิด/ปิด HotString และการเปลี่ยนแปลงมีผลทันทีโดยไม่ต้องรีสตาร์ต
- **คำสั่งสามแบบ** — พิมพ์ข้อความ Unicode, รัน PowerShell แบบซ่อนหน้าต่าง หรือเรียกคำสั่งของแอป
- **คำสั่งตอนเริ่มระบบ** — รัน PowerShell อัตโนมัติเมื่อ HotString เริ่มทำงาน
- **หน้าจอเริ่มต้นใช้งาน** — แนะนำการใช้งานและสร้างกฎ `;hs` → `aopen` ให้อัตโนมัติ
- **ถาดระบบ (System tray)** — เปิดหน้าต่าง หยุด/เริ่มการดักฟัง เปิด/ปิดการเริ่มพร้อม Windows และออก
- **รันได้เพียงอินสแตนซ์เดียว** — เปิด HotString ซ้ำจะเป็นการสั่งให้ตัวที่รันอยู่เปิดหน้าต่างแล้วปิดตัวเอง
- **พิมพ์ Unicode ได้น่าเชื่อถือ** — ภาษาไทย อีโมจิ และข้อความหลายบรรทัดใช้คลิปบอร์ดในการวาง
  จึงไม่ขึ้นกับเลย์เอาต์คีย์บอร์ดที่ใช้งานอยู่
- **บันทึก log แบบหมุนไฟล์** — อยู่ที่ `%APPDATA%\HotString\hotstring.log`

---

## สิ่งที่ต้องมี

- Windows 10 หรือ Windows 11
- Python 3.11 ขึ้นไป
- [`uv`](https://docs.astral.sh/uv/) สำหรับจัดการแพ็กเกจ
- Microsoft Edge WebView2 Runtime (มีมาแล้วใน Windows 11 และ Windows 10 ส่วนใหญ่)

---

## การติดตั้ง

```bash
git clone https://github.com/jeeradate/hotstring.git
cd hotstring
uv sync
uv run hotstring
```

การเปิดครั้งแรกจะแสดงหน้าต้อนรับ ซึ่งอธิบายทริกเกอร์และรูปแบบคำสั่ง พร้อมขอให้สร้าง HotString
ตัวแรกโดยกรอกค่าไว้ให้แล้ว:

| ช่อง | ค่า |
| --- | --- |
| Trigger | `;hs` |
| Description | Open HotString |
| Command | `aopen` |

ตัวเลือก **Start HotString when Windows starts** ถูกติ๊กไว้เป็นค่าเริ่มต้น

หลังจากนั้น HotString จะเริ่มทำงานเบื้องหลังพร้อมไอคอนในถาดระบบทุกครั้ง เปิดหน้าต่างได้โดย
ดับเบิลคลิกไอคอนถาด หรือเลือก **Open HotString**

---

## เริ่มต้นอย่างรวดเร็ว

สร้าง HotString เหล่านี้ในหน้าต่างจัดการ แล้วลองพิมพ์ใน Notepad เบราว์เซอร์ หรือแอปอื่น:

| ทริกเกอร์ | คำสั่ง | ผลลัพธ์ |
| --- | --- | --- |
| `;em` | `tmyname@example.com` | พิมพ์อีเมลของคุณ |
| `;np` | `sStart-Process notepad` | เปิด Notepad (ไม่มีหน้าต่าง console) |
| `;hs` | `aopen` | เปิดหน้าต่างจัดการ HotString |
| `;th` | `tสวัสดีครับ` | พิมพ์ข้อความภาษาไทย (รองรับ Unicode) |

พิมพ์ทริกเกอร์ แล้ว HotString จะลบมันออกและรันคำสั่งให้

---

## รูปแบบคำสั่ง

คำสั่งเป็นข้อความธรรมดา **ตัวอักษรตัวแรก** กำหนดชนิดของคำสั่ง:

| นำหน้า | ชนิด | คำอธิบาย | ตัวอย่าง |
| --- | --- | --- | --- |
| `t` | พิมพ์ข้อความ | วางข้อความในแอปที่กำลังโฟกัส | `tHello world` |
| `s` | PowerShell | รันสคริปต์ PowerShell แบบซ่อนหน้าต่าง | `sStart-Process notepad` |
| `a` | คำสั่งของแอป | เรียกคำสั่งภายใน (`aopen` เปิดหน้าต่าง UI) | `aopen` |
| `r` | ตอนเริ่มระบบ | รันสคริปต์ PowerShell เมื่อ HotString เริ่มทำงาน | `rStart-Process notepad` |

ตัวคั่นหนึ่งตัว (ช่องว่างหรือ `:`) หลังตัวนำหน้าจะถูกข้ามไป รูปแบบต่อไปนี้จึงเทียบเท่ากัน:

```text
tHello
t Hello
t:Hello
```

ใช้ได้เช่นเดียวกันกับ `s`, `a` และ `r` (เช่น `s:Get-Date`) ข้อความหลังตัวนำหน้าจะถูกใช้ตามเดิม
รวมถึงการขึ้นบรรทัดใหม่

หมายเหตุ:

- `t` รองรับ **Unicode (รวมภาษาไทย) และข้อความหลายบรรทัด** โดย HotString จะเก็บข้อความเดิมใน
  คลิปบอร์ดชั่วคราว ใส่ข้อความใหม่ ส่ง `Ctrl+V` แล้วคืนค่าคลิปบอร์ดเดิม
- `s` และ `r` รันคำสั่ง
  `powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -Command "<script>"`
  พร้อม `CREATE_NO_WINDOW` บนเธรดแยก โดยบันทึก stdout, stderr และ exit code ลง log
- คำสั่ง `r` ทำงาน **ครั้งเดียวตอน HotString เริ่มทำงาน** ไม่ใช่ทุกครั้งที่เปิดหน้าต่าง
- คำสั่งที่ขึ้นต้นด้วยตัวอักษรที่ไม่รู้จักจะถูกปฏิเสธทั้งในหน้าต่างแก้ไขและชั้นฐานข้อมูล
- ปุ่ม **Test** ในไดอะล็อกเพิ่ม/แก้ไขจะตรวจสอบคำสั่ง สำหรับ `t` จะแสดงตัวอย่างข้อความแทนการพิมพ์
  ส่วน `s`/`r` จะรันสคริปต์จริง

---

## การใช้หน้าต่างจัดการ

- **Search** กรองตามทริกเกอร์ คำอธิบาย หรือคำสั่ง
- **Add HotString** เปิดหน้าต่างแก้ไขที่ด้านล่างของรายการ
- ปุ่ม **แก้ไข** (ดินสอ) และ **ลบ** (ถังขยะ พร้อมยืนยัน) อยู่ในทุกแถว
- **Enabled** กำหนดว่าทริกเกอร์จะทำงานหรือไม่ ทริกเกอร์ที่ปิดอยู่ยังคงอยู่ในรายการ
- **Settings**:
  - *Start HotString when Windows starts* — เพิ่ม/ลบคีย์รีจิสทรี `Run`
  - *Pause listening* — ยังติดตั้ง keyboard hook แต่หยุดจับคู่ทริกเกอร์
- การปิดหน้าต่างเป็นเพียงการซ่อน UI ตัวดักฟังและไอคอนถาดยังทำงานต่อ

กฎการตรวจสอบในหน้าต่างแก้ไข:

- ทริกเกอร์ยาว 2–8 ตัวอักษร ไม่มีช่องว่าง และไม่ซ้ำกัน (ทริกเกอร์ **แยกตัวพิมพ์เล็ก-ใหญ่**)
- หากทริกเกอร์หนึ่งเป็นส่วนต่อท้าย (suffix) ของอีกทริกเกอร์ จะมีคำเตือน เพราะตัวที่สั้นกว่าจะทำงานก่อนเสมอ
- คำสั่งต้องขึ้นต้นด้วย `t`, `s`, `a` หรือ `r` และต้องมีเนื้อหาต่อท้าย

### เมนูถาดระบบ

| รายการ | การทำงาน |
| --- | --- |
| Open HotString | เปิดหน้าต่างจัดการ |
| Pause listening / Resume listening | หยุด/เริ่มจับคู่ทริกเกอร์ (จำค่าถาวร) |
| Start with Windows | เพิ่ม/ลบคีย์รีจิสทรี (เครื่องหมายถูกแสดงสถานะปัจจุบัน) |
| Exit | หยุดตัวดักฟัง ไอคอนถาด และโปรแกรม |

รันได้เพียงอินสแตนซ์เดียว การเปิด HotString ครั้งที่สองจะสั่งให้ตัวที่รันอยู่เปิดหน้าต่างแล้วปิดตัวเองทันที

---

## เริ่มทำงานพร้อม Windows

HotString ลงทะเบียนตัวเองที่:

```text
HKCU\Software\Microsoft\Windows\CurrentVersion\Run
ชื่อค่า: HotString
```

ค่านี้เรียก `pythonw.exe -m hotstring` (หรือไฟล์ 실행 ที่แพ็กแล้ว) จึงไม่มีหน้าต่าง console ตอนล็อกอิน
เปิด/ปิดได้จาก **Settings** ใน UI หรือเมนูถาดระบบ และมีผลทันทีโดยไม่ต้องรีสตาร์ต

---

## หมายเหตุเรื่องเลย์เอาต์คีย์บอร์ด

การจับคู่ใช้ **ตัวอักษรที่ถูกสร้างจริงตามเลย์เอาต์คีย์บอร์ดที่ใช้งาน** และเปรียบเทียบแบบแยก
ตัวพิมพ์เล็ก-ใหญ่

- ทริกเกอร์ที่พิมพ์ด้วยเลย์เอาต์อังกฤษจะไม่ตรงกับขณะเปิดเลย์เอาต์ไทย
- `;EM` และ `;em` เป็นทริกเกอร์คนละตัว
- Dead key, การประกอบตัวอักษรด้วย IME และอักขระจาก AltGr จะเป็นไปตามเลย์เอาต์ของคุณ

บัฟเฟอร์จะถูกล้างเมื่อกด Enter, Esc, Tab, ปุ่มลูกศร, Home/End, PageUp/PageDown, คลิกเมาส์
หรือสลับหน้าต่าง เพื่อไม่ให้ตัวอักษรเก่ามาทริกเกอร์โดยไม่ตั้งใจ

---

## คำเตือนด้านความปลอดภัย

> **คำสั่ง `s` และ `r` รัน PowerShell ด้วยสิทธิ์ผู้ใช้ Windows ของคุณ**
>
> HotString ไม่ได้แยกSandbox ลงนาม หรือตรวจสอบคำสั่ง คำสั่งที่เป็นอันตรายหรือประมาทอาจลบไฟล์
> เปลี่ยนการตั้งค่า ดาวน์โหลดซอฟต์แวร์ หรือขโมยข้อมูลได้ ควรเพิ่มเฉพาะคำสั่งที่คุณเข้าใจและเชื่อถือ
> เก็บไฟล์ฐานข้อมูลไว้เป็นส่วนตัว และอย่านำ HotString จากแหล่งที่ไม่น่าเชื่อถือมาใช้
> คำสั่งทำงานด้วยสิทธิ์ปกติของคุณ (ไม่ยกระดับ) จึงไม่สามารถจัดการระบบได้เอง เว้นแต่คุณจะรัน
> HotString ในฐานะผู้ดูแลระบบ

keyboard hook มองเห็นทุกสิ่งที่คุณพิมพ์ HotString ไม่บันทึกหรือส่งข้อมูลการพิมพ์ออกไป
มีเพียง 8 ตัวอักษรล่าสุดที่เก็บในหน่วยความจำเพื่อตรวจทริกเกอร์ ฐานข้อมูลและ log อยู่บนเครื่องคุณเท่านั้น

---

## ตำแหน่งข้อมูล

| ข้อมูล | ตำแหน่ง |
| --- | --- |
| ฐานข้อมูล | `D:\hotbuff\hotstring.db` (สร้างโฟลเดอร์และไฟล์ให้อัตโนมัติ) |
| Log | `%APPDATA%\HotString\hotstring.log` (หมุนที่ 2 MB เก็บ 3 ชุด) |
| การตั้งค่า | `%APPDATA%\HotString\settings.json` |

สามารถกำหนดผ่านตัวแปรสภาพแวดล้อมสำหรับการพัฒนา/ทดสอบ:
`HOTSTRING_DB`, `HOTSTRING_APP_DIR`, `HOTSTRING_SETTINGS`, `HOTSTRING_LOG`

---

## การแก้ปัญหา

- **ทริกเกอร์ไม่ทำงาน** ตรวจสอบว่าการดักฟังไม่ได้ถูกหยุด HotString เปิดใช้งานอยู่ ทริกเกอร์ไม่ใช่
  suffix ของอีกตัว และเลย์เอาต์คีย์บอร์ดตรงกัน หน้าต่างที่ยกระดับสิทธิ์และเกมที่ใช้ raw input
  บางตัวอาจไม่รับการป้อนแบบจำลอง ควรเปิด HotString ด้วยระดับสิทธิ์เดียวกัน
- **คำสั่ง `t` ไม่พิมพ์ข้อความ** ตรวจสอบว่าช่องปลายทางรองรับ `Ctrl+V` ระบบจะคืนค่าคลิปบอร์ดที่เป็น
  ข้อความเดิมหลังวาง แต่เนื้อหาที่ไม่ใช่ข้อความอาจถูกแทนที่
- **หน้าต่างไม่เปิด** ตรวจสอบว่าติดตั้ง WebView2 แล้ว ดู log ที่
  `%APPDATA%\HotString\hotstring.log` หรือเปิดโฟลเดอร์ log ได้จากเมนูถาด
- **PowerShell ผิดพลาด** เปิด log เพื่อดู stdout, stderr และ exit code และลองรันสคริปต์เดิมด้วย
  `powershell.exe -NoProfile -Command "<script>"`
- **ดูเหมือนมีสองอินสแตนซ์** อนุญาตให้มีตัวทำงานเบื้องหลังเพียงตัวเดียว การเปิดครั้งที่สองจะสั่งให้
  ตัวแรกเปิดหน้าต่าง

---

## โครงสร้างโปรเจกต์

```text
hotstring/
├── pyproject.toml
├── uv.lock
├── README.md
├── LICENSE
├── .gitignore
├── src/hotstring/
│   ├── __init__.py
│   ├── __main__.py      # uv run hotstring / python -m hotstring
│   ├── app.py           # การเริ่มทำงาน, single instance, จัดการโปรเซส
│   ├── models.py        # โมเดล SQLModel และตัวช่วยตรวจสอบ
│   ├── db.py            # engine, session, CRUD
│   ├── listener.py      # global keyboard hook และบัฟเฟอร์ตัวอักษร
│   ├── executor.py      # แยกวิเคราะห์และรัน t / s / a / r
│   ├── ui.py            # หน้า NiceGUI, ไดอะล็อก, การตั้งค่า
│   ├── tray.py          # ไอคอนและเมนูถาดระบบ
│   ├── autostart.py     # คีย์รีจิสทรี Run
│   ├── signals.py       # Windows named events ระหว่างโปรเซส
│   └── config.py        # พาธ ค่าคงที่ การตั้งค่า และ logging
└── tests/
    ├── test_models.py
    ├── test_matching.py
    └── test_executor.py
```

---

## การพัฒนา

```bash
uv sync                 # สร้าง environment และติดตั้ง dependencies
uv run pytest           # รันชุดทดสอบ
uv run hotstring        # เริ่มโปรแกรม
```

หากต้องการทดสอบ UI โดยไม่เปิดหน้าต่าง native ให้ตั้งค่า `HOTSTRING_NO_NATIVE=1`
ระบบจะแสดง UI ผ่านเบราว์เซอร์แทน pywebview

---

## ข้อจำกัดที่ทราบ

- รองรับเฉพาะ Windows (รีจิสทรี autostart, keyboard hook ของ `pynput`, คลิปบอร์ด Win32)
- ทริกเกอร์จำกัด 8 ตัวอักษร และจับคู่แบบแยกตัวพิมพ์เล็ก-ใหญ่ตามเลย์เอาต์คีย์บอร์ด
- การพิมพ์ใช้การวางจากคลิปบอร์ด เครื่องมือ clipboard history อาจบันทึกข้อความที่วาง และเนื้อหา
  คลิปบอร์ดที่ไม่ใช่ข้อความจะไม่ถูกคืนค่า
- เอาต์พุต PowerShell ถูกถอดรหัสเป็น UTF-8 สคริปต์ที่ส่งข้อความด้วย OEM code page อาจแสดง
  ตัวอักษรทดแทนใน log
- แอปที่ยกระดับสิทธิ์อาจไม่รับการป้อนแบบจำลอง เว้นแต่ HotString จะยกระดับสิทธิ์ด้วย

---

## สัญญาอนุญาต

MIT — ดู [LICENSE](LICENSE)
