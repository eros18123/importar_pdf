# -*- coding: utf-8 -*-
import os
import sys
import time
import subprocess
from aqt.qt import *

try:
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    from PyQt6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage
    HAS_WEBENGINE = True
except ImportError:
    HAS_WEBENGINE = False

def os_paste():
    """Simula Ctrl+V no nível do Sistema Operacional"""
    time.sleep(0.2)
    if sys.platform == 'win32':
        import ctypes
        ctypes.windll.user32.keybd_event(0x11, 0, 0, 0) # Ctrl
        ctypes.windll.user32.keybd_event(0x56, 0, 0, 0) # V
        ctypes.windll.user32.keybd_event(0x56, 0, 0x0002, 0)
        ctypes.windll.user32.keybd_event(0x11, 0, 0x0002, 0)
    elif sys.platform == 'darwin':
        subprocess.run(['osascript', '-e', 'tell application "System Events" to keystroke "v" using command down'])
    else:
        subprocess.run(['xdotool', 'key', 'ctrl+v'], capture_output=True)

class WebBrowserWidget(QWidget):
    def __init__(self, profile_dir):
        super().__init__()
        if not HAS_WEBENGINE:
            layout = QVBoxLayout(self)
            layout.addWidget(QLabel("PyQt6-WebEngine não instalado."))
            return
            
        # Configuração rigorosa para salvar o Login (Cookies e Cache)
        self.web_profile = QWebEngineProfile("AnkiUltimateProfile", self)
        self.web_profile.setPersistentStoragePath(profile_dir)
        self.web_profile.setCachePath(profile_dir)
        self.web_profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.AllowPersistentCookies)
        
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        self.add_new_tab("https://chatgpt.com")

    def add_new_tab(self, url):
        if not HAS_WEBENGINE: return None
        browser = QWebEngineView()
        browser.setPage(QWebEnginePage(self.web_profile, browser))
        browser.setUrl(QUrl(url))
        self.tabs.addTab(browser, "IA Web")
        return browser