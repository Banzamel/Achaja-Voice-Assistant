"""Wspolny wyglad okien Achai (app.py i setup/configure.py).

Jasny i ciemny motyw ttk (na bazie "clam"): zaokraglone przyciski, pola, zakladki i suwaki
rysowane przez Pillow, jedna paleta dla calego programu i ciemny pasek tytulu w trybie ciemnym.
Tryb ustawia config.json: app.theme = "auto" (jak aplikacje w Windows) | "light" | "dark".
"""
import ctypes

PALETTES = {
    "light": {
        "bg": "#f5f4f9", "surface": "#ffffff", "surface2": "#eeedf4", "hover": "#e6e4ef", "pressed": "#dbd8e7",
        "border": "#dddbe6", "text": "#1c1a24", "muted": "#6b6878", "faint": "#a3a0b0",
        "accent": "#6c4cd4", "accent_hover": "#7b5de0", "accent_pressed": "#5a3cc0", "on_accent": "#ffffff",
        "accent_soft": "#ebe5fd", "accent_text": "#5a3cc0", "select": "#ddd3fb",
        "green": "#2e9b57", "red": "#d93a3a", "orange": "#d98c1a", "grey": "#9a97a8", "note": "#9a5a00",
    },
    "dark": {
        "bg": "#1b1a21", "surface": "#25242d", "surface2": "#2f2e38", "hover": "#393844", "pressed": "#45444f",
        "border": "#3b3a46", "text": "#ecebf2", "muted": "#a3a1b0", "faint": "#6f6d7c",
        "accent": "#7e5ff0", "accent_hover": "#8f74f5", "accent_pressed": "#6a4cdc", "on_accent": "#ffffff",
        "accent_soft": "#312a4f", "accent_text": "#b9a8ff", "select": "#463a75",
        "green": "#3fbf72", "red": "#f0575b", "orange": "#f0a43a", "grey": "#7d7a8c", "note": "#e0a050",
    },
}
FONT = "Segoe UI"
FONT_BOLD = "Segoe UI Semibold"


