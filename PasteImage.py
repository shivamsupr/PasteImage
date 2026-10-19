"""PasteImage - paste a clipboard image into the current file on macOS.

Saves the clipboard image as a PNG and inserts a reference at the cursor:
a markdown image link inside markdown files, a plain path elsewhere.
Image references in a file can be previewed inline.

Backed by `pngpaste` (https://github.com/jcsalterego/pngpaste).

Commands:
  paste_image          - save clipboard image, insert reference (Cmd+Ctrl+Shift+V)
  paste_image_preview  - toggle inline previews in the view (Cmd+Ctrl+P)

Settings: see PasteImage.sublime-settings.
"""

import base64
import os
import re
import shutil
import subprocess
import time

import sublime
import sublime_plugin

SETTINGS_FILE = "PasteImage.sublime-settings"

# Sublime's plugin host does not inherit the interactive shell PATH, so resolve
# the `pngpaste` binary explicitly across the usual install locations.
PNGPASTE_CANDIDATES = [
    "/opt/homebrew/bin/pngpaste",
    "/usr/local/bin/pngpaste",
    os.path.expanduser("~/.nix-profile/bin/pngpaste"),
    "/run/current-system/sw/bin/pngpaste",
]

PREVIEW_KEY = "paste_image_preview"


def _settings():
    return sublime.load_settings(SETTINGS_FILE)


def _setting(key, default=None):
    return _settings().get(key, default)


def _log(msg):
    print("[PasteImage] %s" % msg)


def _debug(msg):
    if not _setting("debug", False):
        return
    line = "[PasteImage][debug %s] %s" % (time.strftime("%H:%M:%S"), msg)
    print(line)
    log_file = _setting("debug_log_file", "")
    if log_file:
        try:
            with open(os.path.expanduser(log_file), "a") as fh:
                fh.write(line + "\n")
        except OSError:
            pass


def _find_pngpaste():
    configured = _setting("pngpaste_path", "")
    if configured:
        configured = os.path.expanduser(configured)
        if os.path.exists(configured):
            return configured
        _log("pngpaste_path %r does not exist, falling back to search" % configured)
    found = shutil.which("pngpaste")
    if found:
        return found
    for path in PNGPASTE_CANDIDATES:
        if os.path.exists(path):
            return path
    return None


def _next_path(directory, stem):
    """Return (abs_path, file_name) for the first free "<stem>-<n>.png"."""
    i = 1
    while True:
        name = "%s-%d.png" % (stem, i)
        candidate = os.path.join(directory, name)
        if not os.path.exists(candidate):
            return candidate, name
        i += 1


def _target_dir(view):
    """Return (save_dir, use_relative_link) for the view.

    - If `save_dir` is set, every image goes there and the link is absolute.
    - Otherwise images go to `<file dir>/<assets_dir>` with a relative link.
    - Unsaved buffers fall back to `fallback_dir` with an absolute link.
    """
    save_dir = _setting("save_dir", "")
    if save_dir:
        return os.path.expanduser(save_dir), False

    file_name = view.file_name()
    if file_name:
        assets = _setting("assets_dir", "assets")
        return os.path.join(os.path.dirname(file_name), assets), True

    fallback = _setting("fallback_dir", "~/Downloads/sublime-paste")
    return os.path.expanduser(fallback), False


