"""Formulario nativo de datos del visitante (teclado real, layout completo)."""

from __future__ import annotations

from dataclasses import dataclass
import re
import tkinter as tk
from tkinter import ttk

from el_bienvenidor.config import UiSettings

_MAX_LEN = 40
_BLOCKED = set("<>{}[]\\`|$")

_BG = "#0b1218"
_BG_SOFT = "#121c26"
_GOLD = "#d4b070"
_CREAM = "#f6f1e8"
_INK = "#1c2226"
_MUTED = "#5a6670"
_TEAL = "#204e5e"
_HINT = "#c9b08c"
_PHOTO = "#dce3e8"


@dataclass(frozen=True)
class GuestIntake:
    """Datos capturados antes de la foto; alimentan ``CardData``."""

    guest_name: str
    organization: str | None = None
    role: str | None = None


def sanitize_field(value: str, *, required: bool = False) -> str | None:
    cleaned = "".join(ch for ch in value if ch.isprintable() and ch not in _BLOCKED)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()[:_MAX_LEN]
    if not cleaned:
        return None if not required else "VISITANTE"
    return cleaned


def normalize_intake(name: str, organization: str = "", role: str = "") -> GuestIntake:
    guest_name = sanitize_field(name, required=True) or "VISITANTE"
    return GuestIntake(
        guest_name=guest_name,
        organization=sanitize_field(organization),
        role=sanitize_field(role),
    )


