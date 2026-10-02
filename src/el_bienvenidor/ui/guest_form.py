"""Formulario nativo de datos del visitante (teclado real, layout completo)."""

from __future__ import annotations

from dataclasses import dataclass
import re
import tkinter as tk
from tkinter import ttk

from el_bienvenidor.config import UiSettings

_MAX_LEN = 40
_BLOCKED = set("<>{}[]\\`|$")


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
    root.configure(bg="#121c26")
    root.minsize(900, 620)
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
    style.configure("Kippu.TFrame", background="#121c26")
    style.configure("Card.TFrame", background="#f6f1e8")
    style.configure("Header.TLabel", background="#121c26", foreground="#fcfaf7", font=("Segoe UI", 28, "bold"))
    style.configure("Hint.TLabel", background="#121c26", foreground="#d6b08c", font=("Segoe UI", 13))
    style.configure("CardTitle.TLabel", background="#204e5e", foreground="#fcfaf7", font=("Segoe UI", 16, "bold"))
    style.configure("Headline.TLabel", background="#f6f1e8", foreground="#204e5e", font=("Segoe UI", 18, "bold"))
    style.configure("Field.TLabel", background="#121c26", foreground="#d6b08c", font=("Segoe UI", 10))
    style.configure("Photo.TLabel", background="#dce3e8", foreground="#6e767c", font=("Segoe UI", 14), anchor="center")
    style.configure("Kippu.TEntry", padding=8, fieldbackground="#fffdf9", font=("Segoe UI", 14))
    style.configure("Primary.TButton", font=("Segoe UI", 12, "bold"), padding=(18, 10))
    style.configure("Ghost.TButton", font=("Segoe UI", 11), padding=(14, 8))

    shell = ttk.Frame(root, style="Kippu.TFrame", padding=36)
    shell.pack(fill=tk.BOTH, expand=True)

    ttk.Label(shell, text="Datos del carnet", style="Header.TLabel").pack(anchor="w")
    ttk.Label(shell, text="Escriba con teclado normal (mayúsculas, tildes y símbolos). Luego confirme para pasar a la foto.", style="Hint.TLabel").pack(anchor="w", pady=(4, 24))

    body = ttk.Frame(shell, style="Kippu.TFrame")
    body.pack(fill=tk.BOTH, expand=True)
    body.columnconfigure(0, weight=1)
    body.columnconfigure(1, weight=1)

    card = tk.Frame(body, bg="#f6f1e8", highlightthickness=0)
    card.grid(row=0, column=0, sticky="n", padx=(0, 28))
    header = tk.Frame(card, bg="#204e5e", height=64)
    header.pack(fill=tk.X)
    tk.Label(header, text="KIPPU", bg="#204e5e", fg="#fcfaf7", font=("Segoe UI", 16, "bold")).pack(side=tk.LEFT, padx=20, pady=16)
    photo = tk.Label(card, text="La foto se tomará\ndespués del saludo", bg="#dce3e8", fg="#6e767c", font=("Segoe UI", 13), width=32, height=8)
    photo.pack(padx=24, pady=20, fill=tk.X)
    tk.Label(card, text=headline, bg="#f6f1e8", fg="#204e5e", font=("Segoe UI", 18, "bold")).pack(pady=(0, 8))
    preview_name = tk.StringVar(value="Nombre del visitante")
    preview_org = tk.StringVar(value="Organización")
    preview_role = tk.StringVar(value="Rol / cargo")
    tk.Label(card, textvariable=preview_name, bg="#f6f1e8", fg="#1c2226", font=("Segoe UI", 14, "bold")).pack()
    tk.Label(card, textvariable=preview_org, bg="#f6f1e8", fg="#3d4a52", font=("Segoe UI", 12)).pack(pady=(4, 0))
    tk.Label(card, textvariable=preview_role, bg="#f6f1e8", fg="#3d4a52", font=("Segoe UI", 12)).pack(pady=(2, 20))
    footer = tk.Frame(card, bg="#204e5e", height=36)
    footer.pack(fill=tk.X, side=tk.BOTTOM)
    tk.Label(footer, text="Carnet 10 × 15 cm", bg="#204e5e", fg="#fcfaf7", font=("Segoe UI", 9)).pack(pady=8)

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
        ttk.Label(form, text=label.upper(), style="Field.TLabel").pack(anchor="w", pady=(0, 4))
        entry = ttk.Entry(form, textvariable=var, style="Kippu.TEntry", font=("Segoe UI", 14))
        entry.pack(fill=tk.X, pady=(0, 16), ipady=6)
        entries.append(entry)

    def _confirm(_event: object | None = None) -> None:
        result["value"] = normalize_intake(name_var.get(), org_var.get(), role_var.get())
        root.destroy()

    def _skip(_event: object | None = None) -> None:
        result["value"] = GuestIntake("VISITANTE")
        root.destroy()

    actions = ttk.Frame(form, style="Kippu.TFrame")
    actions.pack(fill=tk.X, pady=(8, 0))
    ttk.Button(actions, text="Confirmar y abrir cámara", style="Primary.TButton", command=_confirm).pack(side=tk.LEFT)
    ttk.Button(actions, text="Continuar como visitante", style="Ghost.TButton", command=_skip).pack(side=tk.LEFT, padx=(12, 0))
    ttk.Label(form, text="Enter confirma  ·  Esc continúa como Visitante", style="Hint.TLabel").pack(anchor="w", pady=(18, 0))

    root.bind("<Return>", _confirm)
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
