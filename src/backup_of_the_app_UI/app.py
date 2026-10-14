"""Visible-record extraction checkpoint.

This version intentionally stops after recognition. It does not fill fields,
submit QR codes, compare values, or continue to another record.
"""

from __future__ import annotations

import io
import os
import re
import threading
import time
import tkinter as tk

from tkinter import messagebox
from typing import Any

from PIL import Image, ImageOps

# PaddleOCR is the primary recognition engine. Import lazily/optionally so the
# existing Tesseract fallback remains available if PaddleOCR is not installed.
try:
    from paddleocr import PaddleOCR
except ImportError:
    PaddleOCR = None

_PADDLE_OCR_ENGINE = None
_PADDLE_OCR_INIT_ERROR: Exception | None = None
try:
    import pytesseract
    pytesseract.pytesseract.tesseract_cmd = os.getenv(
        "TESSERACT_CMD", r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    )
except ImportError:
    pytesseract = None
from flask import Flask, jsonify
from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.by import By
from logic import ReferenceRecord, format_record, parse_reference_text


URL = os.getenv("RECORD_TASK_URL", "https://recordtaskdata.online/")
START_TASK_URL = os.getenv("RECORD_TASK_START_URL", f"{URL.rstrip('/')}/start-task")
USERNAME = os.getenv("RECORD_TASK_USERNAME", "mahesh30802@gmail.com")
PASSWORD = os.getenv("RECORD_TASK_PASSWORD", "9606768755")