def _prompt_guest_card_tk(
    settings: UiSettings,
    *,
    headline: str,
    initial: GuestIntake | None,
) -> GuestIntake:
    result: dict[str, GuestIntake | None] = {"value": None}

    root = tk.Tk()
    root.title(f"{settings.window_name} — Datos del carnet")
    root.configure(bg=_BG)
    root.minsize(980, 680)
    if settings.fullscreen:
        try:
            root.attributes("-fullscreen", True)
        except tk.TclError:
            root.state("zoomed")

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure("Kippu.TFrame", background=_BG)
    style.configure("Card.TFrame", background=_CREAM)
    style.configure("Header.TLabel", background=_BG, foreground="#fcfaf7", font=("Segoe UI", 32, "bold"))
    style.configure("Hint.TLabel", background=_BG, foreground=_HINT, font=("Segoe UI", 13))
    style.configure("Eyebrow.TLabel", background=_BG, foreground=_GOLD, font=("Segoe UI", 11, "bold"))
    style.configure("Field.TLabel", background=_BG, foreground=_GOLD, font=("Segoe UI", 10, "bold"))
    style.configure("Kippu.TEntry", padding=10, fieldbackground="#fffdf9", foreground=_INK, font=("Segoe UI", 15))
    style.map("Kippu.TEntry", fieldbackground=[("focus", "#fff8ea")])
    style.configure(
        "Primary.TButton",
        font=("Segoe UI", 12, "bold"),
        padding=(22, 12),
        background=_GOLD,
        foreground=_INK,
        borderwidth=0,
    )
    style.map("Primary.TButton", background=[("active", "#e4c48a")])
    style.configure(
        "Ghost.TButton",
        font=("Segoe UI", 11),
        padding=(16, 11),
        background=_BG_SOFT,
        foreground="#fcfaf7",
        borderwidth=0,
    )
    style.map("Ghost.TButton", background=[("active", "#1b2834")])

    shell = ttk.Frame(root, style="Kippu.TFrame", padding=44)
    shell.pack(fill=tk.BOTH, expand=True)

    ttk.Label(shell, text="KIPPU  ·  RECEPCIÓN", style="Eyebrow.TLabel").pack(anchor="w")
    ttk.Label(shell, text="Datos del carnet", style="Header.TLabel").pack(anchor="w", pady=(6, 0))
    ttk.Label(
        shell,
        text="Escriba con teclado normal (mayúsculas, tildes y símbolos). Luego confirme para pasar a la foto.",
        style="Hint.TLabel",
    ).pack(anchor="w", pady=(8, 28))

    gold_rule = tk.Frame(shell, bg=_GOLD, height=2)
    gold_rule.pack(fill=tk.X, pady=(0, 28))

    body = ttk.Frame(shell, style="Kippu.TFrame")
    body.pack(fill=tk.BOTH, expand=True)
    body.columnconfigure(0, weight=1)
    body.columnconfigure(1, weight=1)

    card_shadow = tk.Frame(body, bg="#070c10")
    card_shadow.grid(row=0, column=0, sticky="n", padx=(0, 36))
    card = tk.Frame(card_shadow, bg=_CREAM, highlightthickness=0)
    card.pack(padx=3, pady=5)

    header = tk.Frame(card, bg=_TEAL, height=72)
    header.pack(fill=tk.X)
    tk.Label(header, text="KIPPU", bg=_TEAL, fg="#fcfaf7", font=("Segoe UI", 17, "bold")).pack(side=tk.LEFT, padx=22, pady=18)
    tk.Label(header, text="10 × 15 cm", bg=_TEAL, fg=_GOLD, font=("Segoe UI", 10)).pack(side=tk.RIGHT, padx=22)

    photo = tk.Label(
        card,
        text="La foto se tomará\ndespués del saludo",
        bg=_PHOTO,
        fg=_MUTED,
        font=("Segoe UI", 13),
        width=34,
        height=9,
    )
    photo.pack(padx=26, pady=22, fill=tk.X)

    tk.Label(card, text=headline, bg=_CREAM, fg=_TEAL, font=("Segoe UI", 20, "bold")).pack(pady=(0, 10))
    preview_name = tk.StringVar(value="Nombre del visitante")
    preview_org = tk.StringVar(value="Organización")
    preview_role = tk.StringVar(value="Rol / cargo")
    tk.Label(card, textvariable=preview_name, bg=_CREAM, fg=_INK, font=("Segoe UI", 15, "bold")).pack()
    tk.Label(card, textvariable=preview_org, bg=_CREAM, fg="#3d4a52", font=("Segoe UI", 12)).pack(pady=(6, 0))
    tk.Label(card, textvariable=preview_role, bg=_CREAM, fg="#3d4a52", font=("Segoe UI", 12)).pack(pady=(2, 28))
    footer = tk.Frame(card, bg=_TEAL, height=40)
    footer.pack(fill=tk.X, side=tk.BOTTOM)
    tk.Label(footer, text="Carnet de bienvenida", bg=_TEAL, fg="#fcfaf7", font=("Segoe UI", 9)).pack(pady=10)

    form = ttk.Frame(body, style="Kippu.TFrame")
    form.grid(row=0, column=1, sticky="nwe")

    name_var = tk.StringVar(value=initial.guest_name if initial and initial.guest_name != "VISITANTE" else "")
    org_var = tk.StringVar(value=(initial.organization or "") if initial else "")
    role_var = tk.StringVar(value=(initial.role or "") if initial else "")

    def _limit(var: tk.StringVar) -> None:
        if len(var.get()) > _MAX_LEN:
            var.set(var.get()[:_MAX_LEN])

    def _refresh(*_args: object) -> None:
        _limit(name_var)
        _limit(org_var)
        _limit(role_var)
        preview_name.set(name_var.get().strip() or "Nombre del visitante")
        preview_org.set(org_var.get().strip() or "Organización")
        preview_role.set(role_var.get().strip() or "Rol / cargo")

    for var in (name_var, org_var, role_var):
        var.trace_add("write", _refresh)

    fields = (
        ("Nombre", name_var),
        ("Organización", org_var),
        ("Rol / cargo", role_var),
    )
    entries: list[ttk.Entry] = []
    for label, var in fields:
        ttk.Label(form, text=label.upper(), style="Field.TLabel").pack(anchor="w", pady=(0, 6))
        entry = ttk.Entry(form, textvariable=var, style="Kippu.TEntry", font=("Segoe UI", 15))
        entry.pack(fill=tk.X, pady=(0, 18), ipady=8)
        entries.append(entry)

    def _confirm(_event: object | None = None) -> None:
        result["value"] = normalize_intake(name_var.get(), org_var.get(), role_var.get())
        root.destroy()

    def _skip(_event: object | None = None) -> None:
        result["value"] = GuestIntake("VISITANTE")
        root.destroy()

    actions = ttk.Frame(form, style="Kippu.TFrame")
    actions.pack(fill=tk.X, pady=(10, 0))
    confirm_btn = ttk.Button(actions, text="Confirmar y abrir cámara", style="Primary.TButton", command=_confirm)
    confirm_btn.pack(side=tk.LEFT)
    skip_btn = ttk.Button(actions, text="Continuar como visitante", style="Ghost.TButton", command=_skip)
    skip_btn.pack(side=tk.LEFT, padx=(12, 0))
    ttk.Label(
        form,
        text="Enter o Tab: siguiente campo (en el último confirma)   ·   Ctrl+Enter: confirmar directo   ·   Esc: como Visitante",
        style="Hint.TLabel",
    ).pack(anchor="w", pady=(20, 0))

    for idx, entry in enumerate(entries):
        def _make_enter_handler(i: int):
            def _handler(_event: object) -> str:
                if i < len(entries) - 1:
                    next_e = entries[i + 1]
                    next_e.focus_set()
                    next_e.icursor(tk.END)
                else:
                    _confirm()
                return "break"
            return _handler

        def _make_down_handler(i: int):
            def _handler(_event: object) -> str:
                if i < len(entries) - 1:
                    next_e = entries[i + 1]
                    next_e.focus_set()
                    next_e.icursor(tk.END)
                else:
                    confirm_btn.focus_set()
                return "break"
            return _handler

        def _make_up_handler(i: int):
            def _handler(_event: object) -> str:
                if i > 0:
                    prev_e = entries[i - 1]
                    prev_e.focus_set()
                    prev_e.icursor(tk.END)
                return "break"
            return _handler

        entry.bind("<Return>", _make_enter_handler(idx))
        entry.bind("<KP_Enter>", _make_enter_handler(idx))
        entry.bind("<Down>", _make_down_handler(idx))
        entry.bind("<Up>", _make_up_handler(idx))

    confirm_btn.bind("<Return>", lambda _e: (_confirm(), "break")[1])
    confirm_btn.bind("<KP_Enter>", lambda _e: (_confirm(), "break")[1])
    skip_btn.bind("<Return>", lambda _e: (_skip(), "break")[1])
    skip_btn.bind("<KP_Enter>", lambda _e: (_skip(), "break")[1])

    root.bind("<Control-Return>", _confirm)
    root.bind("<Control-KP_Enter>", _confirm)
    root.bind("<Escape>", _skip)
    entries[0].focus_set()
    _refresh()
    root.protocol("WM_DELETE_WINDOW", _skip)
    root.mainloop()
    return result["value"] or GuestIntake("VISITANTE")


def prompt_guest_card(
    settings: UiSettings,
    *,
    headline: str = "¡Bienvenido!",
    initial: GuestIntake | None = None,
    force_default: bool = False,
) -> GuestIntake:
    """Formulario nativo. Con ``force_default`` no abre ventana."""
    fallback = initial or GuestIntake("VISITANTE")
    if force_default or not settings.guest_form_enabled:
        return fallback
    try:
        return _prompt_guest_card_tk(settings, headline=headline, initial=initial)
    except tk.TclError:
        return prompt_guest_card_console(headline)


def prompt_guest_card_console(headline: str = "¡Bienvenido!") -> GuestIntake:
    """Fallback de consola para entornos sin GUI o scripts de diagnóstico."""
    print(f"\n=== Datos del carnet ({headline}) ===")
    name = input("Nombre: ").strip()
    organization = input("Organización (opcional): ").strip()
    role = input("Rol / cargo (opcional): ").strip()
    return normalize_intake(name, organization, role)
