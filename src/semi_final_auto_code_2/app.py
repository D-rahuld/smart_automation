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

    def __init__(self) -> None:
        # Tkinter is retained only as an invisible event loop. All visible UI
        # is rendered inside the Selenium-controlled Chrome page.
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        self.driver: webdriver.Chrome | None = None
        self.busy = False
        self.status = "Starting browser…"
        self.method_indicator = "Method: Waiting"
        self._panel_installed = False
        self._last_record = None
        self._current_form_number = 'Not selected'
        self._filled_count = 0
        self._automation_running = False

    def _build_window(self) -> None:
        # Compatibility shim: no desktop widgets are created.
        self.root.withdraw()

    def _panel_html(self) -> str:
        return r"""
(() => {
  if (document.getElementById('__visible_data_panel_host__')) return;
  const host = document.createElement('div');
  host.id = '__visible_data_panel_host__';
  host.style.cssText = 'position:fixed;z-index:2147483646;top:18px;left:18px;width:430px;height:560px;min-width:320px;min-height:300px;resize:both;overflow:hidden;box-sizing:border-box;';
  const shadow = host.attachShadow({mode:'open'});
  shadow.innerHTML = `
    <style>
      *{box-sizing:border-box}
      .panel{height:100%;width:100%;display:flex;flex-direction:column;background:#0f172a;color:#f8fafc;border:1px solid #475569;border-radius:12px;box-shadow:0 12px 35px #0008;font:14px Arial,sans-serif;overflow:hidden}
      header{display:flex;align-items:center;justify-content:space-between;padding:12px 14px;background:#111c32;cursor:move;user-select:none}
      h2{font-size:19px;margin:0;font-weight:700}
      .headbuttons{display:flex;gap:6px}
      button{border:0;border-radius:5px;color:white;padding:10px 12px;font-weight:700;cursor:pointer}
      button:disabled{opacity:.55;cursor:wait}
      .hide{background:#334155;padding:5px 9px}
      .loading{display:none;align-items:center;justify-content:center;gap:8px;color:#93c5fd;padding:4px 10px}
      .spinner{width:14px;height:14px;border:2px solid #475569;border-top-color:#38bdf8;border-radius:50%;animation:spin .7s linear infinite}
      @keyframes spin{to{transform:rotate(360deg)}}
      .method{color:#94a3b8;text-align:center;padding:8px 10px 2px}
      .status{color:#38bdf8;text-align:center;padding:7px 12px;max-height:58px;overflow:auto;overflow-wrap:anywhere}
      .actions{display:flex;justify-content:center;gap:9px;flex-wrap:wrap;padding:6px 10px 12px;flex-shrink:0}
      .open{background:#2563eb}.read{background:#16a34a}.send{background:#7c3aed}.copy{background:#475569}.tracker{display:flex;align-items:center;gap:7px;margin:0 10px 8px;padding:8px 10px;background:#172554;border:1px solid #1e40af;border-radius:6px;font-size:12px;flex-shrink:0}.tracker strong{color:#bfdbfe}.tracker input{width:62px;padding:6px;background:#0f172a;color:#fff;border:1px solid #475569;border-radius:4px}.tracker button{padding:6px 9px;background:#1d4ed8}.tracker .count{margin-left:auto;color:#cbd5e1}
      textarea{display:block;width:calc(100% - 20px);min-height:0;flex:1;resize:none;margin:0 10px 10px;padding:12px;background:#1e293b;color:#e2e8f0;border:0;border-radius:5px;outline:1px solid #334155;font:14px/1.45 Arial,sans-serif}
      .reopen{position:fixed;left:18px;top:18px;display:none;background:#0f172a;color:white;border:1px solid #64748b;border-radius:9px;padding:10px 13px;box-shadow:0 6px 20px #0008}
      .confirm-overlay{position:absolute;inset:0;z-index:1000;display:flex;align-items:center;justify-content:center;padding:16px;background:#020617eF}
      .confirm-box{width:100%;max-width:340px;background:#1e293b;border:1px solid #64748b;border-radius:10px;padding:18px;box-shadow:0 10px 35px #000a}
      .confirm-message{white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.5;margin:0 0 16px}
      .confirm-actions{display:flex;justify-content:flex-end;gap:8px}
      .confirm-continue{background:#16a34a}.confirm-stop{background:#dc2626}
    </style>
    <div class="panel" id="panel">
      <header id="drag"><h2>Visible Data Recognition</h2><div class="headbuttons"><button class="hide" id="hide" title="Hide panel">—</button></div></header>
      <div class="method" id="method">Method: Waiting</div>
      <div class="status" id="status">Open the website, then read the visible record.</div>
      <div class="loading" id="loading"><span class="spinner"></span><span>Reading visible data…</span></div>
      <div class="tracker">
        <span>Form:</span><strong id="formNumber">Not selected</strong>
        <span class="count" id="fillCount">Filled: 0</span>
        <input id="goFormNumber" type="number" min="1" step="1" placeholder="No."/>
        <button id="goForm">Go</button>
      </div>
      <div class="actions">
        <button class="open" id="open">Open Website</button>
        <button class="read" id="read">Read Visible Data</button>
        <button class="send" id="send">Send</button>
        <button class="copy" id="auto">Start Automation</button>
      </div>
      <textarea id="result" spellcheck="false">Recognized data will appear here.</textarea>
    </div>
    <button class="reopen" id="reopen">Open recognition panel</button>
  `;
  const q = id => shadow.getElementById(id);
  const setAction = action => { window.__visibleDataAction = action; };
  window.__visibleDataShowConfirmation = message => {
    const old=shadow.getElementById('automation-confirm-overlay');
    if(old) old.remove();
    window.__visibleDataPopupChoice='';
    const overlay=document.createElement('div');
    overlay.id='automation-confirm-overlay';
    overlay.className='confirm-overlay';
    const box=document.createElement('div');
    box.className='confirm-box';
    const msg=document.createElement('div');
    msg.className='confirm-message';
    msg.textContent=String(message||'');
    const actions=document.createElement('div');
    actions.className='confirm-actions';
    const stop=document.createElement('button');
    stop.className='confirm-stop';
    stop.textContent='Stop Automation';
    stop.onclick=()=>{window.__visibleDataStopRequested=true;window.__visibleDataPopupChoice='stop';overlay.remove();};
    const cont=document.createElement('button');
    cont.className='confirm-continue';
    cont.textContent='Continue';
    cont.onclick=()=>{window.__visibleDataPopupChoice='continue';overlay.remove();};
    actions.append(stop,cont);box.append(msg,actions);overlay.appendChild(box);
    q('panel').appendChild(overlay);
  };
  q('open').onclick = () => setAction('open');
  q('read').onclick = () => setAction('read');
  q('send').onclick = () => setAction('send');
  q('goForm').onclick = () => { const n=Number(q('goFormNumber').value); if(Number.isInteger(n)&&n>0) setAction('go_form:'+n); else q('status').textContent='Enter a form number greater than zero.'; };
  q('goFormNumber').addEventListener('keydown', e => { if(e.key==='Enter') q('goForm').click(); });
  q('auto').onclick = () => {
     if (window.__visibleDataAutomationRunning) {
       window.__visibleDataStopRequested = true;
       q('auto').textContent = 'Stop Automation';
       q('status').textContent = 'Stop requested. The current safe step will finish first.';
       return;
     }
     const n=Number(q('goFormNumber').value);
     if(Number.isInteger(n)&&n>0) setAction('auto:'+n);
     else q('status').textContent='Enter a starting form number greater than zero.';
   };
  q('hide').onclick = () => { q('panel').style.display='none'; q('reopen').style.display='block'; };
  q('reopen').onclick = () => { q('panel').style.display='flex'; q('reopen').style.display='none'; };
  // Drag by header, while preserving the panel's resize handle.
  let drag=null;
  q('drag').addEventListener('pointerdown', e => {
    if (e.target.closest('button')) return;
    const r=host.getBoundingClientRect();
    drag={x:e.clientX-r.left,y:e.clientY-r.top};
    q('drag').setPointerCapture(e.pointerId);
  });
  q('drag').addEventListener('pointermove', e => {
    if(!drag) return;
    host.style.left=Math.max(0,e.clientX-drag.x)+'px';
    host.style.top=Math.max(0,e.clientY-drag.y)+'px';
  });
  q('drag').addEventListener('pointerup',()=>drag=null);
  document.documentElement.appendChild(host);
})();
"""

    def _install_panel(self) -> None:
        if self.driver is None:
            return
        try:
            self.driver.execute_script(self._panel_html())
            self._panel_installed = True
            self._update_panel()
            self.root.after(150, self._poll_panel_action)
        except WebDriverException as exc:
            print(f"[PANEL DEBUG] Could not install browser panel: {exc}")

    def _update_panel(self, from_automation: bool = False) -> None:
        # Selenium is not thread-safe. During automation, only its worker thread
        # may push panel updates; scheduled Tk callbacks must not race it.
        if self._automation_running and not from_automation:
            return
        if self.driver is None or not self._panel_installed:
            return
        try:
            self.driver.execute_script(
                """
                const host=document.getElementById('__visible_data_panel_host__');
                if(!host || !host.shadowRoot) return;
                const s=host.shadowRoot;
                s.getElementById('status').textContent=arguments[0];
                s.getElementById('method').textContent=arguments[1];
                s.getElementById('result').value=arguments[2];
                s.getElementById('open').disabled=arguments[3];
                s.getElementById('read').disabled=arguments[3];
                s.getElementById('send').disabled=arguments[3];
                s.getElementById('goForm').disabled=arguments[3];
                s.getElementById('loading').style.display=arguments[3]?'flex':'none';
                const autoButton=s.getElementById('auto');
                if(autoButton) autoButton.textContent=arguments[4]?'Stop Automation':'Start Automation';
                """,
                self.status, self.method_indicator,
                getattr(self, "_result_text", "Recognized data will appear here."),
                self.busy, self._automation_running,
            )
            self.driver.execute_script(
                "const h=document.getElementById('__visible_data_panel_host__');"
                "if(h&&h.shadowRoot){h.shadowRoot.getElementById('formNumber').textContent=arguments[0];"
                "h.shadowRoot.getElementById('fillCount').textContent='Filled: '+arguments[1];}",
                str(getattr(self, "_current_form_number", "Not selected")),
                getattr(self, "_filled_count", 0)
            )
        except WebDriverException:
            # Navigation replaces the document; the panel is installed again
            # after the controlled page finishes loading.
            self._panel_installed = False

    def _poll_panel_action(self) -> None:
        if self.driver is None:
            return
        try:
            if not self.busy and self._panel_installed:
                action = self.driver.execute_script(
                    "const a=window.__visibleDataAction||''; "
                    "window.__visibleDataAction=''; return a;"
                )
                if action == "open":
                    self.open_website()
                elif action == "read":
                    self.read_visible_data()
                elif action == "send":
                    self.send_result_to_form()
                elif action.startswith("go_form:"):
                    self.go_to_form_number(int(action.split(":", 1)[1]))
                elif action.startswith("auto:"):
                    self.start_automation(int(action.split(":", 1)[1]))
        except WebDriverException:
            self._panel_installed = False
        if self.root.winfo_exists():
            self.root.after(150, self._poll_panel_action)

    def _resize_ui(self, event) -> None:
        # Kept as a compatibility method; resizing is handled by CSS in Chrome.
        return

    def set_status(self, text: str) -> None:
        clean_text = " ".join(str(text).split())
        if len(clean_text) > 180:
            clean_text = clean_text[:177] + "..."
        self.status = clean_text
        self.root.after(0, self._update_panel)

    def set_method_indicator(self, text: str) -> None:
        self.method_indicator = str(text)
        self.root.after(0, self._update_panel)

    def show_result(self, text: str) -> None:
        self._result_text = str(text)
        self.root.after(0, self._update_panel)

    def set_busy(self, busy: bool) -> None:
        self.busy = busy
        self.root.after(0, self._update_panel)

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
                # Keep the panel visible during OCR. Exclude it only from the
                # instant a screenshot is captured, without editing OCR methods.
                original_screenshot = self.driver.get_screenshot_as_png
                def screenshot_without_panel():
                    try:
                        self.driver.execute_script(
                            "const h=document.getElementById('__visible_data_panel_host__');"
                            "if(h){h.dataset.__ocrPreviousVisibility=h.style.visibility;"
                            "h.style.visibility='hidden';}"
                        )
                    except Exception:
                        pass
                    try:
                        return original_screenshot()
                    finally:
                        try:
                            self.driver.execute_script(
                                "const h=document.getElementById('__visible_data_panel_host__');"
                                "if(h){h.style.visibility=h.dataset.__ocrPreviousVisibility||'';"
                                "delete h.dataset.__ocrPreviousVisibility;}"
                            )
                        except Exception:
                            pass
                self.driver.get_screenshot_as_png = screenshot_without_panel

            self._panel_installed = False
            self.set_status("Opening the website…")
            self.driver.get(URL)
            time.sleep(2)

            username = self._find_input(("Username", "username", "mail", "email"))
            password = self._find_input(("Password", "password", "mobile", "phone"))
            if username is not None and password is not None:
                if not USERNAME or not PASSWORD:
                    self.set_status("Log in manually in Chrome, open the Start Work page, then use Read Visible Data.")
                    self._install_panel()
                    return
                username.clear()
                username.send_keys(USERNAME)
                password.clear()
                password.send_keys(PASSWORD)
                self._click_sign_in()
                time.sleep(3)

            self.driver.get(START_TASK_URL)
            time.sleep(3)
            self._panel_installed = False
            self._install_panel()
            self.set_status("Website is ready. Use Read Visible Data.")
        except Exception as exc:
            error_text = str(exc)
            if "ERR_INTERNET_DISCONNECTED" in error_text:
                self.set_status("Internet disconnected. Reconnect and click Open Website.")
            else:
                self.set_status(f"Could not open website: {error_text[:140]}")
            print(f"[OPEN WEBSITE ERROR] {exc}")
        finally:
            self.set_busy(False)
            self.root.after(0, self._update_panel)

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

    def _detect_current_form_number(self) -> str:
        """Read the selected QRCode form number from the page's Select Form control."""
        if self.driver is None:
            return "Not selected"
        try:
            value = self.driver.execute_script(r"""
                const visible = el => !!(el && el.getClientRects().length);
                const qrNumber = text => {
                  const m = String(text || '').match(/QR\s*Code\s*[-:#]?\s*(\d+)/i);
                  return m ? m[1] : null;
                };
                for (const el of Array.from(document.querySelectorAll('select'))) {
                  if (!visible(el)) continue;
                  const label = (el.labels ? Array.from(el.labels).map(x=>x.innerText).join(' ') : '') +
                    ' ' + (el.parentElement ? el.parentElement.innerText : '');
                  if (/select\s*form/i.test(label) || /QR\s*Code/i.test(el.value)) {
                    const option = el.options && el.selectedIndex >= 0 ? el.options[el.selectedIndex] : null;
                    const n = qrNumber((option && option.text) || el.value);
                    if (n) return n;
                  }
                }
                // Some UI libraries render a custom dropdown instead of a native select.
                for (const el of Array.from(document.querySelectorAll('input,[role="combobox"],button,[aria-haspopup="listbox"]'))) {
                  if (!visible(el)) continue;
                  const label = [el.getAttribute('aria-label'), el.getAttribute('placeholder'),
                    el.value, el.innerText, el.textContent,
                    el.parentElement && el.parentElement.innerText].filter(Boolean).join(' ');
                  if (/select\s*form/i.test(label) || /QR\s*Code/i.test(label)) {
                    const n = qrNumber(label);
                    if (n) return n;
                  }
                }
                const bodyText = document.body ? document.body.innerText : '';
                const m = bodyText.match(/Select\s*Form[\s\S]{0,180}?QR\s*Code\s*[-:#]?\s*(\d+)/i);
                return m ? m[1] : null;
            """)
            return str(value) if value else "Not selected"
        except WebDriverException:
            return "Not selected"

    def go_to_form_number(self, form_number: int) -> None:
        """Select QRCode - N in the website's Select Form dropdown."""
        if self.busy:
            return
        if self.driver is None:
            self.set_status("Browser is not ready. Click Open Website.")
            return
        if form_number < 1:
            self.set_status("Enter a form number greater than zero.")
            return
        self.set_busy(True)
        threading.Thread(target=self._go_to_form_number, args=(form_number,), daemon=True).start()

    def _go_to_form_number(self, form_number: int) -> None:
        selected_ok = False
        try:
            result = self.driver.execute_script(r"""
                const wanted = Number(arguments[0]);
                const visible = el => !!(el && el.getClientRects().length);
                const getNumber = text => {
                  const m = String(text || '').match(/QR\s*Code\s*[-:#]?\s*(\d+)/i);
                  return m ? Number(m[1]) : null;
                };
                // Preferred path: select the matching option in the actual Select Form dropdown.
                for (const select of Array.from(document.querySelectorAll('select'))) {
                  if (!visible(select) || select.disabled) continue;
                  const label = (select.labels ? Array.from(select.labels).map(x=>x.innerText).join(' ') : '') +
                    ' ' + (select.parentElement ? select.parentElement.innerText : '');
                  const option = Array.from(select.options || []).find(o =>
                    getNumber(o.text) === wanted || String(o.value || '').trim() === String(wanted));
                  if (option && (/select\s*form/i.test(label) || Array.from(select.options || []).some(o => /QR\s*Code/i.test(o.text)))) {
                    select.value = option.value;
                    select.dispatchEvent(new Event('input', {bubbles:true}));
                    select.dispatchEvent(new Event('change', {bubbles:true}));
                    select.focus();
                    return {ok:true, method:'native-select', number:wanted};
                  }
                }
                // Custom dropdown: open the control associated with the Select Form label.
                const labels = Array.from(document.querySelectorAll('label')).filter(visible);
                for (const label of labels) {
                  if (!/select\s*form/i.test(label.innerText || label.textContent || '')) continue;
                  const forId = label.getAttribute('for');
                  let control = forId ? document.getElementById(forId) : null;
                  if (!control) control = label.parentElement && label.parentElement.querySelector('input,[role="combobox"],button,[aria-haspopup="listbox"]');
                  if (control && visible(control)) { control.click(); break; }
                }
                const controls = Array.from(document.querySelectorAll('input,[role="combobox"],button,[aria-haspopup="listbox"]')).filter(visible);
                const trigger = controls.find(el => /select\s*form/i.test([
                  el.getAttribute('aria-label'), el.getAttribute('placeholder'),
                  el.parentElement && el.parentElement.innerText].filter(Boolean).join(' ')));
                if (trigger) trigger.click();
                const options = Array.from(document.querySelectorAll('[role="option"],option,li,button,[role="menuitem"],.dropdown-item')).filter(visible);
                const target = options.find(el => getNumber(el.innerText || el.textContent) === wanted ||
                  String(el.innerText || el.textContent || '').trim() === 'QRCode - ' + wanted ||
                  String(el.innerText || el.textContent || '').trim() === 'QR Code - ' + wanted);
                if (target) { target.click(); return {ok:true,method:'custom-option',number:wanted}; }
                return {ok:false, reason:'Could not find QRCode - '+wanted+' in the Select Form dropdown'};
            """, form_number)
            if not result or not result.get("ok"):
                self.set_status(result.get("reason", f"Could not select QRCode - {form_number}.") if result else
                                f"Could not select QRCode - {form_number}.")
                return
            time.sleep(1.0)
            self._current_form_number = self._detect_current_form_number()
            self._filled_count = 0
            self._install_panel()
            selected_ok = True
            self.set_status(
                f"Selected QRCode - {self._current_form_number}. "
                "Reading visible data in 1 second…"
            )
        except WebDriverException:
            self.set_status("The browser was closed while selecting the requested form.")
        except Exception as exc:
            self.set_status(f"Could not select QRCode - {form_number}: {str(exc)[:120]}")
        finally:
            self.set_busy(False)
            self.root.after(0, self._update_panel)
            if selected_ok:
                # Let the website finish updating the selected form before OCR starts.
                self.root.after(1000, self.read_visible_data)

    def start_automation(self, start_number: int) -> None:
        """Run the form-processing sequence from the requested QRCode number."""
        if self.busy:
            return
        if self.driver is None:
            self.set_status("Browser is not ready. Click Open Website.")
            return
        if start_number < 1:
            self.set_status("Enter a starting form number greater than zero.")
            return
        self._automation_running = True
        try:
            self.driver.execute_script("window.__visibleDataAutomationRunning=true; window.__visibleDataStopRequested=false;")
        except WebDriverException:
            self._automation_running = False
            self.set_status("Could not start automation on the current page.")
            return
        self.set_busy(True)
        self.root.after(0, self._update_panel)
        threading.Thread(target=self._run_automation, args=(start_number,), daemon=True).start()

    def _automation_stop_requested(self) -> bool:
        if not self._automation_running or self.driver is None:
            return True
        try:
            return bool(self.driver.execute_script("return !!window.__visibleDataStopRequested;"))
        except WebDriverException:
            return True

    def _show_automation_confirmation(self, message: str) -> bool:
        """Show a dismissible in-panel confirmation without blocking browser JS."""
        if self.driver is None:
            return False
        self.driver.execute_script(
            "if(window.__visibleDataShowConfirmation) window.__visibleDataShowConfirmation(arguments[0]);",
            message,
        )
        while self._automation_running and self.driver is not None:
            try:
                choice = self.driver.execute_script(
                    "return window.__visibleDataPopupChoice || '';"
                )
            except WebDriverException:
                return False
            if choice == "continue":
                return not self._automation_stop_requested()
            if choice == "stop" or self._automation_stop_requested():
                return False
            time.sleep(0.1)
        return False

    def _run_automation(self, start_number: int) -> None:
        """Process forms sequentially; only click explicit Generate QR / Next controls."""
        processed = 0
        skipped = 0
        try:
            numbers = self.driver.execute_script(r"""
                const visible = el => !!(el && el.getClientRects().length);
                const num = text => { const m=String(text||'').match(/QR\s*Code\s*[-:#]?\s*(\d+)/i); return m?Number(m[1]):null; };
                for (const s of Array.from(document.querySelectorAll('select'))) {
                  if (!visible(s) || s.disabled) continue;
                  const label=(s.labels?Array.from(s.labels).map(x=>x.innerText).join(' '):'')+' '+(s.parentElement?s.parentElement.innerText:'');
                  if (/select\s*form/i.test(label) || Array.from(s.options||[]).some(o=>/QR\s*Code/i.test(o.text))) {
                    return Array.from(s.options||[]).map(o=>num(o.text) ?? (/^\d+$/.test(String(o.value||''))?Number(o.value):null)).filter(n=>n!==null).filter((n,i,a)=>a.indexOf(n)===i).sort((a,b)=>a-b);
                  }
                }
                return [];
            """) or []
            numbers = [int(n) for n in numbers if int(n) >= start_number]
            if not numbers:
                # Custom dropdown fallback: avoid guessing the full list. Process the requested form only.
                numbers = [start_number]
            for number in numbers:
                if self._automation_stop_requested():
                    self.set_status("Automation stopped by user.")
                    break
                if self.driver is None:
                    break
                self.set_status(f"Automation: opening QRCode - {number}…")
                self._update_panel(from_automation=True)
                if not self._select_form_sync(number):
                    self.set_status(f"Stopped safely: could not verify selection of QRCode - {number}. No data was read or entered.")
                    self._update_panel(from_automation=True)
                    break
                self._current_form_number = str(number)
                # Give the website time to refresh the record content after the
                # dropdown selection, then verify the form identity once more.
                time.sleep(1.0)
                actual_number = self._detect_current_form_number()
                if str(actual_number) != str(number):
                    self.set_status(
                        f"Stopped safely: requested QRCode - {number}, but the page now shows "
                        f"QRCode - {actual_number}. No data was read or entered."
                    )
                    self._update_panel(from_automation=True)
                    break
                self._current_form_number = str(actual_number)
                self._filled_count = 0
                self.set_status(f"QRCode - {number}: reading visible data…")
                self._update_panel(from_automation=True)
                self.driver._method_indicator_callback = self.set_method_indicator
                record = extract_visible_record(self.driver)
                if not record:
                    self.show_result("No complete record was recognized for QRCode - %s. Automation stopped to avoid filling the wrong data." % number)
                    self.set_status(f"Stopped safely at QRCode - {number}: recognition failed.")
                    self._update_panel(from_automation=True)
                    break
                self._last_record = dict(record)
                self.show_result(format_record(record))
                self._update_panel(from_automation=True)
                filled, missing = self._fill_record_sync(record)
                self._filled_count = len(filled)
                self._update_panel(from_automation=True)
                if not filled or missing:
                    self.set_status(f"Stopped at QRCode - {number}: filled {len(filled)} fields; missing {', '.join(missing) if missing else 'no fields filled'}. Please check manually.")
                    break
                # Wait in short increments so Stop remains responsive during the 5-second verification pause.
                for _ in range(50):
                    if self._automation_stop_requested():
                        self.set_status("Automation stopped by user after filling; no submission button was clicked.")
                        return
                    time.sleep(0.1)
                state = self._inspect_submission_state()
                if self._automation_stop_requested():
                    self.set_status("Automation stopped by user before changing submission state.")
                    break
                if state == 'already_submitted':
                    skipped += 1
                    self.set_status(f"Form {number} is already submitted (Not Allowed). Dismiss the confirmation to continue.")
                    self._update_panel(from_automation=True)
                    if not self._show_automation_confirmation(
                        f"Form no. {number} is already submitted. The disabled Not Allowed button was detected. This form will be skipped."
                    ):
                        self.set_status(f"Automation stopped after confirmation for form {number}.")
                        self._update_panel(from_automation=True)
                        break
                    continue
                if state != 'generate':
                    self.set_status(f"Stopped safely at QRCode - {number}: could not confidently identify Generate QR or Not Allowed.")
                    break
                if self._automation_stop_requested():
                    self.set_status("Automation stopped by user before clicking Generate QR.")
                    break
                if not self._click_exact_button('Generate QR'):
                    self.set_status(f"Stopped safely at QRCode - {number}: Generate QR could not be clicked.")
                    break
                if not self._wait_and_click_next(timeout=30):
                    if self._automation_stop_requested():
                        self.set_status(f"Automation stopped while waiting for Next on form {number}.")
                    else:
                        self.set_status(f"QRCode - {number}: Generate QR was clicked, but a visible Next button did not appear within 30 seconds. Check the page manually.")
                    self._update_panel(from_automation=True)
                    break
                processed += 1
                self._update_panel(from_automation=True)
                # Non-blocking in-panel confirmation; Stop remains available in the popup.
                if not self._show_automation_confirmation(
                    f"Form no. {number} completed: QR generated and Next clicked. Continue to the next form?"
                ):
                    self.set_status(f"Automation stopped after completing form {number}.")
                    self._update_panel(from_automation=True)
                    break
                time.sleep(1.0)
            if self._automation_stop_requested():
                self.set_status(f"Automation stopped. QR generated: {processed}; already submitted/skipped: {skipped}.")
            else:
                self.set_status(f"Automation finished. QR generated: {processed}; already submitted/skipped: {skipped}. Review the website before restarting.")
        except WebDriverException:
            self.set_status("Automation stopped because the browser session ended.")
        except Exception as exc:
            self.set_status(f"Automation stopped safely: {str(exc)[:140]}")
        finally:
            self._automation_running = False
            try:
                if self.driver is not None:
                    self.driver.execute_script("window.__visibleDataAutomationRunning=false; window.__visibleDataStopRequested=false;")
            except WebDriverException:
                pass
            self.set_busy(False)
            self.root.after(0, self._update_panel)

    def _select_form_sync(self, form_number: int) -> bool:
        result = self.driver.execute_script(r"""
            const wanted=Number(arguments[0]);
            const visible=el=>!!(el&&el.getClientRects().length);
            const num=text=>{const m=String(text||'').match(/QR\s*Code\s*[-:#]?\s*(\d+)/i);return m?Number(m[1]):null;};
            for(const s of Array.from(document.querySelectorAll('select'))){
              if(!visible(s)||s.disabled)continue;
              const label=(s.labels?Array.from(s.labels).map(x=>x.innerText).join(' '):'')+' '+(s.parentElement?s.parentElement.innerText:'');
              const opt=Array.from(s.options||[]).find(o=>num(o.text)===wanted||String(o.value||'').trim()===String(wanted));
              if(opt&&(/select\s*form/i.test(label)||Array.from(s.options||[]).some(o=>/QR\s*Code/i.test(o.text)))){
                s.value=opt.value;s.dispatchEvent(new Event('input',{bubbles:true}));s.dispatchEvent(new Event('change',{bubbles:true}));return true;
              }
            }
            const trigger=Array.from(document.querySelectorAll('input,[role="combobox"],button,[aria-haspopup="listbox"]')).find(el=>visible(el)&&/select\s*form/i.test([el.getAttribute('aria-label'),el.getAttribute('placeholder'),el.parentElement&&el.parentElement.innerText].filter(Boolean).join(' ')));
            if(trigger)trigger.click();
            const options=Array.from(document.querySelectorAll('[role="option"],li,button,[role="menuitem"],.dropdown-item')).filter(visible);
            const target=options.find(el=>num(el.innerText||el.textContent)===wanted);
            if(target){target.click();return true;}return false;
        """, form_number)
        if not result:
            return False
        # A successful click/event is not proof that the website switched forms.
        # Verify the actual selected form before OCR or field filling can proceed.
        deadline = time.time() + 5.0
        while time.time() < deadline:
            if self._automation_stop_requested():
                return False
            actual = self._detect_current_form_number()
            if str(actual) == str(form_number):
                self._current_form_number = str(form_number)
                return True
            time.sleep(0.2)
        self.set_status(
            f"Requested QRCode - {form_number}, but the website still shows QRCode - "
            f"{self._detect_current_form_number()}. Selection was not verified."
        )
        return False

    def _fill_record_sync(self, record: dict) -> tuple[list[str], list[str]]:
        aliases_map = {
            "name": ("name", "full name", "contact name"),
            "designation": ("designation", "job title", "title"),
            "company": ("company name", "company", "organization", "organisation"),
            "website": ("website", "web site", "company website", "url"),
            "address": ("address", "company address", "location"),
            "email": ("email", "e-mail", "email address"),
            "phone": ("office contact", "phone", "telephone", "contact number"),
        }
        values={str(k).casefold():str(v or '').strip() for k,v in record.items()}
        filled=[]; missing=[]
        for key, aliases in aliases_map.items():
            value=values.get(key,'')
            if not value:
                missing.append(key); continue
            element=self.driver.execute_script("""
              const aliases=arguments[0].map(x=>x.toLowerCase());
              const visible=el=>!!(el&&el.getClientRects().length)&&!el.disabled&&el.type!=='hidden'&&!['submit','button','checkbox','radio'].includes((el.type||'').toLowerCase());
              const norm=s=>(s||'').replace(/[*:]/g,' ').replace(/\s+/g,' ').trim().toLowerCase();
              for(const el of Array.from(document.querySelectorAll('input,textarea,[contenteditable="true"]')).filter(visible)){
                const attrs=[el.name,el.id,el.placeholder,el.getAttribute('aria-label')].map(norm);let labelText='';
                if(el.id){const l=document.querySelector('label[for="'+CSS.escape(el.id)+'"]');if(l)labelText=norm(l.innerText||l.textContent);}
                const p=el.closest('label');if(p)labelText+=' '+norm(p.innerText||p.textContent);
                if(el.parentElement)labelText+=' '+norm(el.parentElement.innerText||el.parentElement.textContent).slice(0,120);
                const all=attrs.concat([norm(labelText)]);
                if(aliases.some(a=>all.some(t=>t===a||t.startsWith(a+' ')||t.includes(' '+a+' '))))return el;
              }return null;
            """, list(aliases))
            if element is None:
                missing.append(key); continue
            try: element.clear()
            except Exception: pass
            element.send_keys(value); filled.append(key)
        return filled, missing

    def _inspect_submission_state(self) -> str:
        return self.driver.execute_script(r"""
          // Disabled "Not Allowed" is meaningful: it indicates this form was already submitted.
          const visible=el=>!!(el&&el.getClientRects().length);
          const buttons=Array.from(document.querySelectorAll('button,input[type="button"],input[type="submit"],[role="button"]')).filter(visible);
          const label=el=>String(el.innerText||el.value||el.textContent||'').replace(/\s+/g,' ').trim().toLowerCase();
          if(buttons.some(el=>label(el)==='not allowed'))return 'already_submitted';
          if(buttons.some(el=>label(el)==='generate qr'))return 'generate';
          return 'unknown';
        """)

    def _click_exact_button(self, text: str) -> bool:
        return bool(self.driver.execute_script(r"""
          const wanted=String(arguments[0]).trim().toLowerCase();
          const visible=el=>!!(el&&el.getClientRects().length)&&!el.disabled&&el.getAttribute('aria-disabled')!=='true';
          const label=el=>String(el.innerText||el.value||el.textContent||'').replace(/\s+/g,' ').trim().toLowerCase();
          const el=Array.from(document.querySelectorAll('button,input[type="button"],input[type="submit"],[role="button"]')).find(x=>visible(x)&&label(x)===wanted);
          if(!el)return false;el.click();return true;
        """, text))

    def _wait_and_click_next(self, timeout: int = 30) -> bool:
        deadline=time.time()+timeout
        while time.time()<deadline:
            if self._automation_stop_requested():
                return False
            if self._click_exact_button('Next'):
                return True
            time.sleep(0.4)
        return False

    def read_visible_data(self) -> None:
        if self.busy:
            return
        if self.driver is None:
            self.set_status("Browser is not ready. Click Open Website.")
            return
        self.set_busy(True)
        threading.Thread(target=self._read_visible_data, daemon=True).start()

    def _read_visible_data(self) -> None:
        try:
            self.set_status("Looking for the visible record…")
            self.set_method_indicator("Method: Checking DOM…")
            # The panel stays visible. The screenshot wrapper above briefly
            # excludes it from screenshot pixels, so OCR sees the same page
            # content as before without any changes to OCR implementation.
            try:
                self.driver.execute_script(
                    "const s=document.getElementById('__ocr_crop_debug__');"
                    "if(s)s.remove();"
                )
            except Exception:
                pass

            self.driver._method_indicator_callback = self.set_method_indicator
            record = extract_visible_record(self.driver)

            if record is None:
                self.show_result(
                    "No complete record was recognized.\\n\\n"
                    "Make sure the seven asterisk-separated values are visible in the browser, then try again."
                )
                self.set_status("No complete record found.")
                return

            self._last_record = dict(record)
            self.show_result(format_record(record))
            self.set_status("Record recognized. Review it, then click Send to fill the form.")
        except WebDriverException:
            self.set_status("The browser was closed. Open the website again.")
        except Exception as exc:
            self.set_status(f"Recognition failed: {exc}")
        finally:
            self.set_busy(False)
            self.root.after(0, self._update_panel)

    def send_result_to_form(self) -> None:
        """Fill visible form fields from the last recognized record; never submit."""
        if self.busy:
            return
        if self.driver is None:
            self.set_status("Browser is not ready. Open the website first.")
            return
        if not self._last_record:
            self.set_status("No recognized record yet. Click Read Visible Data first.")
            return
        self.set_busy(True)
        threading.Thread(target=self._send_result_to_form, daemon=True).start()

    def _send_result_to_form(self) -> None:
        try:
            record = self._last_record or {}
            # Aliases are based on the fields shown in the current record form.
            field_aliases = {
                "name": ("name", "full name", "contact name"),
                "designation": ("designation", "job title", "title"),
                "company": ("company name", "company", "organization", "organisation"),
                "website": ("website", "web site", "company website", "url"),
                "address": ("address", "company address", "location"),
                "email": ("email", "e-mail", "email address"),
                "phone": ("office contact", "phone", "telephone", "contact number"),
            }
            values = {str(k).casefold(): str(v or "").strip() for k, v in record.items()}
            filled = []
            missing = []
            for key, aliases in field_aliases.items():
                value = values.get(key, "")
                if not value:
                    missing.append(key)
                    continue
                # Find a visible, enabled input by label text or common attributes.
                element = self.driver.execute_script("""
                    const aliases = arguments[0].map(x => x.toLowerCase());
                    const visible = el => !!(el && el.getClientRects().length) &&
                      !el.disabled && el.type !== 'hidden' &&
                      !['submit','button','checkbox','radio'].includes((el.type||'').toLowerCase());
                    const norm = s => (s||'').replace(/[*:]/g,' ').replace(/\\s+/g,' ').trim().toLowerCase();
                    const candidates = Array.from(document.querySelectorAll('input,textarea,[contenteditable="true"]')).filter(visible);
                    for (const el of candidates) {
                      const attrs = [el.name, el.id, el.placeholder, el.getAttribute('aria-label')].map(norm);
                      let labelText = '';
                      if (el.id) {
                        const label = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
                        if (label) labelText = norm(label.innerText || label.textContent);
                      }
                      const parentLabel = el.closest('label');
                      if (parentLabel) labelText += ' ' + norm(parentLabel.innerText || parentLabel.textContent);
                      const container = el.parentElement;
                      if (container) labelText += ' ' + norm(container.innerText || container.textContent).slice(0,120);
                      const all = attrs.concat([norm(labelText)]);
                      if (aliases.some(alias => all.some(text => text === alias || text.startsWith(alias + ' ') || text.includes(' ' + alias + ' ')))) return el;
                    }
                    return null;
                """, list(aliases))
                if element is None:
                    missing.append(key)
                    continue
                try:
                    element.clear()
                except Exception:
                    pass
                element.send_keys(value)
                filled.append(key)
            self._filled_count = len(filled)
            if filled:
                self.set_status("Filled form fields: " + ", ".join(filled) +
                                (". Review the values; nothing was submitted." if not missing else
                                 ". Could not find: " + ", ".join(missing) + ". Nothing was submitted."))
            else:
                self.set_status("Could not match recognized fields to visible form inputs. Nothing was submitted.")
        except WebDriverException:
            self.set_status("The browser was closed. The form was not filled.")
        except Exception as exc:
            self.set_status(f"Could not fill the form: {str(exc)[:130]}")
        finally:
            self.set_busy(False)
            self.root.after(0, self._update_panel)

    def close(self) -> None:
        try:
            if self.driver is not None:
                self.driver.quit()
        except Exception:
            pass
        self.root.destroy()

    def _watch_browser(self) -> None:
        """Stop the Python event loop when the controlled Chrome window is closed."""
        if not self.root.winfo_exists():
            return
        if self.driver is not None:
            try:
                # An empty handle list means the user closed the Chrome window.
                if not self.driver.window_handles:
                    self._stop_after_browser_closed()
                    return
            except WebDriverException:
                # Selenium loses its session when Chrome is closed externally.
                self._stop_after_browser_closed()
                return
        self.root.after(500, self._watch_browser)

    def _stop_after_browser_closed(self) -> None:
        """Stop Python without attempting to close a browser that is already gone."""
        try:
            self.driver = None
        except Exception:
            pass
        try:
            if self.root.winfo_exists():
                self.root.quit()
                self.root.destroy()
        except tk.TclError:
            pass

    def run(self) -> None:
        # Launch directly into the controlled browser; there is no desktop panel.
        self.root.after(100, self.open_website)
        self.root.after(500, self._watch_browser)
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
