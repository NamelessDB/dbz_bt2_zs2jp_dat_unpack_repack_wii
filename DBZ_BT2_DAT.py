"""
Dragon Ball Z: Sparking! NEO / Tenkaichi 2 (Wii) — DAT Unpacker/Repacker
File: zs2jp.dat  (Japan region, 1478 MB)

ARCHIVE FORMAT  (all offsets/sizes are big-endian PowerPC)
──────────────────────────────────────────────────────────
Header (32 bytes):
  0x00  num_files   uint32 BE  →  45 660
  0x04  total_size  uint32 BE  →  1 550 640 640 bytes
  0x08  padding     24 × 0x00

Entry table (16 bytes × num_files, at offset 0x20):
  +0x00  data_offset   uint32 BE
  +0x04  data_size     uint32 BE   (raw, no compression)
  +0x08  dec_size      uint32 BE   (always == data_size)
  +0x0C  flags         uint32 BE   (always 0)

Data section: raw blobs at their offsets, 32-byte aligned.
No filenames stored — files identified by index only.

FILE TYPES INSIDE
─────────────────
  GSCF  760 files  Wii audio container (NintendoWare, little-endian internally)
                   Sub-chunks: GSHD · GSCD · GSAC · GSDT · EOFC
                   Codec: DSP-ADPCM  →  convert with vgmstream / BrawlBox
  .bin  rest       Binary game data: models, textures, scripts, animations
                   Empty entries (size=0 or all-zero) are skipped by default.
"""

import struct
import os
import threading
import customtkinter as ctk
from tkinter import filedialog, messagebox
from pathlib import Path




HEADER_SIZE = 0x20
ENTRY_SIZE  = 16
ENTRY_FMT   = ">IIII"   # offset, size, dec_size, flags — big-endian
DATA_ALIGN  = 0x20


def _align(n, a=DATA_ALIGN):
    return (n + a - 1) & ~(a - 1)


def read_entries(data: bytes):
    """Parse header + entry table. Handles partial files gracefully."""
    if len(data) < HEADER_SIZE:
        raise ValueError("File too small to be a valid archive.")
    num_files, total_size = struct.unpack(">II", data[:8])
    table_end = HEADER_SIZE + num_files * ENTRY_SIZE
    if table_end > len(data):
        num_files = (len(data) - HEADER_SIZE) // ENTRY_SIZE
    entries = []
    for i in range(num_files):
        pos = HEADER_SIZE + i * ENTRY_SIZE
        offset, size, dec_size, flags = struct.unpack(ENTRY_FMT, data[pos:pos + ENTRY_SIZE])
        entries.append({"index": i, "offset": offset, "size": size,
                        "dec_size": dec_size, "flags": flags})
    return num_files, total_size, entries


_MAGIC_EXT = {
    b"GSCF": ".gscf",
    b"RARC": ".rarc",
    b"\x89PNG": ".png",
    b"BM":   ".bmp",
    b"RIFF": ".riff",
}

def detect_ext(blob: bytes) -> str:
    for magic, ext in _MAGIC_EXT.items():
        if blob[:len(magic)] == magic:
            return ext
    return ".bin"

def _is_empty(blob: bytes) -> bool:
    return not any(blob)




def unpack(dat_path: str, out_dir: str,
           skip_empty: bool = True,
           progress_cb=None, log_cb=None):
    with open(dat_path, "rb") as f:
        data = f.read()

    num_files, total_size, entries = read_entries(data)
    os.makedirs(out_dir, exist_ok=True)

    is_full = len(data) >= total_size
    if log_cb:
        log_cb(f"Archivo  : {len(data)/1024/1024:.1f} MB  "
               f"({'completo ✓' if is_full else '⚠ parcial — faltan partes'})")
        log_cb(f"Entradas : {num_files:,}  |  tamaño declarado {total_size/1024/1024:.1f} MB\n")

    extracted = skipped = out_of_range = 0
    for idx, e in enumerate(entries):
        off, sz = e["offset"], e["size"]
        if sz == 0:
            skipped += 1
        elif off + sz > len(data):
            out_of_range += 1
        else:
            blob = data[off: off + sz]
            if skip_empty and _is_empty(blob):
                skipped += 1
            else:
                ext   = detect_ext(blob)
                fname = os.path.join(out_dir, f"{idx:05d}{ext}")
                with open(fname, "wb") as f:
                    f.write(blob)
                extracted += 1
        if progress_cb:
            progress_cb((idx + 1) / len(entries))

    if log_cb:
        log_cb(f"Extraídos   : {extracted:,}")
        log_cb(f"Omitidos    : {skipped:,}  (vacíos/null)")
        log_cb(f"Fuera rango : {out_of_range:,}  (archivo truncado)")
    return extracted, skipped, out_of_range




