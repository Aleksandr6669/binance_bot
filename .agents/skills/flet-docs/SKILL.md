---
name: flet-docs
description: Comprehensive reference documentation and development guidelines for Flet version 0.85+ based on official resources.
---

# Flet Development & Reference Manual (v0.85+)

This skill contains the comprehensive developer guidelines compiled from the official Flet resources:
- [Flet Documentation Portal](https://flet.dev/docs)
- [Flet Components Gallery](https://flet.app/gallery)

---

## 📂 1. Styling, Theming & Layouts

### 🚀 1.1 Expanding Controls
- **Rule**: Use `expand=True` to make a control fill all available space within its parent container.
- **Relative Ratios**: Pass integers (e.g., `expand=2` and `expand=1` to make the first control twice as large as the second).

```python
ft.Row([
    ft.Container(expand=1, bgcolor="red"),
    ft.Container(expand=2, bgcolor="blue")
])
```

### 🎨 1.2 Colors & Fonts
- **Colors**: Always use `ft.Colors` constants or hex strings (`#HEX`). Use `ft.Colors.with_opacity(opacity, color)` for transparency.
- **Fonts**: Load custom TTF/OTF fonts via the `page.fonts` dictionary and map them using string keys.

```python
page.fonts = {
    "Roboto": "fonts/Roboto-Regular.ttf",
    "OpenSans": "https://fonts.googleapis.com/...OpenSans.ttf"
}
page.theme = ft.Theme(font_family="Roboto")
```

### 🛠️ 1.3 Theming & Assets
- **Theming**: Toggle dark/light theme via `page.theme_mode = ft.ThemeMode.DARK`. Customize themes via `ft.Theme(color_scheme=ft.ColorScheme(...))`.
- **Assets**: Store static images and files inside an `/assets` directory. Reference using a leading slash (e.g., `src="/logo.png"`).

---

## ⚡ 2. User Interactions & Advanced Features

### 🎞️ 2.1 Animations
- **Implicit Animations**: Set the `animate` parameter on a container.
- **Explicit / Lottie**: Use `ft.Lottie` for complex vector animations or custom transitions.

```python
# Implicit animation example
container = ft.Container(width=100, height=100, animate=ft.Animation(500, ft.AnimationCurve.EASE))
def change_size(e):
    container.width = 200
    page.update()
```

### 📱 2.2 Adaptive Apps
- Detect user platform with `page.platform` (e.g. `ft.PagePlatform.MACOS`).
- Build responsive views utilizing `ft.ResponsiveRow` grids with breakpoints.

```python
is_mobile = page.width < 768
layout = ft.ResponsiveRow([
    ft.Container(col={"xs": 12, "md": 6}, content=...)
])
```

### ⌨️ 2.3 Keyboard Shortcuts
- Catch global keystrokes using the `page.on_keyboard_event` handler.

```python
def on_key(e: ft.KeyboardEvent):
    if e.ctrl and e.key == "P":
        print("Print action triggered")
page.on_keyboard_event = on_key
```

### 🎯 2.4 Drag and Drop
- Use `ft.Draggable` and `ft.DragTarget` components to handle item movement.

```python
drag = ft.Draggable(group="items", content=ft.Text("Drag Me"))
target = ft.DragTarget(
    group="items",
    on_accept=lambda e: print(f"Item received: {e.src_data}")
)
```

### 📋 2.5 Large Lists & Accessibility
- **Large Lists**: Use `ft.ListView` or `ft.GridView` to virtualize scrollable areas.
- **Accessibility**: Define the `tooltip`, `label`, and `semantics_label` properties to assist screen readers.

---

## 🧭 3. Routing & Application Architecture

### 🔗 3.1 Navigation, Routing & Router
- Manage route changes in `page.on_route_change` and control routing using `page.go()`.
- Keep screen stacks organized within `page.views` list.

```python
def route_change(e):
    page.views.clear()
    page.views.append(
        ft.View(
            route="/",
            controls=[ft.AppBar(title=ft.Text("Home")), ft.Text("Main View")]
        )
    )
    if page.route == "/settings":
        page.views.append(
            ft.View(
                route="/settings",
                controls=[ft.AppBar(title=ft.Text("Settings")), ft.Text("Settings View")]
            )
        )
    page.update()
page.on_route_change = route_change
```

### 🧩 3.2 Control Refs & Custom Controls
- **Control Refs**: Use `ft.Ref` to access controls cleanly without storing global layout variables.
- **Custom Controls**: Inherit from standard container structures or customize combined classes.

```python
name_input = ft.Ref[ft.TextField]()
page.add(
    ft.TextField(ref=name_input, label="Name"),
    ft.ElevatedButton("Save", on_click=lambda _: print(name_input.current.value))
)
```

### 🗂️ 3.3 Declarative CRUD Pattern
- Avoid modifying existing controls imperatively. Clear and rebuild list containers declaratively:

```python
todo_list = ft.Column()
def add_todo(text):
    todo_list.controls.append(ft.Text(text))
    page.update() # Renders layout declaratively
```

---

## 💾 4. Asynchronous Execution & Storage

### 🌐 4.1 Async Apps
- Define application entry point with `async def main(page: ft.Page):` and use asynchronous handlers.

```python
import asyncio

async def main(page: ft.Page):
    async def load_data(e):
        await asyncio.sleep(2)
        print("Data loaded")
    page.add(ft.ElevatedButton("Load", on_click=load_data))
```

### 📁 4.2 Read and Write Files
- Launch local OS dialogues using the `ft.FilePicker` component.

```python
picker = ft.FilePicker(on_result=lambda e: print(e.files))
page.overlay.append(picker)
page.add(ft.ElevatedButton("Select Files", on_click=lambda _: picker.pick_files()))
```

### 💾 4.3 Client & Session Storage
- **Client Storage**: Persistent local storage across app restarts.
- **Session Storage**: Temporary workspace session storage.

```python
# Client Storage
page.client_storage.set("token", "secret-key")
# Session Storage
page.session.store.set("active_tab", 0)
```

### 💬 4.4 PubSub
- Broadcast real-time events across multiple application sessions.

```python
def on_broadcast(message):
    print("Broadcast received:", message)
page.pubsub.subscribe(on_broadcast)
page.pubsub.send_all("System announcement")
```

---

## 🔒 5. System, Security & Dialogs

### 🖥️ 5.1 Subprocesses & Logging
- Run command line applications inside separate worker threads to keep the user interface responsive.
- Pipe logs output into the application window using Python's standard `logging` module.

### 🔑 5.2 Authentication & Encrypting Data
- Maintain login screens using session checks (`page.session.store.get("user_id")`).
- Encrypt database storage keys using Python's `cryptography` library.

### 💬 5.3 Declarative Dialogs
- Initialize and open overlays cleanly using `page.open(dialog)`.

```python
confirm_dialog = ft.AlertDialog(
    title=ft.Text("Exit Application"),
    content=ft.Text("Are you sure you want to close?"),
    actions=[
        ft.TextButton("Yes", on_click=lambda _: page.close(confirm_dialog)),
        ft.TextButton("No", on_click=lambda _: page.close(confirm_dialog))
    ]
)
page.open(confirm_dialog)
```

---

## 🖼️ 6. Flet Gallery Control Reference & Parameters

This section lists the essential properties for components found in the [Flet Gallery](https://flet.app/gallery).

### 6.1 Layout Controls
- **Container**: `content`, `padding`, `margin`, `alignment`, `bgcolor`, `border`, `border_radius`, `image_src`, `gradient`, `width`, `height`, `clip_behavior`.
- **Row / Column**: `controls`, `alignment`, `vertical_alignment`, `spacing`, `wrap`, `run_spacing`, `scroll`.
- **Stack**: `controls`, `alignment`, `clip_behavior`.
- **ListView**: `controls`, `spacing`, `divider_thickness`, `padding`, `first_visible_index`, `on_scroll`.
- **GridView**: `controls`, `runs_count`, `max_extent`, `spacing`, `run_spacing`, `padding`, `on_scroll`.
- **ResponsiveRow**: `controls`, `spacing`, `run_spacing`. Columns can define responsive span dictionaries: `col={"xs": 12, "md": 6}`.

### 6.2 Button Controls
- **ElevatedButton**: `text`, `icon`, `icon_color`, `color`, `bgcolor`, `disabled`, `on_click`.
- **IconButton**: `icon`, `icon_color`, `icon_size`, `tooltip`, `disabled`, `on_click`.
- **PopupMenuButton**: `items` (list of `ft.PopupMenuItem`), `icon`, `tooltip`, `on_select`.

### 6.3 Input Controls
- **TextField**: `value`, `label`, `placeholder`, `password`, `can_reveal_password`, `multiline`, `min_lines`, `max_lines`, `keyboard_type`, `border_color`, `focused_border_color`, `on_change`, `on_submit`.
- **Dropdown**: `options` (list of `ft.dropdown.Option`), `value`, `label`, `on_change`.
- **Switch**: `value` (bool), `label`, `label_position`, `on_change`.
- **Checkbox**: `value` (bool), `label`, `on_change`.

---

## 🎨 7. Capitalization Reference (Flet 0.85+)

Always use **capitalized class names** instead of obsolete lowercase helper modules:

| Obsolete (0.7x and below) | Modern (0.85+) | Example |
| :--- | :--- | :--- |
| `ft.border.all()` | `ft.Border.all()` | `border=ft.Border.all(1, "#334155")` |
| `ft.border.only()` | `ft.Border.only()` | `border=ft.Border.only(bottom=...)` |
| `ft.padding.only()` | `ft.Padding.only()` | `padding=ft.Padding.only(bottom=4)` |
| `ft.padding.symmetric()` | `ft.Padding.symmetric()` | `padding=ft.Padding.symmetric(8, 12)` |
| `ft.margin.all()` | `ft.Margin.all()` | `margin=ft.Margin.all(10)` |
| `ft.colors.TRANSPARENT` | `ft.Colors.TRANSPARENT` | `bgcolor=ft.Colors.TRANSPARENT` |
| `ft.alignment.center` | `ft.Alignment.CENTER` | `alignment=ft.Alignment.CENTER` |

### Icons & Flet Gallery
- Replaced the deprecated `name` parameter in `ft.Icon(name=...)` with the position parameter `ft.Icon(ft.Icons.XXX)`.
- Use capitalized icon names from the [Flet Gallery](https://flet.app/gallery).
