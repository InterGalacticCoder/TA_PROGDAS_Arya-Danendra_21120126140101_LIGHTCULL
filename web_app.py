import asyncio
import io
import os
import zipfile

from js import Blob, Object, Uint8Array, URL, document
from pyodide.ffi import create_proxy, to_js

from core.analyzer import AutoGrayscaleAnalyzer, ManualEVAnalyzer
from models.data_structures import PhotoQueue, UndoStack
from models.photo_item import PhotoItem


class LightCullWebApp:
    """Controller Web Client-Side untuk LightCull (Shared Core dengan versi Desktop)."""

    MODE_EV = "EV (Needs supported Metadata)"
    MODE_GRAYSCALE = "Grayscale"
    VALID_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".bmp")

    STATUS_COLORS = {
        "Normal": "#2ecc71",
        "Underexposed": "#5dade2",
        "Overexposed": "#e67e22",
    }

    def __init__(self):
        self.queue = PhotoQueue()
        self.undo_stack = UndoStack()
        self.analyzer = ManualEVAnalyzer()

        self.pending_photos: list[PhotoItem] = []
        self.file_store: dict[int, dict] = {}
        self.sorted_results: dict[str, list[PhotoItem]] = {
            "Normal": [],
            "Underexposed": [],
            "Overexposed": [],
        }
        self.stats = {
            "Total": 0,
            "Normal": 0,
            "Underexposed": 0,
            "Overexposed": 0,
        }

        self.is_processing = False
        self._proxies = []  # Menjaga referensi callback JS agar tidak terkena GC

        self._bind_elements()
        self._bind_events()
        self._on_mode_change()
        self._mark_ready()

    def _bind_elements(self):
        self.status_badge = document.getElementById("status-badge")
        self.folder_display = document.getElementById("folder-display")
        self.folder_input = document.getElementById("folder-input")
        self.files_input = document.getElementById("files-input")

        self.btn_folder = document.getElementById("btn-folder")
        self.btn_files = document.getElementById("btn-files")
        self.mode_select = document.getElementById("mode-select")
        self.mode_note = document.getElementById("mode-note")

        self.ev_controls = document.getElementById("ev-controls")
        self.min_ev_label = document.getElementById("min-ev-label")
        self.min_ev_slider = document.getElementById("min-ev-slider")
        self.max_ev_label = document.getElementById("max-ev-label")
        self.max_ev_slider = document.getElementById("max-ev-slider")

        self.btn_start = document.getElementById("btn-start")
        self.btn_undo = document.getElementById("btn-undo")
        self.btn_undo_all = document.getElementById("btn-undo-all")
        self.btn_download = document.getElementById("btn-download")

        self.preview_img = document.getElementById("preview-img")
        self.preview_placeholder = document.getElementById("preview-placeholder")
        self.file_info = document.getElementById("file-info")
        self.result_info = document.getElementById("result-info")
        self.progress_fill = document.getElementById("progress-fill")
        self.queue_info = document.getElementById("queue-info")
        self.summary_text = document.getElementById("summary-text")
        self.log_box = document.getElementById("log-box")

    def _add_listener(self, element, event_name: str, handler):
        proxy = create_proxy(handler)
        self._proxies.append(proxy)
        element.addEventListener(event_name, proxy)

    def _bind_events(self):
        self._add_listener(self.btn_folder, "click", lambda _e: self.folder_input.click())
        self._add_listener(self.btn_files, "click", lambda _e: self.files_input.click())
        self._add_listener(self.folder_input, "change", self._on_files_selected)
        self._add_listener(self.files_input, "change", self._on_files_selected)

        self._add_listener(self.mode_select, "change", lambda _e: self._on_mode_change())
        self._add_listener(self.min_ev_slider, "input", lambda _e: self._on_slider_change())
        self._add_listener(self.max_ev_slider, "input", lambda _e: self._on_slider_change())

        self._add_listener(self.btn_start, "click", self._on_start_click)
        self._add_listener(self.btn_undo, "click", lambda _e: self._undo_last())
        self._add_listener(self.btn_undo_all, "click", lambda _e: self._undo_all())
        self._add_listener(self.btn_download, "click", lambda _e: self._download_zip())

    def _mark_ready(self):
        self.status_badge.textContent = "Siap — 100% Lokal di Browser"
        self.status_badge.classList.add("ready")
        self._update_controls()
        self._log("[INFO] Engine Python & Pillow siap. Foto diproses lokal tanpa upload server.")

    # --- PENGATURAN MODE & SLIDER ---
    def _on_mode_change(self):
        if self.mode_select.value == self.MODE_EV:
            self.mode_note.textContent = (
                "Membaca metadata Exposure Bias (EXIF). Jika foto tidak memiliki "
                "metadata EV, otomatis beralih ke metode Grayscale."
            )
        else:
            self.mode_note.textContent = (
                "Mode otomatis menggunakan konversi Grayscale dengan parameter "
                "bawaan (slider dinonaktifkan)."
            )
        self._update_controls()

    def _on_slider_change(self):
        min_ev = float(self.min_ev_slider.value)
        max_ev = float(self.max_ev_slider.value)
        self.min_ev_label.textContent = f"Batas Gelap (Under): {min_ev:+.1f} EV"
        self.max_ev_label.textContent = f"Batas Terang (Over): {max_ev:+.1f} EV"

    def _create_selected_analyzer(self):
        if self.mode_select.value == self.MODE_EV:
            return ManualEVAnalyzer(
                min_ev=float(self.min_ev_slider.value),
                max_ev=float(self.max_ev_slider.value),
            )
        return AutoGrayscaleAnalyzer()

    # --- MEMUAT FILE KE QUEUE ---
    def _reset_session(self):
        for meta in self.file_store.values():
            if meta.get("url"):
                URL.revokeObjectURL(meta["url"])

        self.file_store.clear()
        self.pending_photos.clear()
        self.queue.clear()
        self.undo_stack.clear()
        self.sorted_results = {"Normal": [], "Underexposed": [], "Overexposed": []}
        self.stats = {"Total": 0, "Normal": 0, "Underexposed": 0, "Overexposed": 0}
        self.progress_fill.style.width = "0%"

    def _on_files_selected(self, event):
        js_files = event.target.files
        if not js_files or js_files.length == 0:
            return

        self._reset_session()

        raw_list = [js_files.item(i) for i in range(js_files.length)]
        raw_list.sort(key=lambda f: f.name.lower())

        for js_file in raw_list:
            if js_file.name.lower().endswith(self.VALID_EXTENSIONS):
                photo = PhotoItem(js_file.name)
                self.file_store[id(photo)] = {
                    "js_file": js_file,
                    "bytes": None,
                    "url": URL.createObjectURL(js_file),
                }
                self.pending_photos.append(photo)
                self.queue.enqueue(photo)

        # Reset nilai input agar folder yang sama bisa dipilih ulang
        event.target.value = ""

        count = self.queue.size()
        self.folder_display.value = f"{count} foto valid dipilih (siap diantrekan)"
        self._refresh_stats()
        self._update_controls()
        self._log(f"[INFO] {count} foto valid berhasil dimuat ke Queue.")

    # --- PROSES CULLING (QUEUE FIFO) ---
    def _on_start_click(self, _event):
        if self.is_processing:
            return
        asyncio.ensure_future(self._run_culling())

    async def _run_culling(self):
        if self.queue.is_empty() and self.pending_photos:
            for photo in self.pending_photos:
                self.queue.enqueue(photo)

        batch_total = self.queue.size()
        if batch_total == 0:
            self._log("[INFO] Tidak ada foto tersisa di antrean untuk dipindai.")
            return

        self.analyzer = self._create_selected_analyzer()
        self.is_processing = True
        self.progress_fill.style.width = "0%"
        self._update_controls()
        self._log(
            f"[START] Memulai culling {batch_total} foto dengan mode '{self.mode_select.value}'..."
        )

        processed = 0
        while not self.queue.is_empty():
            photo: PhotoItem = self.queue.dequeue()
            if photo in self.pending_photos:
                self.pending_photos.remove(photo)

            meta = self.file_store[id(photo)]
            try:
                # Baca bytes dari File lokal di browser (tanpa server)
                if meta["bytes"] is None:
                    array_buf = await meta["js_file"].arrayBuffer()
                    meta["bytes"] = Uint8Array.new(array_buf).to_bytes()

                score, status, detail = self.analyzer.analyze(meta["bytes"])
                photo.set_analysis_result(score, status, detail)

                self.sorted_results[status].append(photo)
                self.undo_stack.push({"photo": photo, "status": status})

                self.stats["Total"] += 1
                self.stats[status] += 1

                self._show_preview(meta["url"])
                self.file_info.textContent = f"File: {photo.get_filename()}"
                self.result_info.textContent = f"Status: {status} | {detail}"
                self.result_info.style.color = self.STATUS_COLORS.get(status, "#f0f0f0")
                self._log(f"[QUEUE] {photo.get_filename()} -> /{status} ({detail})")
            except Exception as err:
                self._log(f"[ERROR] Gagal memproses {photo.get_filename()}: {err}")

            processed += 1
            pct = (processed / batch_total) * 100
            self.progress_fill.style.width = f"{pct:.1f}%"
            self._refresh_stats()

            # Beri jeda singkat agar browser me-render preview & progress bar
            await asyncio.sleep(0.02)

        self.is_processing = False
        self._update_controls()
        self._log("[SELESAI] Seluruh antrean Queue selesai diproses. Siap diunduh sebagai ZIP.")

    # --- UNDO (STACK LIFO) ---
    def _undo_one(self):
        if self.undo_stack.is_empty():
            return None

        record = self.undo_stack.pop()
        photo = record["photo"]
        status = record["status"]

        if photo in self.sorted_results[status]:
            self.sorted_results[status].remove(photo)
        self.pending_photos.append(photo)

        self.stats["Total"] = max(0, self.stats["Total"] - 1)
        self.stats[status] = max(0, self.stats[status] - 1)
        return record

    def _undo_last(self):
        record = self._undo_one()
        if record:
            photo = record["photo"]
            meta = self.file_store[id(photo)]
            self._show_preview(meta["url"])
            self.file_info.textContent = f"File: {photo.get_filename()}"
            self.result_info.textContent = "Status: Dikembalikan ke antrean asal (Undo)"
            self.result_info.style.color = "#cccccc"
            self._log(f"[STACK] UNDO: {photo.get_filename()} dikembalikan.")

        self._refresh_stats()
        self._update_controls()

    def _undo_all(self):
        count = 0
        while not self.undo_stack.is_empty():
            if self._undo_one() is not None:
                count += 1

        if count > 0:
            self.progress_fill.style.width = "0%"
            self._log(f"[STACK] UNDO ALL: {count} foto berhasil dikembalikan.")

        self._refresh_stats()
        self._update_controls()

    # --- EKSPOR HASIL KE ZIP (CLIENT-SIDE) ---
    def _download_zip(self):
        if self.stats["Total"] == 0:
            return

        self._log("[ZIP] Mengemas hasil culling ke dalam LightCull_Hasil.zip...")
        zip_buffer = io.BytesIO()
        used_paths = set()

        with zipfile.ZipFile(zip_buffer, "w", compression=zipfile.ZIP_STORED) as zf:
            for category, photos in self.sorted_results.items():
                for photo in photos:
                    img_bytes = self.file_store[id(photo)]["bytes"]
                    if img_bytes is None:
                        continue

                    filename = photo.get_filename()
                    base, ext = os.path.splitext(filename)
                    arcname = f"{category}/{filename}"
                    counter = 1
                    while arcname in used_paths:
                        arcname = f"{category}/{base}_{counter}{ext}"
                        counter += 1

                    used_paths.add(arcname)
                    zf.writestr(arcname, img_bytes)

        zip_bytes = zip_buffer.getvalue()
        blob_parts = to_js([zip_bytes])
        blob_opts = to_js({"type": "application/zip"}, dict_converter=Object.fromEntries)
        blob = Blob.new(blob_parts, blob_opts)
        download_url = URL.createObjectURL(blob)

        link = document.createElement("a")
        link.href = download_url
        link.download = "LightCull_Hasil.zip"
        document.body.appendChild(link)
        link.click()
        document.body.removeChild(link)
        URL.revokeObjectURL(download_url)

        self._log(f"[ZIP] Selesai! {self.stats['Total']} foto berhasil diunduh.")

    # --- HELPER UI ---
    def _show_preview(self, object_url: str):
        self.preview_placeholder.style.display = "none"
        self.preview_img.src = object_url
        self.preview_img.style.display = "block"

    def _refresh_stats(self):
        self.summary_text.textContent = (
            f"RINGKASAN: Total: {self.stats['Total']} | "
            f"Normal: {self.stats['Normal']} | "
            f"Underexposed: {self.stats['Underexposed']} | "
            f"Overexposed: {self.stats['Overexposed']}"
        )
        pending_count = self.queue.size() if not self.queue.is_empty() else len(self.pending_photos)
        self.queue_info.textContent = (
            f"Sisa di Queue: {pending_count} foto | "
            f"Riwayat Undo (Stack): {self.undo_stack.size()}"
        )

    def _update_controls(self):
        is_ev_mode = self.mode_select.value == self.MODE_EV
        can_edit_sliders = is_ev_mode and not self.is_processing
        has_work = (not self.queue.is_empty()) or (len(self.pending_photos) > 0)
        has_undo = not self.undo_stack.is_empty()

        self.btn_folder.disabled = self.is_processing
        self.btn_files.disabled = self.is_processing
        self.mode_select.disabled = self.is_processing

        self.min_ev_slider.disabled = not can_edit_sliders
        self.max_ev_slider.disabled = not can_edit_sliders
        for group in self.ev_controls.querySelectorAll(".slider-group"):
            if is_ev_mode:
                group.classList.remove("disabled")
            else:
                group.classList.add("disabled")

        self.btn_start.disabled = self.is_processing or not has_work
        self.btn_undo.disabled = self.is_processing or not has_undo
        self.btn_undo_all.disabled = self.is_processing or not has_undo
        self.btn_download.disabled = self.is_processing or (self.stats["Total"] == 0)

    def _log(self, message: str):
        self.log_box.textContent += message + "\n"
        self.log_box.scrollTop = self.log_box.scrollHeight


app = LightCullWebApp()