class ExtractionApp:
    """Browser-hosted recognition panel; no separate desktop UI window."""

    PANEL_ID = "__visible_data_recognition_panel__"

    def __init__(self) -> None:
        # Tk is retained only as a hidden event loop. All visible controls live
        # inside the Selenium-controlled Chrome page.
        self.root = tk.Tk()
        self.root.withdraw()
        self.driver: webdriver.Chrome | None = None
        self.busy = False
        self.panel_ready = False
        self.app_closed = False
        self.status_text = "Starting website…"
        self.method_text = "Method: Waiting"
        self.result_text = "Recognized data will appear here."
        self.root.after(300, self._poll_browser)
        threading.Thread(target=self._start_browser, daemon=True).start()

    def _start_browser(self) -> None:
        try:
            options = webdriver.ChromeOptions()
            options.add_argument("--start-maximized")
            # If the user closes only the in-page panel, leave Chrome open.
            options.add_experimental_option("detach", True)
            self.driver = webdriver.Chrome(options=options)
            self.driver.get(URL)
            time.sleep(2)

            username = self._find_input(("Username", "username", "mail", "email"))
            password = self._find_input(("Password", "password", "mobile", "phone"))
            if username is not None and password is not None:
                if USERNAME and PASSWORD:
                    username.clear()
                    username.send_keys(USERNAME)
                    password.clear()
                    password.send_keys(PASSWORD)
                    self._click_sign_in()
                    time.sleep(3)

            self.driver.get(START_TASK_URL)
            time.sleep(2)
            self.status_text = "Website is ready. Click Read Visible Data."
            self._install_browser_panel()
        except Exception as exc:
            self.status_text = f"Could not open website: {str(exc)[:180]}"
            try:
                self._install_browser_panel()
            except Exception:
                pass

    def _find_input(self, names: tuple[str, ...]) -> Any | None:
        if self.driver is None:
            return None
        for name in names:
            for by, value in (
                (By.NAME, name),
                (By.ID, name),
                (By.XPATH, f"//input[@placeholder='{name}']"),
            ):
                try:
                    element = self.driver.find_element(by, value)
                    if element.is_displayed():
                        return element
                except Exception:
                    continue
        return None

    def _click_sign_in(self) -> None:
        if self.driver is None:
            return
        elements = self.driver.find_elements(
            By.XPATH,
            "//button[contains(normalize-space(.),'Sign In')] | "
            "//input[@type='submit']",
        )
        for element in elements:
            if element.is_displayed() and element.is_enabled():
                element.click()
                return

    def _panel_script(self) -> str:
        # The entire panel is HTML in the page: it minimizes with Chrome,
        # can be dragged freely, and never creates a separate desktop window.
        return r"""
(() => {
  const old = document.getElementById('__visible_data_recognition_panel__');
  if (old) old.remove();
  const panel = document.createElement('section');
  panel.id = '__visible_data_recognition_panel__';
  Object.assign(panel.style, {
    position:'fixed', left:'18px', top:'18px', width:'min(420px, calc(100vw - 36px))',
    maxHeight:'calc(100vh - 36px)', display:'flex', flexDirection:'column',
    overflow:'hidden', resize:'both', zIndex:'2147483647',
    background:'rgba(15,23,42,0.93)', color:'#f8fafc',
    border:'1px solid rgba(148,163,184,.45)', borderRadius:'9px',
    boxShadow:'0 8px 28px rgba(0,0,0,.30)', fontFamily:'Arial,sans-serif',
    fontSize:'14px', boxSizing:'border-box', opacity:'0.98'
  });
  panel.innerHTML = `
    <header id="__vdr_drag__" style="flex:none;cursor:move;touch-action:none;padding:12px 14px;font-size:18px;font-weight:700;text-align:center;border-bottom:1px solid #334155;user-select:none">
      Visible Data Recognition
      <button id="__vdr_close__" title="Close panel (Chrome stays open)" style="float:right;border:0;background:transparent;color:#cbd5e1;font-size:20px;line-height:20px;cursor:pointer">×</button>
    </header>
    <div id="__vdr_method__" style="flex:none;padding:8px 12px;color:#94a3b8;text-align:center;overflow-wrap:anywhere">Method: Waiting</div>
    <div id="__vdr_status__" style="flex:none;padding:5px 12px 10px;color:#38bdf8;text-align:center;overflow-wrap:anywhere">Starting website…</div>
    <div style="display:flex;flex:none;gap:8px;justify-content:center;flex-wrap:wrap;padding:0 10px 12px">
      <button id="__vdr_open__" style="border:0;border-radius:3px;background:#2563eb;color:white;padding:10px 14px;font-weight:700;cursor:pointer">Open Website</button>
      <button id="__vdr_read__" style="border:0;border-radius:3px;background:#16a34a;color:white;padding:10px 14px;font-weight:700;cursor:pointer">Read Visible Data</button>
    </div>
    <pre id="__vdr_result__" style="flex:1;min-height:72px;max-height:55vh;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere;margin:0 12px 12px;padding:12px;background:#1e293b;color:#e2e8f0;border-radius:3px;font:14px/1.35 Arial,sans-serif;box-sizing:border-box">Recognized data will appear here.</pre>`;
  document.documentElement.appendChild(panel);

  const send = action => { window.__vdr_action = action; };
  panel.querySelector('#__vdr_open__').onclick = () => send('open');
  panel.querySelector('#__vdr_read__').onclick = () => send('read');
  panel.querySelector('#__vdr_close__').onclick = () => {
    panel.remove();
    window.__vdr_action = 'close_panel';
  };
  const handle = panel.querySelector('#__vdr_drag__');
  let drag = null;
  handle.addEventListener('pointerdown', e => {
    if (e.target.closest('button')) return;
    const r = panel.getBoundingClientRect();
    drag = {x:e.clientX-r.left, y:e.clientY-r.top};
    handle.setPointerCapture(e.pointerId);
  });
  handle.addEventListener('pointermove', e => {
    if (!drag) return;
    const maxX = Math.max(0, window.innerWidth-panel.offsetWidth);
    const maxY = Math.max(0, window.innerHeight-50);
    panel.style.left = Math.max(0,Math.min(maxX,e.clientX-drag.x))+'px';
    panel.style.top = Math.max(0,Math.min(maxY,e.clientY-drag.y))+'px';
    panel.style.right = 'auto';
  });
  const endDrag = () => { drag = null; };
  handle.addEventListener('pointerup', endDrag);
  handle.addEventListener('pointercancel', endDrag);
})();
"""

    def _install_browser_panel(self) -> None:
        if self.driver is None:
            return
        try:
            self.driver.execute_script(self._panel_script())
            self.panel_ready = True
            self._sync_panel()
        except Exception as exc:
            self.status_text = f"Panel could not be loaded: {str(exc)[:160]}"

    def _sync_panel(self) -> None:
        if self.driver is None or not self.panel_ready:
            return
        script = """
          const p = document.getElementById(arguments[0]);
          if (!p) return false;
          const set = (id, value) => {
            const el = document.getElementById(id);
            if (el) el.textContent = value;
          };
          set('__vdr_status__', arguments[1]);
          set('__vdr_method__', arguments[2]);
          set('__vdr_result__', arguments[3]);
          const busy = arguments[4];
          for (const id of ['__vdr_open__','__vdr_read__']) {
            const b = document.getElementById(id);
            if (b) { b.disabled = busy; b.style.opacity = busy ? '.55' : '1'; }
          }
          return true;
        """
        try:
            exists = self.driver.execute_script(
                script, self.PANEL_ID, self.status_text, self.method_text,
                self.result_text, self.busy
            )
            if not exists:
                self.panel_ready = False
        except Exception:
            # Browser closure is handled by the periodic monitor.
            pass

    def set_status(self, text: str) -> None:
        self.status_text = str(text)[:240]
        self.root.after(0, self._sync_panel)

    def set_method_indicator(self, text: str) -> None:
        self.method_text = str(text)[:180]
        self.root.after(0, self._sync_panel)

    def show_result(self, text: str) -> None:
        self.result_text = str(text)
        self.root.after(0, self._sync_panel)

    def set_busy(self, busy: bool) -> None:
        self.busy = busy
        self.root.after(0, self._sync_panel)

    def open_website(self) -> None:
        if self.busy or self.driver is None:
            return
        self.set_busy(True)
        threading.Thread(target=self._open_website, daemon=True).start()

    def _open_website(self) -> None:
        try:
            if self.driver is None:
                return
            self.driver.get(URL)
            time.sleep(2)
            self.driver.get(START_TASK_URL)
            time.sleep(1)
            self.panel_ready = False
            self._install_browser_panel()
            self.set_status("Website is ready. Click Read Visible Data.")
        except Exception as exc:
            self.set_status(f"Could not open website: {str(exc)[:180]}")
        finally:
            self.set_busy(False)

    def read_visible_data(self) -> None:
        if self.busy:
            return
        if self.driver is None:
            self.set_status("Browser is not available. Restart the app.")
            return
        self.set_busy(True)
        threading.Thread(target=self._read_visible_data, daemon=True).start()

    def _read_visible_data(self) -> None:
        try:
            self.set_status("Looking for the visible record…")
            self.set_method_indicator("Method: PaddleOCR recognition…")
            self.driver._method_indicator_callback = self.set_method_indicator

            # Temporarily hide the in-page panel while taking OCR screenshots.
            # The panel is UI-only and must not cover the record or enter the
            # captured pixels. Restore it even if recognition raises an error.
            panel_was_hidden = False
            try:
                panel_was_hidden = bool(
                    self.driver.execute_script(
                        """
                        const panel = document.getElementById(arguments[0]);
                        if (!panel) return false;
                        panel.style.visibility = 'hidden';
                        return true;
                        """,
                        self.PANEL_ID,
                    )
                )
                record = extract_visible_record(self.driver)
            finally:
                if panel_was_hidden:
                    try:
                        self.driver.execute_script(
                            """
                            const panel = document.getElementById(arguments[0]);
                            if (panel) panel.style.visibility = '';
                            """,
                            self.PANEL_ID,
                        )
                    except WebDriverException:
                        pass
            if record is None:
                self.show_result(
                    "No complete record was recognized.\n\n"
                    "Make sure the seven asterisk-separated values are visible "
                    "in the browser, then try again."
                )
                self.set_status("No complete record found.")
                return
            self.show_result(format_record(record))
            self.set_status("Record recognized. Nothing was entered or submitted.")
        except WebDriverException:
            self.set_status("The browser was closed.")
            self.root.after(0, self._stop_after_browser_close)
        except Exception as exc:
            self.set_status(f"Recognition failed: {str(exc)[:220]}")
        finally:
            self.set_busy(False)

    def _poll_browser(self) -> None:
        if self.app_closed:
            return
        # Selenium commands must not run concurrently with an active OCR or
        # navigation worker; defer browser polling until that operation ends.
        if self.busy:
            self.root.after(350, self._poll_browser)
            return
        if self.driver is not None:
            try:
                handles = self.driver.window_handles
                if not handles:
                    self._stop_after_browser_close()
                    return
                if not self.panel_ready:
                    self._install_browser_panel()
                else:
                    action = self.driver.execute_script(
                        "const a=window.__vdr_action||''; "
                        "window.__vdr_action=''; return a;"
                    )
                    if action == "read":
                        self.read_visible_data()
                    elif action == "open":
                        self.open_website()
                    elif action == "close_panel":
                        # Closing the in-page app closes only the panel. Chrome
                        # remains open, as requested.
                        self.app_closed = True
                        self.root.destroy()
                        return
                    else:
                        self._sync_panel()
            except WebDriverException:
                # Closing the controlled browser terminates this Python app.
                self._stop_after_browser_close()
                return
        self.root.after(350, self._poll_browser)

    def _stop_after_browser_close(self) -> None:
        if self.app_closed:
            return
        self.app_closed = True
        # Chrome is already closed; stop the program without creating another
        # desktop window or leaving a background polling loop.
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def close(self) -> None:
        # No visible Tk window exists; this is a defensive shutdown handler.
        self.app_closed = True
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def run(self) -> None:
        self.root.mainloop()


def _paddleocr_candidates(driver: webdriver.Chrome) -> list[str]:
    """Recognize the visible record's pixels with PaddleOCR.

    DOM text is used only to locate the record's rectangle; the returned text
    always comes from OCR on the screenshot pixels. The Tesseract fallback is
    kept separate and unchanged.
    """
    global _PADDLE_OCR_ENGINE, _PADDLE_OCR_INIT_ERROR

    if PaddleOCR is None:
        _update_method_indicator(
            driver, "PaddleOCR unavailable; using existing Tesseract fallback…"
        )
        return []

    if _PADDLE_OCR_ENGINE is None and _PADDLE_OCR_INIT_ERROR is None:
        init_started = time.perf_counter()
        try:
            # Use the lighter English mobile models for CPU inference.
            # This changes only PaddleOCR model selection; the OCR result
            # handling and existing Tesseract fallback remain unchanged.
            try:
                _PADDLE_OCR_ENGINE = PaddleOCR(
                    lang="en",
                    text_detection_model_name="PP-OCRv5_mobile_det",
                    text_recognition_model_name="en_PP-OCRv5_mobile_rec",
                    use_textline_orientation=False,
                    # Reduce detection input size to speed up CPU inference.
                    # More aggressive CPU speed setting; validate small-text accuracy carefully.
                    text_det_limit_side_len=480,
                    text_det_limit_type="max",
                    cpu_threads=4,
                    enable_mkldnn=True,
                )
            except TypeError:
                # Compatibility with older PaddleOCR releases.
                _PADDLE_OCR_ENGINE = PaddleOCR(
                    lang="en",
                    use_angle_cls=False,
                )
            print(
                f"[PADDLEOCR TIMING] Model initialization: "
                f"{time.perf_counter() - init_started:.2f}s"
            )
            print("[PADDLEOCR DEBUG] CPU-friendly mobile OCR models selected")
        except Exception as exc:
            _PADDLE_OCR_INIT_ERROR = exc
            print(f"[PADDLEOCR DEBUG] Initialization failed: {exc}")
            return []

    try:
        # Capture the browser once, then OCR only the source-record region when
        # its visible rectangle can be identified. No DOM text is used as OCR
        # output; the DOM is only a locator for reducing image size.
        screenshot = Image.open(
            io.BytesIO(driver.get_screenshot_as_png())
        ).convert("RGB")

        crop_started = time.perf_counter()
        try:
            elements = driver.find_elements(
                By.XPATH,
                "//*[contains(normalize-space(.),'*') and contains(normalize-space(.),'@')]"
            )
            ranked = []
            for element in elements:
                try:
                    if (
                        not element.is_displayed()
                        or element.find_elements(
                            By.CSS_SELECTOR, "input, textarea, select, button"
                        )
                    ):
                        continue
                    candidate_text = re.sub(r"\\s+", " ", element.text or "").strip()
                    if (
                        candidate_text.count("*") < 4
                        or "@" not in candidate_text
                        or len(candidate_text) > 1400
                    ):
                        continue
                    rect = element.rect
                    if rect.get("width", 0) > 0 and rect.get("height", 0) > 0:
                        ranked.append((len(candidate_text), rect))
                except Exception:
                    continue

            if ranked:
                _, rect = min(ranked, key=lambda item: item[0])
                viewport = driver.execute_script(
                    "return {w: window.innerWidth, h: window.innerHeight};"
                ) or {}
                scale_x = screenshot.width / max(
                    1, int(viewport.get("w", screenshot.width))
                )
                scale_y = screenshot.height / max(
                    1, int(viewport.get("h", screenshot.height))
                )
                pad_x, pad_y = 18, 14
                left = max(0, int(rect.get("x", 0) * scale_x) - pad_x)
                top = max(0, int(rect.get("y", 0) * scale_y) - pad_y)
                right = min(
                    screenshot.width,
                    int((rect.get("x", 0) + rect.get("width", 0)) * scale_x)
                    + pad_x,
                )
                bottom = min(
                    screenshot.height,
                    int((rect.get("y", 0) + rect.get("height", 0)) * scale_y)
                    + pad_y,
                )
                if right > left and bottom > top:
                    screenshot = screenshot.crop((left, top, right, bottom))
                    print(
                        f"[PADDLEOCR TIMING] Using targeted crop "
                        f"{screenshot.width}x{screenshot.height}"
                    )
        except Exception as crop_exc:
            print(f"[PADDLEOCR DEBUG] Targeted crop skipped: {crop_exc}")

        print(
            f"[PADDLEOCR TIMING] Screenshot/crop preparation: "
            f"{time.perf_counter() - crop_started:.2f}s"
        )

        import numpy as np
        image_array = np.asarray(screenshot)
        inference_started = time.perf_counter()

        if hasattr(_PADDLE_OCR_ENGINE, "predict"):
            result_items = _PADDLE_OCR_ENGINE.predict(image_array)
            recognized: list[tuple[float, float, str]] = []
            for result in result_items or []:
                data = getattr(result, "json", None)
                if callable(data):
                    data = data()
                if isinstance(data, dict) and isinstance(data.get("res"), dict):
                    data = data["res"]
                if not isinstance(data, dict):
                    continue
                texts = data.get("rec_texts") or []
                boxes = data.get("rec_boxes") or data.get("dt_polys") or []
                for index, text in enumerate(texts):
                    text = str(text or "").strip()
                    if not text:
                        continue
                    box = boxes[index] if index < len(boxes) else None
                    try:
                        top = float(min(point[1] for point in box))
                        left = float(min(point[0] for point in box))
                    except Exception:
                        top, left = float(index), 0.0
                    recognized.append((top, left, text))
        else:
            raw = _PADDLE_OCR_ENGINE.ocr(image_array, cls=False) or []
            recognized = []
            for page in raw:
                for line in page or []:
                    try:
                        box, info = line[0], line[1]
                        text = str(info[0] or "").strip()
                        top = float(min(point[1] for point in box))
                        left = float(min(point[0] for point in box))
                    except Exception:
                        continue
                    if text:
                        recognized.append((top, left, text))

        print(
            f"[PADDLEOCR TIMING] Inference: "
            f"{time.perf_counter() - inference_started:.2f}s"
        )

        recognized.sort(key=lambda item: (item[0], item[1]))
        if not recognized:
            return []

        lines = [item[2] for item in recognized]
        candidates = [" ".join(lines)]
        for size in (12, 9, 7):
            if len(lines) > size:
                for offset in range(0, len(lines) - size + 1, max(1, size // 2)):
                    candidates.append(" ".join(lines[offset:offset + size]))

        seen: set[str] = set()
        return [text for text in candidates if text and not (text in seen or seen.add(text))]
    except Exception as exc:
        print(f"[PADDLEOCR DEBUG] Recognition failed: {exc}")
        return []


def _show_crop_rectangle(
    driver: webdriver.Chrome,
    element,
) -> None:
    """Draw a visible red outline around the selected live webpage element."""
    try:
        result = driver.execute_script(
            """
            const target = arguments[0];

            const old = document.getElementById('__ocr_crop_debug__');
            if (old) old.remove();

            const r = target.getBoundingClientRect();
            const padX = 12;
            const padY = 10;

            const left = Math.max(0, r.left - padX);
            const top = Math.max(0, r.top - padY);
            const right = Math.min(
                window.innerWidth,
                r.right + padX
            );
            const bottom = Math.min(
                window.innerHeight,
                r.bottom + padY
            );

            if (right <= left || bottom <= top) {
                return {
                    visible: false,
                    reason: 'Target is outside the visible viewport',
                    x: left,
                    y: top,
                    width: right - left,
                    height: bottom - top
                };
            }

            const box = document.createElement('div');
            box.id = '__ocr_crop_debug__';

            Object.assign(box.style, {
                position: 'fixed',
                left: left + 'px',
                top: top + 'px',
                width: (right - left) + 'px',
                height: (bottom - top) + 'px',
                border: '5px solid #ff0000',
                background: 'rgba(255, 0, 0, 0.08)',
                boxSizing: 'border-box',
                pointerEvents: 'none',
                zIndex: '2147483647',
                display: 'block',
                visibility: 'visible',
                opacity: '1'
            });

            document.documentElement.appendChild(box);

            return {
                visible: true,
                x: left,
                y: top,
                width: right - left,
                height: bottom - top
            };
            """,
            element,
        )

        print(f"[OCR DEBUG] Live crop rectangle: {result}")

    except Exception as exc:
        print(f"[OCR DEBUG] Could not draw live crop rectangle: {exc}")



def _ocr_texts(driver: webdriver.Chrome) -> list[str]:
    """OCR fallback using several conservative image/preprocessing modes."""
    if pytesseract is None:
        raise RuntimeError(
            "Screenshot OCR is unavailable; install pytesseract and Tesseract OCR."
        )

    screenshot = Image.open(
        io.BytesIO(driver.get_screenshot_as_png())
    ).convert("RGB")

    images: list[Image.Image] = []

    # Prefer a crop around the visible source-record DOM element, if one can be located.
    try:
        elements = driver.find_elements(
            By.XPATH,
            "//*[contains(normalize-space(.),'*') and contains(normalize-space(.),'@')]"
        )
        ranked = []

        for element in elements:
            try:
                if (
                    not element.is_displayed()
                    or element.find_elements(
                        By.CSS_SELECTOR, "input, textarea, select, button"
                    )
                ):
                    continue

                text = re.sub(r"\s+", " ", element.text or "").strip()
                if text.count("*") < 4 or "@" not in text or len(text) > 1400:
                    continue

                rect = element.rect
                ranked.append((len(text), element, rect))

            except Exception:
                continue

        
        if ranked:
            _, target_element, rect = min(
                ranked,
                key=lambda item: item[0],
            )

            # Display the rectangle around the selected DOM element.
            _show_crop_rectangle(driver, target_element)

            viewport = driver.execute_script(
                "return {w: window.innerWidth, h: window.innerHeight};"
            ) or {}

            scale_x = screenshot.width / max(
                1, int(viewport.get("w", screenshot.width))
            )
            scale_y = screenshot.height / max(
                1, int(viewport.get("h", screenshot.height))
            )

            left = max(
                0, int(rect.get("x", 0) * scale_x) - 12
            )
            top = max(
                0, int(rect.get("y", 0) * scale_y) - 10
            )
            right = min(
                screenshot.width,
                int(
                    (rect.get("x", 0) + rect.get("width", 0)) * scale_x
                ) + 16,
            )
            bottom = min(
                screenshot.height,
                int(
                    (rect.get("y", 0) + rect.get("height", 0)) * scale_y
                ) + 12,
            )

            if right > left and bottom > top:
                # Preserve the original screenshot crop operation.
                images.append(
                    screenshot.crop((left, top, right, bottom))
                )
        else:
            print(
                "[OCR DEBUG] No suitable DOM element found for targeted cropping."
            )


    except Exception as exc:
        print(f"[OCR DEBUG] Targeted crop selection failed: {exc}")

    # ORIGINAL: Keep the full-screen fallback.
    images.append(screenshot)

    texts: list[str] = []
    seen: set[str] = set()

    for image in images:
        gray = ImageOps.grayscale(image)

        # ORIGINAL: Upscale small record text before OCR.
        if gray.width < 1200:
            ratio = min(2.0, 1200 / max(1, gray.width))
            gray = gray.resize(
                (int(gray.width * ratio), int(gray.height * ratio))
            )

        variants = [
            gray,
            ImageOps.autocontrast(gray),
            gray.point(lambda pixel: 255 if pixel > 170 else 0),
        ]

        for variant in variants:
            for mode in (6, 11, 12):
                try:
                    text = pytesseract.image_to_string(
                        variant,
                        config=f"--oem 3 --psm {mode}",
                    )
                    text = re.sub(r"\s+", " ", text).strip()

                    if text and text not in seen:
                        seen.add(text)
                        texts.append(text)

                except Exception:
                    continue

    return texts



def _record_quality(record: ReferenceRecord) -> int:
    """Rank candidates by completeness and absence of common OCR contamination."""
    fields = [record.get(key, "") for key in (
        "name", "designation", "company", "website", "address", "email", "phone"
    )]
    score = sum(2 for value in fields if value)
    combined = " ".join(fields).casefold()
    # These are known page-overlay/OCR artifacts, not valid field content.
    for marker in ("work report", "syp mno", "cumin oncece", "©", "®", "™", "____"):
        if marker in combined:
            score -= 8
    if re.match(r"^(?:[A-Z]{2,4}\\s+){1,3}", record.get("name", "")):
        score -= 5
    address = record.get("address", "")
    if re.search(r"(?:©|®|™|work report|\\bweer\\b|\\bwetter\\b)", address, re.I):
        score -= 8
    if not record.get("phone"):
        score -= 1
    return score


def _update_method_indicator(driver: webdriver.Chrome, text: str) -> None:
    """Update the UI's method label for diagnostics without affecting extraction."""
    callback = getattr(driver, "_method_indicator_callback", None)
    if callable(callback):
        try:
            callback(text)
        except Exception:
            pass
    print(f"[METHOD DEBUG] {text}")


def extract_visible_record(driver: webdriver.Chrome) -> ReferenceRecord | None:
    """Use PaddleOCR first, then the unchanged existing Tesseract fallback."""
    _update_method_indicator(driver, "Method: PaddleOCR recognition…")
    paddle_records: list[tuple[int, ReferenceRecord]] = []
    for candidate in _paddleocr_candidates(driver):
        record = parse_reference_text(candidate)
        if record is not None:
            paddle_records.append((_record_quality(record), record))
    if paddle_records:
        best_score, best_record = max(paddle_records, key=lambda item: item[0])
        if best_score >= 10:
            _update_method_indicator(driver, "Method used: PaddleOCR ✓")
            return best_record

    _update_method_indicator(driver, "Method: PaddleOCR unusable; existing Tesseract fallback…")
    ocr_records: list[tuple[int, ReferenceRecord]] = []
    for text in _ocr_texts(driver):
        record = parse_reference_text(text)
        if record is not None:
            ocr_records.append((_record_quality(record), record))
    if not ocr_records:
        _update_method_indicator(driver, "Method used: Tesseract fallback — no valid record")
        return None
    # Preserve the existing quality gate for the fallback results.
    best_score, best_record = max(ocr_records, key=lambda item: item[0])
    if best_score < 10:
        _update_method_indicator(driver, "Method used: Tesseract fallback — record rejected by existing quality check")
        return None
    _update_method_indicator(driver, "Method used: Tesseract fallback ✓")
    return best_record


api = Flask(__name__)


@api.get("/api/status")
def status() -> Any:
    return jsonify({"mode": "recognition_only"})


if __name__ == "__main__":
    ExtractionApp().run()