def system_mode():
    """Tryb aplikacji z ustawien Windows (Personalizacja > Kolory)."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
            return "light" if winreg.QueryValueEx(key, "AppsUseLightTheme")[0] else "dark"
    except (ImportError, OSError):
        return "light"


def resolve(pref):
    return pref if pref in PALETTES else system_mode()


def blend(c1, c2, t):
    """Kolor posredni miedzy c1 a c2 (t=0 -> c1, t=1 -> c2)."""
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b))


class Theme:
    def __init__(self, root, pref="auto"):
        self.root = root
        self.pref = pref
        try:
            self.scale = max(1.0, root.winfo_fpixels("1i") / 96)
        except Exception:
            self.scale = 1.0
        self.images = {}  # obrazy elementow musza zyc tak dlugo jak motyw
        self.mode = None
        self.p = PALETTES["light"]
        self.mono = "Consolas"
        try:
            from tkinter import font as tkfont
            if "Cascadia Mono" in tkfont.families(root):
                self.mono = "Cascadia Mono"
            for name, size in (("TkDefaultFont", 10), ("TkTextFont", 10), ("TkMenuFont", 10)):
                tkfont.nametofont(name, root).configure(family=FONT, size=size)
        except Exception:
            pass
        self.apply()

    def px(self, value):
        return max(1, round(value * self.scale))

    def stale(self):
        """True, gdy ustawienie Windows (tryb auto) zmienilo sie od ostatniego apply()."""
        return resolve(self.pref) != self.mode

    def apply(self, pref=None):
        """Ustawia motyw; zwraca True, gdy zmienil sie tryb (trzeba przemalowac zwykle widzety tk)."""
        from tkinter import ttk
        if pref is not None:
            self.pref = pref
        mode = resolve(self.pref)
        changed = mode != self.mode
        self.mode, self.p = mode, PALETTES[mode]
        style = ttk.Style(self.root)
        name = f"achaja-{mode}"
        if name not in style.theme_names():
            style.theme_create(name, parent="clam")
            style.theme_use(name)
            self._build(style)
        else:
            style.theme_use(name)
        p = self.p
        self.root.configure(background=p["bg"])
        for pattern, value in (("background", p["surface"]), ("foreground", p["text"]),
                               ("selectBackground", p["select"]), ("selectForeground", p["text"])):
            self.root.option_add(f"*TCombobox*Listbox.{pattern}", value)
        self.root.option_add("*TCombobox*Listbox.font", (FONT, 10))
        self.root.option_add("*TCombobox*Listbox.relief", "flat")
        self.titlebar(self.root)
        return changed

    # --- obrazki elementow ---
    def _img(self, w, h, r, fill=None, outline=None, inset=(0, 0), check=None):
        from PIL import Image, ImageDraw, ImageTk
        k = 4  # rysujemy 4x wieksze i zmniejszamy - gladkie krawedzie
        img = Image.new("RGBA", (w * k, h * k), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        left, top, right, bottom = (inset * 2)[:4]  # (x, y) albo (lewo, gora, prawo, dol)
        box = [left * k, top * k, (w - right) * k - 1, (h - bottom) * k - 1]
        if fill or outline:
            d.rounded_rectangle(box, radius=r * k, fill=fill, outline=outline, width=max(1, round(self.scale)) * k)
        if check:
            x0, y0, x1, y1 = box
            s = x1 - x0
            pts = [(x0 + s * 0.25, y0 + s * 0.52), (x0 + s * 0.43, y0 + s * 0.70), (x0 + s * 0.76, y0 + s * 0.33)]
            d.line(pts, fill=check, width=round(s * 0.12), joint="curve")
        img = img.resize((w, h), Image.LANCZOS)
        photo = ImageTk.PhotoImage(img, master=self.root)
        self.images.setdefault(self.mode, []).append(photo)
        return photo

    def _element(self, style, name, size, radius, states, border=None, inset=(0, 0), sticky="nsew", padding=0):
        """states: lista (stan ttk albo "" dla domyslnego, kolor wypelnienia, kolor obramowania[, znaczek])."""
        w, h = size
        imgs = []
        for spec in states:
            state, fill, outline = spec[:3]
            mark = spec[3] if len(spec) > 3 else None
            imgs.append((state, self._img(w, h, radius, fill, outline, inset, mark)))
        default = next(img for state, img in imgs if not state)
        specs = [(state, img) for state, img in imgs if state]
        kw = {"sticky": sticky, "padding": padding}  # odstepy wewnatrz daje styl, nie obrazek
        if border is not None:
            kw["border"] = border
        style.element_create(name, "image", default, *specs, **kw)

    def _build(self, style):
        p, px = self.p, self.px
        light = self.mode == "light"
        r = px(8)
        font, bold = (FONT, 10), (FONT_BOLD, 10)

        style.configure(".", background=p["bg"], foreground=p["text"], font=font, troughcolor=p["bg"],
                        bordercolor=p["border"], lightcolor=p["bg"], darkcolor=p["bg"], focuscolor=p["accent"],
                        selectbackground=p["select"], selectforeground=p["text"], insertcolor=p["text"],
                        arrowcolor=p["muted"], fieldbackground=p["surface"])
        style.map(".", foreground=[("disabled", p["faint"])])

        # przyciski: zwykly, akcentowy i "duch" (bez tla, np. menu)
        btn_fill = p["surface"] if light else p["surface2"]
        size, pad = (px(40), px(32)), r + px(2)
        self._element(style, "A.btn", size, r, [
            ("disabled", p["surface2"], p["border"]), ("pressed", p["pressed"], p["border"]),
            ("active", p["hover"], p["border"]), ("", btn_fill, p["border"])], border=pad)
        self._element(style, "A.accent", size, r, [
            ("disabled", blend(p["accent"], p["bg"], 0.55), None), ("pressed", p["accent_pressed"], None),
            ("active", p["accent_hover"], None), ("", p["accent"], None)], border=pad)
        self._element(style, "A.ghost", size, r, [
            ("pressed", p["pressed"], None), ("active", p["hover"], None), ("", None, None)], border=pad)
        for name, el in (("TButton", "A.btn"), ("Accent.TButton", "A.accent"), ("Ghost.TButton", "A.ghost")):
            style.layout(name, [(el, {"sticky": "nsew", "children": [
                ("Button.padding", {"sticky": "nsew", "children": [("Button.label", {"sticky": "nsew"})]})]})])
        style.configure("TButton", padding=(px(14), px(5)), anchor="center", foreground=p["text"])
        style.configure("Accent.TButton", foreground=p["on_accent"], font=bold)
        style.map("Accent.TButton", foreground=[("disabled", p["bg"])])
        style.configure("Ghost.TButton", padding=(px(6), px(2)), foreground=p["muted"], font=(FONT, 12))
        style.map("Ghost.TButton", foreground=[("active", p["text"])])

        # pola tekstowe i listy rozwijane
        self._element(style, "A.field", (px(40), px(32)), px(6), [
            ("disabled", p["surface2"], p["border"]), ("focus", p["surface"], p["accent"]),
            ("hover", p["surface"], p["faint"]), ("", p["surface"], p["border"])], border=px(8))
        style.layout("TEntry", [("A.field", {"sticky": "nsew", "children": [
            ("Entry.padding", {"sticky": "nsew", "children": [("Entry.textarea", {"sticky": "nsew"})]})]})])
        style.configure("TEntry", padding=(px(4), px(3)), fieldbackground=p["surface"])
        style.layout("TCombobox", [("A.field", {"sticky": "nsew", "children": [
            ("Combobox.downarrow", {"side": "right", "sticky": "ns"}),
            ("Combobox.padding", {"expand": "1", "sticky": "nsew", "children": [
                ("Combobox.textarea", {"sticky": "nsew"})]})]})])
        style.configure("TCombobox", padding=(px(4), px(3)), background=p["surface"], fieldbackground=p["surface"],
                        bordercolor=p["surface"], lightcolor=p["surface"], darkcolor=p["surface"],
                        arrowcolor=p["muted"], arrowsize=px(12))
        style.map("TCombobox", background=[("active", p["surface"]), ("pressed", p["surface"])],
                  fieldbackground=[("readonly", p["surface"])], arrowcolor=[("active", p["text"])],
                  bordercolor=[("focus", p["surface"])], lightcolor=[("focus", p["surface"])])

        # pole wyboru z zaokraglonym kwadratem (obrazek ma z prawej odstep od etykiety)
        box = px(18)
        csize, cinset = (box + px(8), box + px(2)), (0, px(1), px(8), px(1))
        self._element(style, "A.check", csize, px(4), [
            ("selected disabled", p["faint"], None, p["surface"]),
            ("selected active", p["accent_hover"], None, p["on_accent"]),
            ("selected", p["accent"], None, p["on_accent"]),
            ("active", p["hover"], p["muted"]), ("", p["surface"], p["faint"])], inset=cinset, sticky="")
        style.layout("TCheckbutton", [("Checkbutton.padding", {"sticky": "nsew", "children": [
            ("A.check", {"side": "left", "sticky": ""}), ("Checkbutton.label", {"side": "left", "sticky": "nsew"})]})])
        style.configure("TCheckbutton", padding=(0, px(3)))

        # zakladki jako "pigulki"
        self._element(style, "A.tab", (px(40), px(32)), px(8), [
            ("selected", p["accent_soft"], None), ("active", p["hover"], None), ("", None, None)],
            border=px(10), inset=(px(2), 0))
        style.layout("TNotebook.Tab", [("A.tab", {"sticky": "nsew", "children": [
            ("Notebook.padding", {"sticky": "nsew", "children": [("Notebook.label", {"sticky": ""})]})]})])
        style.configure("TNotebook", background=p["bg"], borderwidth=0, tabmargins=(px(10), px(2), px(10), px(8)))
        style.configure("TNotebook.Tab", padding=(px(16), px(5)), foreground=p["muted"], font=bold)
        style.map("TNotebook.Tab", foreground=[("selected", p["accent_text"]), ("active", p["text"])])
        style.layout("TNotebook", [("Notebook.client", {"sticky": "nsew"})])
        style.configure("TNotebook", bordercolor=p["bg"], lightcolor=p["bg"], darkcolor=p["bg"])

        # waskie, zaokraglone suwaki bez strzalek
        self._element(style, "Vertical.Scrollbar.thumb", (px(12), px(32)), px(4), [
            ("pressed", p["muted"], None), ("active", p["faint"], None),
            ("", blend(p["faint"], p["bg"], 0.35), None)], border=px(6), inset=(px(3), px(1)))
        style.layout("Vertical.TScrollbar", [("Vertical.Scrollbar.trough", {"sticky": "ns", "children": [
            ("Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nsew"})]})])
        style.configure("Vertical.TScrollbar", troughcolor=p["bg"], bordercolor=p["bg"], background=p["bg"],
                        lightcolor=p["bg"], darkcolor=p["bg"], arrowsize=px(12), gripcount=0)
        style.configure("Card.Vertical.TScrollbar", troughcolor=p["surface"], bordercolor=p["surface"],
                        background=p["surface"], lightcolor=p["surface"], darkcolor=p["surface"])
        style.layout("Card.Vertical.TScrollbar", style.layout("Vertical.TScrollbar"))

        # tabela (konta pocztowe)
        style.configure("Treeview", background=p["surface"], fieldbackground=p["surface"], foreground=p["text"],
                        rowheight=px(28), borderwidth=1, bordercolor=p["border"], lightcolor=p["surface"],
                        darkcolor=p["surface"])
        style.map("Treeview", background=[("selected", p["select"])], foreground=[("selected", p["text"])])
        style.configure("Treeview.Heading", background=p["surface2"], foreground=p["muted"], font=(FONT_BOLD, 9),
                        relief="flat", borderwidth=0, padding=(px(8), px(5)), bordercolor=p["border"],
                        lightcolor=p["surface2"], darkcolor=p["surface2"])
        style.map("Treeview.Heading", background=[("active", p["hover"])])

        # karty, baner, pigulka stanu
        self._element(style, "A.card", (px(48), px(48)), px(12), [("", p["surface"], p["border"])], border=px(14))
        self._element(style, "A.input", (px(48), px(48)), px(12), [
            ("focus", p["surface"], p["accent"]), ("", p["surface"], p["border"])], border=px(14))
        self._element(style, "A.banner", (px(48), px(48)), px(12), [("", p["accent_soft"], None)], border=px(14))
        self._element(style, "A.pill", (px(48), px(40)), px(20), [("", p["surface"], p["border"])], border=px(20))
        for name, el in (("Card.TFrame", "A.card"), ("Input.TFrame", "A.input"),
                         ("Banner.TFrame", "A.banner"), ("Pill.TFrame", "A.pill")):
            style.layout(name, [(el, {"sticky": "nsew"})])

        # etykiety
        style.configure("TLabel", background=p["bg"], foreground=p["text"])
        style.configure("Muted.TLabel", foreground=p["muted"])
        style.configure("Small.TLabel", foreground=p["muted"], font=(FONT, 9))
        style.configure("Title.TLabel", font=(FONT_BOLD, 16))
        style.configure("Sub.TLabel", foreground=p["muted"])
        style.configure("Section.TLabel", foreground=p["muted"], font=(FONT_BOLD, 9))
        style.configure("Card.TLabel", background=p["surface"])
        style.configure("CardTitle.TLabel", background=p["surface"], font=(FONT_BOLD, 11))
        style.configure("CardMuted.TLabel", background=p["surface"], foreground=p["muted"])
        style.configure("Status.TLabel", background=p["surface"], font=(FONT_BOLD, 10))
        style.configure("Banner.TLabel", background=p["accent_soft"], foreground=p["accent_text"], font=bold)
        style.configure("Brand.TLabel", font=(FONT_BOLD, 13))
        style.configure("Card.TCheckbutton", background=p["surface"])
        style.configure("TFrame", background=p["bg"])
        style.configure("Plain.TFrame", background=p["surface"])
        style.configure("TSeparator", background=p["border"])

    # --- zwykle widzety tk i okna ---
    def text(self, widget, surface=True):
        p = self.p
        widget.configure(background=p["surface"] if surface else p["bg"], foreground=p["text"],
                         insertbackground=p["text"], selectbackground=p["select"], selectforeground=p["text"],
                         inactiveselectbackground=p["select"], highlightthickness=0, borderwidth=0, relief="flat")

    def listbox(self, widget):
        p = self.p
        widget.configure(background=p["surface"], foreground=p["text"], selectbackground=p["accent_soft"],
                         selectforeground=p["text"], highlightthickness=0, borderwidth=0, relief="flat",
                         activestyle="none", font=(FONT, 10))

    def menu(self, widget):
        p = self.p
        widget.configure(background=p["surface"], foreground=p["text"], activebackground=p["accent_soft"],
                         activeforeground=p["text"], relief="flat", borderwidth=0, font=(FONT, 10))

    def titlebar(self, win):
        """Ciemny/jasny pasek tytulu (Windows 10 2004+ i 11)."""
        try:
            win.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(win.winfo_id()) or win.winfo_id()
            value = ctypes.c_int(1 if self.mode == "dark" else 0)
            for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (nowe / starsze kompilacje)
                if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(value),
                                                              ctypes.sizeof(value)) == 0:
                    break
            if win.winfo_viewable():  # Windows 10 przemalowuje pasek dopiero po zmianie okna
                win.wm_attributes("-alpha", 0.99)
                win.after(30, lambda: win.wm_attributes("-alpha", 1.0))
        except Exception:
            pass