def repack(src_dir: str, out_path: str,
           num_slots: int | None = None,
           progress_cb=None, log_cb=None):
    """
    Reempaqueta una carpeta de archivos extraídos en un .dat.
    Los archivos deben llamarse  NNNNN[.ext]  (índice de 5 dígitos).
    Los índices faltantes se guardan como entradas vacías.
    """
    files = {}
    for fname in os.listdir(src_dir):
        stem = Path(fname).stem
        if stem.isdigit():
            files[int(stem)] = os.path.join(src_dir, fname)

    if not files:
        raise ValueError("No se encontraron archivos numerados en la carpeta.")

    max_idx   = max(files.keys())
    num_files = num_slots if num_slots is not None else max_idx + 1

    if log_cb:
        log_cb(f"Fuente  : {len(files):,} archivos  (índice máx. {max_idx})")
        log_cb(f"Slots   : {num_files:,}")

    data_start = _align(HEADER_SIZE + num_files * ENTRY_SIZE)
    entries = []
    blobs   = []
    cur_off = data_start

    for i in range(num_files):
        if i in files:
            with open(files[i], "rb") as f:
                blob = f.read()
            sz  = len(blob)
            pad = _align(sz) - sz
            entries.append((cur_off, sz, sz, 0))
            blobs.append(blob + b"\x00" * pad)
            cur_off += sz + pad
        else:
            entries.append((0, 0, 0, 0))
            blobs.append(b"")
        if progress_cb:
            progress_cb((i + 1) / num_files * 0.5)

    total_size = cur_off
    out = bytearray()
    out += struct.pack(">II", num_files, total_size)
    out += b"\x00" * 24
    for e in entries:
        out += struct.pack(ENTRY_FMT, *e)
    while len(out) < data_start:
        out += b"\x00"
    for i, blob in enumerate(blobs):
        out += blob
        if progress_cb and i % 200 == 0:
            progress_cb(0.5 + i / len(blobs) * 0.5)

    with open(out_path, "wb") as f:
        f.write(out)

    if log_cb:
        log_cb(f"Salida  : {len(out)/1024/1024:.1f} MB → {out_path}")
    return len(files)




ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

BG    = "#12121e"
PANEL = "#1a1a2e"
CARD  = "#16213e"
ACCT  = "#e94560"
BLUE  = "#0f3460"
TEXT  = "#eaeaea"
DIM   = "#7a7a9a"

