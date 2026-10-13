"""Application stylesheet and color scheme."""

from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gtk  # noqa: E402

STYLE_PATH = Path(__file__).with_name("style.css")


def apply_style() -> None:
    """Force the dark scheme, font rendering and style.css for the whole display."""
    Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_DARK)
    # GTK's automatic font rendering draws FantasqueSansM at 14pt with the top
    # row of the glyphs cut off (flat 0, 6, 8, 9). Manual mode follows the
    # system's fontconfig hinting, like kitty, and draws whole glyphs.
    Gtk.Settings.get_default().set_property("gtk-font-rendering", Gtk.FontRendering.MANUAL)
    provider = Gtk.CssProvider()
    provider.load_from_path(str(STYLE_PATH))
    Gtk.StyleContext.add_provider_for_display(
        Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )
