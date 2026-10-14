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
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Visible Data Recognition")
        self.root.geometry("430x560")
        self.root.configure(bg="#0f172a")
        self.root.attributes("-topmost", True)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        self.driver: webdriver.Chrome | None = None
        self.busy = False
        self.status = tk.StringVar(value="Open the website, then read the visible record.")
        self.method_indicator = tk.StringVar(value="Method: Waiting")
        self._build_window()

        

    def _build_window(self) -> None:
        tk.Label(
            self.root,
            text="Visible Data Recognition",
            bg="#0f172a",
            fg="#f8fafc",
            font=("Arial", 17, "bold"),
        ).pack(pady=(22, 6))
        tk.Label(
            self.root,
            textvariable=self.method_indicator,
            bg="#0f172a",
            fg="#94a3b8",
            font=("Arial", 10),
        ).pack()

        tk.Label(
            self.root,
            textvariable=self.status,
            bg="#0f172a",
            fg="#38bdf8",
            wraplength=360,
            justify="center",
            font=("Arial", 10),
        ).pack(pady=18)

        button_frame = tk.Frame(self.root, bg="#0f172a")
        button_frame.pack(pady=(0, 12))
        self.open_button = tk.Button(
            button_frame,
            text="Open Website",
            command=self.open_website,
            bg="#2563eb",
            fg="white",
            activebackground="#1d4ed8",
            relief="flat",
            padx=14,
            pady=8,
            font=("Arial", 10, "bold"),
        )
        self.open_button.pack(side="left", padx=5)
        self.read_button = tk.Button(
            button_frame,
            text="Read Visible Data",
            command=self.read_visible_data,
            bg="#16a34a",
            fg="white",
            activebackground="#15803d",
            relief="flat",
            padx=14,
            pady=8,
            font=("Arial", 10, "bold"),
        )
        self.read_button.pack(side="left", padx=5)

        self.result = tk.Text(
            self.root,
            height=18,
            width=45,
            bg="#1e293b",
            fg="#e2e8f0",
            insertbackground="white",
            relief="flat",
            padx=14,
            pady=14,
            wrap="word",
            font=("Arial", 11),
        )
        self.result.pack(fill="both", expand=True, padx=22, pady=(0, 18))
        self.result.insert("1.0", "Recognized data will appear here.")
        self.result.configure(state="normal")

    def set_status(self, text: str) -> None:
        self.root.after(0, lambda: self.status.set(text))

    def set_method_indicator(self, text: str) -> None:
        self.root.after(0, lambda: self.method_indicator.set(text))

    def show_result(self, text: str) -> None:
        def update() -> None:
            self.result.configure(state="normal")
            self.result.delete("1.0", "end")
            self.result.insert("1.0", text)
            self.result.configure(state="normal")

        self.root.after(0, update)

    def set_busy(self, busy: bool) -> None:
        self.busy = busy
        state = "disabled" if busy else "normal"
        self.root.after(0, lambda: self.open_button.configure(state=state))
        self.root.after(0, lambda: self.read_button.configure(state=state))

    def open_website(self) -> None:
        if self.busy:
            return
        self.set_busy(True)
        threading.Thread(target=self._open_website, daemon=True).start()

    def _open_website(self) -> None:
        try:
            if self.driver is None:
                options = webdriver.ChromeOptions()
                options.add_argument("--start-maximized")
                self.driver = webdriver.Chrome(options=options)

            self.set_status("Opening the website…")
            self.driver.get(URL)
            time.sleep(2)

            username = self._find_input(("Username", "username", "mail", "email"))
            password = self._find_input(("Password", "password", "mobile", "phone"))
            if username is not None and password is not None:
                if not USERNAME or not PASSWORD:
                    self.set_status("Log in manually in Chrome, open the Start Work page, then click Read Visible Data here.")
                    return
                username.clear()
                username.send_keys(USERNAME)
                password.clear()
                password.send_keys(PASSWORD)
                self._click_sign_in()
                time.sleep(3)

            self.driver.get(START_TASK_URL)
            time.sleep(3)
            self.set_status("Website is ready. Click Read Visible Data.")
        except Exception as exc:
            self.set_status(f"Could not open the website: {exc}")
        finally:
            self.set_busy(False)

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

    def read_visible_data(self) -> None:
        if self.busy:
            return
        if self.driver is None:
            messagebox.showinfo("Website not open", "Open the website before reading data.")
            return
        self.set_busy(True)
        threading.Thread(target=self._read_visible_data, daemon=True).start()

    def _read_visible_data(self) -> None:
        try:
            self.set_status("Looking for the visible record…")
            self.set_method_indicator("Method: Checking DOM…")
            # Diagnostic callback only; it does not affect extraction decisions.
            self.driver._method_indicator_callback = self.set_method_indicator
            record = extract_visible_record(self.driver)
            if record is None:
                self.show_result("No complete record was recognized.\n\nMake sure the seven asterisk-separated values are visible in the browser, then try again.")
                self.set_status("No complete record found.")
                return
            self.show_result(format_record(record))
            self.set_status("Record recognized. Nothing was entered or submitted.")
        except WebDriverException:
            self.set_status("The browser was closed. Open the website again.")
        except Exception as exc:
            self.set_status(f"Recognition failed: {exc}")
        finally:
            self.set_busy(False)

    def close(self) -> None:
        try:
            if self.driver is not None:
                self.driver.quit()
        except Exception:
            pass
        self.root.destroy()

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
