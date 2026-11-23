import customtkinter as ctk
from tkinter import filedialog, messagebox
from PIL import Image, ImageOps
from core.analyzer import ManualEVAnalyzer, AutoGrayscaleAnalyzer
from core.culling_manager import CullingManager

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class LightCullApp(ctk.CTk):
    """Antarmuka grafis utama aplikasi LightCull."""

    MODE_EV = "EV (Needs supported Metadata)"
    MODE_GRAYSCALE = "Grayscale"

    STATUS_COLORS = {
        "Normal": "#2ecc71",
        "Underexposed": "#5dade2",
        "Overexposed": "#e67e22",
    }

    def __init__(self):
        super().__init__()
        self.title("LightCull — Auto-Culling Foto Exposure")
        self.geometry("960x790")
        self.minsize(880, 640)

        self.manager = CullingManager()
        self.is_processing = False
        self.batch_total = 0
        self.batch_processed = 0
        self.current_preview_image = None

        self._build_ui()
        self._on_mode_change(self.MODE_EV)
        self._update_controls()

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # --- HEADER ---
        header_frame = ctk.CTkFrame(self, corner_radius=10)
        header_frame.grid(row=0, column=0, padx=16, pady=(14, 8), sticky="ew")
        header_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            header_frame,
            text="LightCull",
            font=ctk.CTkFont(size=22, weight="bold"),
        ).grid(row=0, column=0, padx=16, pady=10, sticky="w")

        ctk.CTkLabel(
            header_frame,
            text="Auto-Culling Foto Underexposed & Overexposed",
            text_color="gray75",
        ).grid(row=0, column=1, padx=8, pady=10, sticky="w")

        # --- BAR PILIH FOLDER ---
        folder_frame = ctk.CTkFrame(self, corner_radius=10)
        folder_frame.grid(row=1, column=0, padx=16, pady=6, sticky="ew")
        folder_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(folder_frame, text="Folder Sumber:").grid(
            row=0, column=0, padx=(14, 8), pady=10
        )
        self.folder_entry = ctk.CTkEntry(
            folder_frame, placeholder_text="Pilih folder berisi foto yang ingin disortir..."
        )
        self.folder_entry.configure(state="readonly")
        self.folder_entry.grid(row=0, column=1, padx=6, pady=10, sticky="ew")

        self.btn_browse = ctk.CTkButton(
            folder_frame, text="Pilih Folder", width=120, command=self._choose_folder
        )
        self.btn_browse.grid(row=0, column=2, padx=(6, 14), pady=10)

        # --- AREA TENGAH (2 KOLOM) ---
        main_frame = ctk.CTkFrame(self, fg_color="transparent")
        main_frame.grid(row=2, column=0, padx=16, pady=6, sticky="nsew")
        main_frame.grid_columnconfigure(0, weight=4)
        main_frame.grid_columnconfigure(1, weight=6)
        main_frame.grid_rowconfigure(0, weight=1)

        # Kolom Kiri: Pengaturan & Kontrol
        left_panel = ctk.CTkFrame(main_frame, corner_radius=10)
        left_panel.grid(row=0, column=0, padx=(0, 8), sticky="nsew")
        left_panel.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            left_panel,
            text="PENGATURAN ANALISIS",
            font=ctk.CTkFont(size=14, weight="bold"),
        ).grid(row=0, column=0, padx=16, pady=(14, 8), sticky="w")

        ctk.CTkLabel(left_panel, text="Mode Analisis (OOP 2):").grid(
            row=1, column=0, padx=16, pady=(4, 2), sticky="w"
        )
        self.mode_menu = ctk.CTkOptionMenu(
            left_panel,
            values=[self.MODE_EV, self.MODE_GRAYSCALE],
            command=self._on_mode_change,
        )
        self.mode_menu.set(self.MODE_EV)
        self.mode_menu.grid(row=2, column=0, padx=16, pady=(0, 6), sticky="ew")

        self.mode_note_label = ctk.CTkLabel(
            left_panel,
            text="",
            justify="left",
            wraplength=290,
            font=ctk.CTkFont(size=11),
            text_color="gray75",
        )
        self.mode_note_label.grid(row=3, column=0, padx=16, pady=(0, 10), sticky="w")

        # Parameter Slider EV (hanya aktif di mode EV)
        self.min_ev_label = ctk.CTkLabel(left_panel, text="Batas Gelap (Under): -2.0 EV")
        self.min_ev_label.grid(row=4, column=0, padx=16, pady=(4, 0), sticky="w")
        self.min_ev_slider = ctk.CTkSlider(
            left_panel,
            from_=-5.0,
            to=-0.5,
            number_of_steps=45,  # Kelipatan 0.1 EV
            command=self._on_slider_change,
        )
        self.min_ev_slider.set(-2.0)
        self.min_ev_slider.grid(row=5, column=0, padx=16, pady=(4, 12), sticky="ew")

        self.max_ev_label = ctk.CTkLabel(left_panel, text="Batas Terang (Over): +2.0 EV")
        self.max_ev_label.grid(row=6, column=0, padx=16, pady=(4, 0), sticky="w")
        self.max_ev_slider = ctk.CTkSlider(
            left_panel,
            from_=0.5,
            to=5.0,
            number_of_steps=45,  # Kelipatan 0.1 EV
            command=self._on_slider_change,
        )
        self.max_ev_slider.set(2.0)
        self.max_ev_slider.grid(row=7, column=0, padx=16, pady=(4, 18), sticky="ew")

        self.btn_start = ctk.CTkButton(
            left_panel,
            text="Mulai Culling (Queue)",
            height=40,
            font=ctk.CTkFont(weight="bold"),
            command=self._start_culling,
        )
        self.btn_start.grid(row=8, column=0, padx=16, pady=6, sticky="ew")

        self.btn_undo = ctk.CTkButton(
            left_panel,
            text="Undo Terakhir (Stack)",
            fg_color="#34495e",
            hover_color="#2c3e50",
            command=self._undo_last,
        )
        self.btn_undo.grid(row=9, column=0, padx=16, pady=6, sticky="ew")

        self.btn_undo_all = ctk.CTkButton(
            left_panel,
            text="Kembalikan Semua",
            fg_color="#7f8c8d",
            hover_color="#636e72",
            command=self._undo_all,
        )
        self.btn_undo_all.grid(row=10, column=0, padx=16, pady=(6, 16), sticky="ew")

        # Kolom Kanan: Preview & Status Queue
        right_panel = ctk.CTkFrame(main_frame, corner_radius=10)
        right_panel.grid(row=0, column=1, padx=(8, 0), sticky="nsew")
        right_panel.grid_columnconfigure(0, weight=1)
        right_panel.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            right_panel,
            text="PREVIEW & PROSES ANTREAN",
            font=ctk.CTkFont(size=14, weight="bold"),
        ).grid(row=0, column=0, padx=16, pady=(14, 6), sticky="w")

        self.preview_box = ctk.CTkLabel(
            right_panel,
            text="Belum ada foto diproses",
            width=360,
            height=220,
            fg_color="gray16",
            corner_radius=8,
        )
        self.preview_box.grid(row=1, column=0, padx=16, pady=6, sticky="nsew")

        info_frame = ctk.CTkFrame(right_panel, fg_color="transparent")
        info_frame.grid(row=2, column=0, padx=16, pady=6, sticky="ew")
        info_frame.grid_columnconfigure(0, weight=1)

        self.file_info_label = ctk.CTkLabel(
            info_frame, text="File: -", anchor="w", font=ctk.CTkFont(weight="bold")
        )
        self.file_info_label.grid(row=0, column=0, sticky="w")

        self.result_info_label = ctk.CTkLabel(
            info_frame, text="Status: -  |  Detail: -", anchor="w"
        )
        self.result_info_label.grid(row=1, column=0, sticky="w")

        self.progress_bar = ctk.CTkProgressBar(right_panel)
        self.progress_bar.set(0)
        self.progress_bar.grid(row=3, column=0, padx=16, pady=(6, 4), sticky="ew")

        self.queue_info_label = ctk.CTkLabel(
            right_panel, text="Sisa di Queue: 0 foto  |  Riwayat Undo (Stack): 0"
        )
        self.queue_info_label.grid(row=4, column=0, padx=16, pady=(0, 12), sticky="w")

        # --- PANEL BAWAH: RINGKASAN & LOG ---
        bottom_panel = ctk.CTkFrame(self, corner_radius=10)
        bottom_panel.grid(row=3, column=0, padx=16, pady=(6, 14), sticky="ew")
        bottom_panel.grid_columnconfigure(0, weight=1)

        self.summary_label = ctk.CTkLabel(
            bottom_panel,
            text="RINGKASAN:  Total: 0  |  Normal: 0  |  Underexposed: 0  |  Overexposed: 0",
            font=ctk.CTkFont(size=13, weight="bold"),
        )
        self.summary_label.grid(row=0, column=0, padx=14, pady=(10, 4), sticky="w")

        self.log_box = ctk.CTkTextbox(bottom_panel, height=110)
        self.log_box.configure(state="disabled")
        self.log_box.grid(row=1, column=0, padx=14, pady=(2, 12), sticky="ew")

    # --- EVENT HANDLERS ---
    def _on_mode_change(self, selected_mode: str):
        if selected_mode == self.MODE_EV:
            self.mode_note_label.configure(
                text=(
                    "Membaca metadata Exposure Bias (EXIF). Jika foto tidak memiliki "
                    "metadata EV, otomatis beralih ke metode Grayscale."
                )
            )
        else:
            self.mode_note_label.configure(
                text=(
                    "Mode otomatis menggunakan konversi Grayscale dengan parameter "
                    "bawaan (slider dinonaktifkan)."
                )
            )
        self._update_slider_states()

    def _on_slider_change(self, _value):
        min_ev = round(self.min_ev_slider.get(), 1)
        max_ev = round(self.max_ev_slider.get(), 1)
        self.min_ev_label.configure(text=f"Batas Gelap (Under): {min_ev:+.1f} EV")
        self.max_ev_label.configure(text=f"Batas Terang (Over): {max_ev:+.1f} EV")

    def _update_slider_states(self):
        is_ev_mode = self.mode_menu.get() == self.MODE_EV
        can_edit = is_ev_mode and not self.is_processing

        slider_state = "normal" if can_edit else "disabled"
        label_color = "white" if is_ev_mode else "gray45"
        button_color = "#1f6aa5" if can_edit else "gray35"
        progress_color = "#aab0b5" if can_edit else "gray30"

        for slider in (self.min_ev_slider, self.max_ev_slider):
            slider.configure(
                state=slider_state,
                button_color=button_color,
                progress_color=progress_color,
            )

        self.min_ev_label.configure(text_color=label_color)
        self.max_ev_label.configure(text_color=label_color)

    def _choose_folder(self):
        folder = filedialog.askdirectory(title="Pilih Folder Foto")
        if not folder:
            return

        self.manager.set_source_folder(folder)
        self.folder_entry.configure(state="normal")
        self.folder_entry.delete(0, "end")
        self.folder_entry.insert(0, folder)
        self.folder_entry.configure(state="readonly")

        queued = self.manager.load_folder_to_queue()
        self.progress_bar.set(0)
        self._refresh_stats()
        self._log(f"[INFO] Folder dipilih: {folder} ({queued} foto ditemukan).")
        self._update_controls()

    def _create_selected_analyzer(self):
        if self.mode_menu.get() == self.MODE_EV:
            min_ev = round(self.min_ev_slider.get(), 1)
            max_ev = round(self.max_ev_slider.get(), 1)
            return ManualEVAnalyzer(min_ev=min_ev, max_ev=max_ev)
        return AutoGrayscaleAnalyzer()

    def _start_culling(self):
        if not self.manager.get_source_folder():
            messagebox.showwarning("Peringatan", "Pilih folder sumber terlebih dahulu.")
            return

        queued = self.manager.load_folder_to_queue()
        if queued == 0:
            messagebox.showinfo(
                "Info", "Tidak ada foto tersisa di folder sumber untuk dipindai."
            )
            return

        analyzer = self._create_selected_analyzer()
        self.manager.set_analyzer(analyzer)

        self.is_processing = True
        self.batch_total = queued
        self.batch_processed = 0
        self.progress_bar.set(0)
        self._update_controls()
        self._log(
            f"[START] Memulai culling {queued} foto dengan mode '{self.mode_menu.get()}'..."
        )
        self.after(20, self._process_next_in_queue)

    def _process_next_in_queue(self):
        if self.manager.is_queue_empty():
            self.is_processing = False
            self._update_controls()
            self._refresh_stats()
            self._log("[SELESAI] Seluruh antrean Queue selesai diproses.")
            return

        photo, error = self.manager.process_next()
        self.batch_processed += 1
        self.progress_bar.set(self.batch_processed / max(1, self.batch_total))

        if error:
            name = photo.get_filename() if photo else "Unknown"
            self._log(f"[ERROR] Gagal memproses {name}: {error}")
        elif photo:
            self._show_preview(photo.get_current_path())
            status = photo.get_status()
            color = self.STATUS_COLORS.get(status, "white")
            self.file_info_label.configure(text=f"File: {photo.get_filename()}")
            self.result_info_label.configure(
                text=f"Status: {status}  |  {photo.get_detail()}",
                text_color=color,
            )
            self._log(
                f"[QUEUE] {photo.get_filename()} -> /{status} ({photo.get_detail()})"
            )

        self._refresh_stats()
        self.after(25, self._process_next_in_queue)

    def _undo_last(self):
        record = self.manager.undo_last()
        if record:
            photo = record["photo"]
            self._show_preview(photo.get_current_path())
            self.file_info_label.configure(text=f"File: {photo.get_filename()}")
            self.result_info_label.configure(
                text="Status: Dikembalikan ke folder asal (Undo)",
                text_color="gray80",
            )
            self._log(f"[STACK] UNDO: {photo.get_filename()} dikembalikan ke folder asal.")
        self._refresh_stats()
        self._update_controls()

    def _undo_all(self):
        count = self.manager.undo_all()
        if count > 0:
            self._log(f"[STACK] UNDO ALL: {count} foto berhasil dikembalikan ke folder asal.")
            self.progress_bar.set(0)
        self._refresh_stats()
        self._update_controls()

    # --- HELPER UI ---
    def _show_preview(self, image_path: str):
        try:
            with Image.open(image_path) as raw_img:
                fixed_img = ImageOps.exif_transpose(raw_img)
                contained = ImageOps.contain(fixed_img, (360, 210))
                self.current_preview_image = ctk.CTkImage(
                    light_image=contained,
                    dark_image=contained,
                    size=contained.size,
                )
            self.preview_box.configure(image=self.current_preview_image, text="")
        except Exception:
            self.preview_box.configure(image=None, text="Preview tidak tersedia")

    def _refresh_stats(self):
        stats = self.manager.get_stats()
        self.summary_label.configure(
            text=(
                f"RINGKASAN:  Total: {stats['Total']}  |  Normal: {stats['Normal']}  |  "
                f"Underexposed: {stats['Underexposed']}  |  Overexposed: {stats['Overexposed']}"
            )
        )
        self.queue_info_label.configure(
            text=(
                f"Sisa di Queue: {self.manager.get_queue_size()} foto  |  "
                f"Riwayat Undo (Stack): {self.manager.get_undo_size()}"
            )
        )

    def _update_controls(self):
        has_folder = bool(self.manager.get_source_folder())
        has_undo = not self.manager.is_undo_empty()

        self.btn_browse.configure(state="disabled" if self.is_processing else "normal")
        self.mode_menu.configure(state="disabled" if self.is_processing else "normal")
        self._update_slider_states()
        self.btn_start.configure(
            state="normal" if (has_folder and not self.is_processing) else "disabled"
        )
        self.btn_undo.configure(
            state="normal" if (has_undo and not self.is_processing) else "disabled"
        )
        self.btn_undo_all.configure(
            state="normal" if (has_undo and not self.is_processing) else "disabled"
        )

    def _log(self, message: str):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", message + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")