# PasteImage

Sublime Text 4 plugin for macOS. Paste an image from the clipboard into any
file, and see it inline.

- Press **Cmd+Ctrl+V**. The image is saved as a PNG and a link is inserted at
  the cursor. Markdown files get `![](assets/note-1.png)`. Other files get the
  path.
- Press **Cmd+Ctrl+P** to toggle inline previews of every image link in the
  file. Previews update as you edit, and show on their own when you open a
  file that has image links.
- If the clipboard has no image, Cmd+Ctrl+V does a normal text paste.

## Install

1. Install [`pngpaste`](https://github.com/jcsalterego/pngpaste):

       brew install pngpaste

2. Install the plugin:
   - **Package Control:** `Package Control: Install Package` → `PasteImage`
   - **Manual:** clone this repo into your `Packages` folder:

         cd "$HOME/Library/Application Support/Sublime Text/Packages"
         git clone https://github.com/shivamsupr/PasteImage.git

## Where images go

By default, images are saved next to the file in an `assets/` folder, and the
link is relative. Unsaved buffers use `~/Downloads/sublime-paste` with an
absolute link.

To save every image in one place instead, set `save_dir`:

```jsonc
// Preferences > Package Settings > PasteImage > Settings
{
    "save_dir": "~/Pictures/pasted"
}
```

## Settings

| Setting | Default | What it does |
|---|---|---|
| `save_dir` | `""` | Fixed folder for all images. Empty means next to the file. |
| `assets_dir` | `"assets"` | Folder name next to the file when `save_dir` is empty. |
| `fallback_dir` | `"~/Downloads/sublime-paste"` | Folder for unsaved buffers. |
| `markdown_template` | `"![]({path})"` | Text inserted in markdown files. |
| `plain_template` | `"{path}"` | Text inserted in other files. |
| `fallback_to_text_paste` | `true` | Normal paste when there is no image. |
| `preview_after_paste` | `true` | Show the preview right after a paste. |
| `auto_preview` | `true` | Show previews when a file is opened. |
| `preview_max_width` | `600` | Scale down wider previews (pixels). |
| `pngpaste_path` | `""` | Full path to `pngpaste`. Empty means auto-detect. |

Templates accept `{path}` (the link) and `{name}` (the file name).

## Key bindings

Change them in `Preferences > Package Settings > PasteImage > Key Bindings`:

```json
[
    { "keys": ["super+ctrl+v"], "command": "paste_image" },
    { "keys": ["super+ctrl+p"], "command": "paste_image_preview" }
]
```

## Troubleshooting

Open the console with <kbd>Ctrl</kbd>+<kbd>`</kbd>. Lines that start with
`[PasteImage]` show which `pngpaste` binary ran and its exit code.

- **"pngpaste not found"**: install it, or set `pngpaste_path`.
- **Text pasted instead of an image**: the clipboard had no image. On macOS,
  <kbd>Cmd</kbd>+<kbd>Shift</kbd>+<kbd>4</kbd> saves a screenshot to a file.
  Add <kbd>Ctrl</kbd> to copy it to the clipboard instead.

## Requirements

- Sublime Text 4
- macOS (uses `pngpaste` and `sips`)

## License

MIT