FH = ("Segoe UI", 21, "bold")
FB = ("Segoe UI", 13, "bold")
FN = ("Segoe UI", 12)
FM = ("Consolas", 11)


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("DBZ Tenkaichi 2 · DAT Tool")
        self.geometry("860x700")
        self.minsize(700, 580)
        self.configure(fg_color=BG)

        self._dat   = ctk.StringVar()
        self._uout  = ctk.StringVar()
        self._src   = ctk.StringVar()
        self._rout  = ctk.StringVar()
        self._slots = ctk.StringVar(value="45660")
        self._skip  = ctk.BooleanVar(value=True)
        self._prog  = ctk.DoubleVar(value=0.0)

        self._build()

    

    def _build(self):
        # Header
        bar = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=0, height=68)
        bar.pack(fill="x")
        bar.pack_propagate(False)
        ctk.CTkLabel(bar, text="⚡  DBZ Tenkaichi 2  ·  DAT Tool",
                     font=FH, text_color=TEXT).pack(side="left", padx=20)
        ctk.CTkLabel(bar, text="Wii  ·  zs2jp.dat  ·  Unpack & Repack",
                     font=FN, text_color=DIM).pack(side="left", padx=6)

        # Tabs
        tabs = ctk.CTkTabview(
            self, fg_color=BG,
            segmented_button_fg_color=PANEL,
            segmented_button_selected_color=BLUE,
            segmented_button_selected_hover_color=ACCT,
            text_color=TEXT, border_width=0,
        )
        tabs.pack(fill="both", expand=True, padx=16, pady=(10, 6))
        tabs.add("📦  Unpack")
        tabs.add("🔧  Repack")
        

        self._tab_unpack(tabs.tab("📦  Unpack"))
        self._tab_repack(tabs.tab("🔧  Repack"))


        
        bot = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=14)
        bot.pack(fill="x", padx=16, pady=(0, 14))

        self._pbar = ctk.CTkProgressBar(bot, variable=self._prog,
                                        progress_color=ACCT, height=8, corner_radius=4)
        self._pbar.pack(fill="x", padx=14, pady=(12, 6))

        self._log = ctk.CTkTextbox(bot, height=140, fg_color="#0a0a14",
                                   text_color=TEXT, font=FM, border_width=0)
        self._log.pack(fill="x", padx=14, pady=(0, 12))
        self._log.configure(state="disabled")

    def _card(self, parent):
        f = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=10)
        f.pack(fill="x", padx=2, pady=6)
        return f

    def _row(self, parent, label, var, btn_text, cmd):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=5)
        ctk.CTkLabel(row, text=label, width=150, anchor="w",
                     font=FB, text_color=TEXT).pack(side="left")
        ctk.CTkEntry(row, textvariable=var, font=FM,
                     fg_color="#0a0a14", text_color=TEXT,
                     border_color=BLUE, border_width=1,
                     height=34).pack(side="left", fill="x", expand=True, padx=6)
        ctk.CTkButton(row, text=btn_text, width=90,
                      fg_color=BLUE, hover_color=ACCT,
                      font=FB, height=34,
                      command=cmd).pack(side="left")

    

    def _tab_unpack(self, tab):
        tab.configure(fg_color=BG)
        ctk.CTkLabel(tab, text="Extrae todos los archivos del zs2jp.dat.",
                     font=FN, text_color=DIM).pack(anchor="w", padx=4, pady=(8, 2))

        c = self._card(tab)
        self._row(c, "Archivo .dat:", self._dat, "Buscar…",
                  lambda: self._pick_file(self._dat, [("DAT files", "*.dat"), ("All", "*.*")]))
        self._row(c, "Carpeta salida:", self._uout, "Buscar…",
                  lambda: self._pick_dir(self._uout))

        opts = ctk.CTkFrame(c, fg_color="transparent")
        opts.pack(fill="x", padx=12, pady=(2, 10))
        ctk.CTkCheckBox(opts, text="Omitir entradas vacías / null",
                        variable=self._skip, font=FN, text_color=DIM,
                        fg_color=BLUE, hover_color=ACCT,
                        border_color=BLUE).pack(side="left")

        ctk.CTkButton(tab, text="▶   Unpack",
                      font=FH, fg_color=ACCT, hover_color="#c0334e",
                      height=52, corner_radius=10,
                      command=self._do_unpack).pack(pady=14, padx=2, fill="x")

    

    def _tab_repack(self, tab):
        tab.configure(fg_color=BG)
        ctk.CTkLabel(tab, text="Reempaqueta una carpeta de archivos modificados en un .dat",
                     font=FN, text_color=DIM).pack(anchor="w", padx=4, pady=(8, 2))

        c = self._card(tab)
        self._row(c, "Carpeta fuente:", self._src, "Buscar…",
                  lambda: self._pick_dir(self._src))
        self._row(c, "Salida .dat:", self._rout, "Buscar…",
                  lambda: self._save_file(self._rout, [("DAT files", "*.dat"), ("All", "*.*")]))

        srow = ctk.CTkFrame(c, fg_color="transparent")
        srow.pack(fill="x", padx=12, pady=(2, 10))
        ctk.CTkLabel(srow, text="Slots totales:", width=150, anchor="w",
                     font=FB, text_color=TEXT).pack(side="left")
        ctk.CTkEntry(srow, textvariable=self._slots, width=100,
                     fg_color="#0a0a14", text_color=TEXT,
                     border_color=BLUE, border_width=1, height=34,
                     font=FM).pack(side="left", padx=6)
        ctk.CTkLabel(srow, text="← 45660 para mantener el original",
                     font=FN, text_color=DIM).pack(side="left")

        ctk.CTkButton(tab, text="▶   Repack",
                      font=FH, fg_color=BLUE, hover_color=ACCT,
                      height=52, corner_radius=10,
                      command=self._do_repack).pack(pady=14, padx=2, fill="x")

    

  

    

    def _pick_file(self, var, ft):
        p = filedialog.askopenfilename(filetypes=ft)
        if p: var.set(p)

    def _pick_dir(self, var):
        p = filedialog.askdirectory()
        if p: var.set(p)

    def _save_file(self, var, ft):
        p = filedialog.asksaveasfilename(filetypes=ft, defaultextension=".dat")
        if p: var.set(p)

    

    def _log_write(self, msg):
        self._log.configure(state="normal")
        self._log.insert("end", msg + "\n")
        self._log.see("end")
        self._log.configure(state="disabled")

    def _log_clear(self):
        self._log.configure(state="normal")
        self._log.delete("1.0", "end")
        self._log.configure(state="disabled")

    

    def _do_unpack(self):
        dat = self._dat.get().strip()
        out = self._uout.get().strip()
        if not dat or not os.path.isfile(dat):
            messagebox.showerror("Error", "Seleccioná un archivo .dat válido")
            return
        if not out:
            messagebox.showerror("Error", "Seleccioná una carpeta de salida")
            return
        self._log_clear()
        self._prog.set(0)
        threading.Thread(target=self._unpack_worker,
                         args=(dat, out, self._skip.get()), daemon=True).start()

    def _unpack_worker(self, dat, out, skip):
        try:
            ex, sk, oor = unpack(dat, out, skip_empty=skip,
                                 progress_cb=lambda v: self._prog.set(v),
                                 log_cb=self._log_write)
            self._log_write(f"\n✅  Listo — {ex:,} archivos extraídos")
            messagebox.showinfo("Unpack completo",
                                f"Extraídos   {ex:,}\nOmitidos    {sk:,} (vacíos)\n"
                                f"Sin rango   {oor:,} (archivo truncado)\n\n→ {out}")
        except Exception as e:
            self._log_write(f"\n❌  {e}")
            messagebox.showerror("Error", str(e))

    

    def _do_repack(self):
        src = self._src.get().strip()
        out = self._rout.get().strip()
        if not src or not os.path.isdir(src):
            messagebox.showerror("Error", "Seleccioná una carpeta fuente válida")
            return
        if not out:
            messagebox.showerror("Error", "Seleccioná la ruta de salida del .dat")
            return
        try:
            slots = int(self._slots.get()) if self._slots.get().strip() else None
        except ValueError:
            messagebox.showerror("Error", "Los slots deben ser un número entero")
            return
        self._log_clear()
        self._prog.set(0)
        threading.Thread(target=self._repack_worker,
                         args=(src, out, slots), daemon=True).start()

    def _repack_worker(self, src, out, slots):
        try:
            n = repack(src, out, num_slots=slots,
                       progress_cb=lambda v: self._prog.set(v),
                       log_cb=self._log_write)
            self._log_write(f"\n✅  Listo — {n:,} archivos empaquetados")
            messagebox.showinfo("Repack completo",
                                f"Empaquetados {n:,} archivos\n\n→ {out}")
        except Exception as e:
            self._log_write(f"\n❌  {e}")
            messagebox.showerror("Error", str(e))




if __name__ == "__main__":
    app = App()
    app.mainloop()