class PasteImageCommand(sublime_plugin.TextCommand):
    """Save the clipboard image and insert a reference to it."""

    def run(self, edit):
        view = self.view
        if _setting("debug", False):
            _debug(
                "paste_image start: view=%s sel=%s clipboard_text=%r"
                % (view.id(), list(view.sel()), sublime.get_clipboard()[:60])
            )

        pngpaste = _find_pngpaste()
        if not pngpaste:
            _log("pngpaste binary not found")
            sublime.error_message(
                "PasteImage: `pngpaste` not found.\n\n"
                "Install it with `brew install pngpaste`, or set "
                "`pngpaste_path` in PasteImage.sublime-settings."
            )
            return

        file_name = view.file_name()
        stem = (
            os.path.splitext(os.path.basename(file_name))[0]
            if file_name
            else "pasted"
        )

        save_dir, relative = _target_dir(view)
        os.makedirs(save_dir, exist_ok=True)
        abs_path, name = _next_path(save_dir, stem)

        proc = subprocess.Popen(
            [pngpaste, abs_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        _, err = proc.communicate()
        _log(
            "pngpaste=%r rc=%s stderr=%r"
            % (pngpaste, proc.returncode, err.decode(errors="replace").strip())
        )

        if proc.returncode != 0 or not os.path.exists(abs_path):
            if os.path.exists(abs_path):
                os.remove(abs_path)
            if _setting("fallback_to_text_paste", True):
                _debug("no image on clipboard, running text paste")
                sublime.status_message(
                    "PasteImage: no image in clipboard - pasting text"
                )
                view.run_command("paste")
            else:
                sublime.status_message("PasteImage: no image in clipboard")
            return

        if relative:
            link = os.path.join(_setting("assets_dir", "assets"), name)
        else:
            link = abs_path

        is_markdown = any(
            "text.html.markdown" in view.scope_name(r.begin()) for r in view.sel()
        )
        template = _setting(
            "markdown_template" if is_markdown else "plain_template",
            "![]({path})" if is_markdown else "{path}",
        )
        snippet = template.replace("{path}", link).replace("{name}", name)

        # Replace every selection, like a normal paste. Walk backwards so
        # earlier regions stay valid after each replacement. Then leave a
        # plain cursor after each inserted link: view.replace() otherwise
        # keeps the new text selected, and any following keystroke or paste
        # would wipe it out.
        regions = list(view.sel())
        for region in reversed(regions):
            view.replace(edit, region, snippet)
        # Earlier insertions shift later positions, so recompute from the front.
        sel = view.sel()
        sel.clear()
        shift = 0
        for region in regions:
            end = region.begin() + shift + len(snippet)
            sel.add(sublime.Region(end))
            shift += len(snippet) - region.size()

        _log("saved %s" % abs_path)
        _debug("inserted %r, sel now %s" % (snippet, list(view.sel())))
        sublime.status_message("PasteImage: saved %s" % abs_path)

        if _setting("preview_after_paste", True):
            _previewing.add(view.id())
            _render_previews(view)


# --- Inline preview -------------------------------------------------------

# View ids that currently have previews shown.
_previewing = set()

# view id -> sublime.PhantomSet
_phantom_sets = {}

# abs_path -> (mtime, data_uri, dims_str). Avoids re-encoding on every edit.
_uri_cache = {}

# Markdown image: ![alt](path)
_IMG_MD_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
# A whole line that is just an image path (non-markdown inserts).
_IMG_PATH_RE = re.compile(r".+\.(?:png|jpe?g|gif|webp|bmp)", re.IGNORECASE)

_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
}


def _data_uri(path):
    """Read an image and return a base64 data: URI, or None on failure.

    minihtml renders file:// images unreliably (and breaks on spaces in the
    path), so the bytes are embedded directly.
    """
    try:
        with open(path, "rb") as fh:
            data = base64.b64encode(fh.read()).decode("ascii")
    except Exception:
        return None
    mime = _MIME.get(os.path.splitext(path)[1].lower(), "image/png")
    return "data:%s;base64,%s" % (mime, data)


def _image_size(path):
    """Return (width, height) via macOS `sips`, or None."""
    try:
        out = subprocess.check_output(
            ["/usr/bin/sips", "-g", "pixelWidth", "-g", "pixelHeight", path],
            stderr=subprocess.DEVNULL,
        ).decode()
    except Exception:
        return None
    w = h = None
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("pixelWidth:"):
            w = int(line.split(":")[1])
        elif line.startswith("pixelHeight:"):
            h = int(line.split(":")[1])
    if w and h:
        return w, h
    return None


def _image_refs(view):
    """Yield (line_region, abs_path) for each image reference in the view."""
    file_name = view.file_name()
    base_dir = os.path.dirname(file_name) if file_name else ""
    for line_region in view.lines(sublime.Region(0, view.size())):
        text = view.substr(line_region)
        rels = _IMG_MD_RE.findall(text)
        if not rels:
            stripped = text.strip()
            if stripped and _IMG_PATH_RE.fullmatch(stripped):
                rels = [stripped]
        for rel in rels:
            rel = os.path.expanduser(rel)
            abs_path = rel if os.path.isabs(rel) else os.path.join(base_dir, rel)
            if os.path.exists(abs_path):
                yield line_region, abs_path


def _phantom_set(view):
    ps = _phantom_sets.get(view.id())
    if ps is None:
        ps = sublime.PhantomSet(view, PREVIEW_KEY)
        _phantom_sets[view.id()] = ps
    return ps


def _render(abs_path):
    """Return (data_uri, dims_html) for a path, cached by mtime, or None."""
    try:
        mtime = os.path.getmtime(abs_path)
    except OSError:
        return None
    max_width = int(_setting("preview_max_width", 600))
    cached = _uri_cache.get(abs_path)
    if cached and cached[0] == (mtime, max_width):
        return cached[1], cached[2]
    uri = _data_uri(abs_path)
    if not uri:
        return None
    size = _image_size(abs_path)
    if size:
        w, h = size
        if w > max_width:
            h = int(h * max_width / w)
            w = max_width
        dims = ' width="%d" height="%d"' % (w, h)
    else:
        dims = ""
    _uri_cache[abs_path] = ((mtime, max_width), uri, dims)
    return uri, dims


def _render_previews(view):
    """(Re)build phantoms for all image refs in the view. Returns the count."""
    phantoms = []
    for line_region, abs_path in _image_refs(view):
        rendered = _render(abs_path)
        if not rendered:
            _log("could not read %r" % abs_path)
            continue
        uri, dims = rendered
        html = '<body><img src="%s"%s></body>' % (uri, dims)
        phantoms.append(
            sublime.Phantom(
                sublime.Region(line_region.end()),
                html,
                sublime.LAYOUT_BLOCK,
            )
        )
    _phantom_set(view).update(phantoms)
    return len(phantoms)


class PasteImagePreviewCommand(sublime_plugin.TextCommand):
    """Toggle inline previews of every image reference in the current file."""

    def run(self, edit):
        view = self.view
        vid = view.id()

        if vid in _previewing:
            _previewing.discard(vid)
            _phantom_set(view).update([])
            sublime.status_message("PasteImage: preview hidden")
            return

        _previewing.add(vid)
        count = _render_previews(view)
        sublime.status_message(
            "PasteImage: preview shown (%d image%s)"
            % (count, "" if count == 1 else "s")
        )


def _auto_preview(view):
    """Show previews for a freshly opened view if it has any image refs."""
    if not _setting("auto_preview", True):
        return
    if view.id() in _previewing:
        return
    _previewing.add(view.id())
    if _render_previews(view) == 0:
        _previewing.discard(view.id())


class PasteImageListener(sublime_plugin.EventListener):
    """Keep previews in sync with edits and show them on open."""

    def on_load_async(self, view):
        _auto_preview(view)

    def on_modified_async(self, view):
        if view.id() in _previewing:
            count = _render_previews(view)
            _debug("on_modified: view=%s re-rendered %d preview(s)" % (view.id(), count))

    def on_text_command(self, view, name, args):
        if _setting("debug", False) and name != "paste_image":
            _debug("text command %r %r on view=%s sel=%s" % (name, args, view.id(), list(view.sel())))

    def on_post_text_command(self, view, name, args):
        if _setting("debug", False) and name in ("paste", "paste_and_indent"):
            _debug("after %r: last line=%r" % (name, view.substr(view.line(view.sel()[0]))))

    def on_close(self, view):
        _previewing.discard(view.id())
        _phantom_sets.pop(view.id(), None)


def plugin_loaded():
    """Render previews for files already open when the plugin loads."""
    for window in sublime.windows():
        for view in window.views():
            _auto_preview(view)
