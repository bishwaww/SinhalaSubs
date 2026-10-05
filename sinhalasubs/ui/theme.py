"""Colours and the Qt style sheet (Qt's version of CSS)."""

ACCENT = "#E8A33D"      # warm gold, like a temple lamp
BG = "#16171B"
PANEL = "#1F2127"
PANEL_2 = "#272A31"
BORDER = "#343842"
TEXT = "#E9EAEE"
MUTED = "#9A9FAB"
DANGER = "#E5534B"
OK = "#57AB5A"

STYLESHEET = f"""
QWidget {{ background: {BG}; color: {TEXT}; font-size: 10pt; }}
QFrame#Panel {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 10px; }}
QLabel#Title {{ font-size: 13pt; font-weight: 600; background: transparent; }}
QLabel#Section {{ color: {MUTED}; font-size: 8.5pt; font-weight: 600; letter-spacing: 1px;
                  background: transparent; padding-top: 6px; }}
QLabel {{ background: transparent; }}
QLabel#Muted {{ color: {MUTED}; }}

QPushButton {{ background: {PANEL_2}; border: 1px solid {BORDER}; border-radius: 7px; padding: 6px 12px; }}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton:pressed {{ background: {BORDER}; }}
QPushButton:disabled {{ color: {MUTED}; border-color: {PANEL_2}; }}
QPushButton#Primary {{ background: {ACCENT}; color: #1A1206; border: none; font-weight: 600; padding: 8px 14px; }}
QPushButton#Primary:hover {{ background: #F2B65A; }}
QPushButton#Primary:disabled {{ background: #6B5433; color: #2A2112; }}
QPushButton#Danger:hover {{ border-color: {DANGER}; color: {DANGER}; }}

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit {{
    background: {PANEL_2}; border: 1px solid {BORDER}; border-radius: 6px; padding: 4px 6px;
    selection-background-color: {ACCENT}; selection-color: #1A1206; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus {{ border-color: {ACCENT}; }}
QComboBox QAbstractItemView {{ background: {PANEL_2}; border: 1px solid {BORDER}; selection-background-color: {ACCENT}; }}

QListWidget, QTableView {{ background: {PANEL}; border: none; outline: none; alternate-background-color: #22252B; }}
QListWidget::item {{ padding: 6px; border-radius: 6px; }}
QListWidget::item:selected, QTableView::item:selected {{ background: #3A3222; color: {TEXT}; }}
QHeaderView::section {{ background: {PANEL}; color: {MUTED}; border: none; border-bottom: 1px solid {BORDER}; padding: 5px; }}
QTableView {{ gridline-color: {BORDER}; }}

QCheckBox {{ background: transparent; spacing: 6px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px; border: 1px solid {BORDER}; background: {PANEL_2}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QProgressBar {{ background: {PANEL_2}; border: none; border-radius: 4px; height: 8px; text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 4px; }}
QSlider::groove:horizontal {{ height: 4px; background: {BORDER}; border-radius: 2px; }}
QSlider::handle:horizontal {{ width: 14px; margin: -6px 0; border-radius: 7px; background: {ACCENT}; }}
QScrollBar:vertical {{ background: transparent; width: 10px; }}
QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 5px; min-height: 30px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; }}
QScrollBar::handle:horizontal {{ background: {BORDER}; border-radius: 5px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
QTabWidget::pane {{ border: none; }}
QTabBar::tab {{ background: transparent; color: {MUTED}; padding: 6px 12px; border-bottom: 2px solid transparent; }}
QTabBar::tab:selected {{ color: {TEXT}; border-bottom-color: {ACCENT}; }}
QToolTip {{ background: {PANEL_2}; color: {TEXT}; border: 1px solid {BORDER}; padding: 4px; }}
QMenu {{ background: {PANEL_2}; border: 1px solid {BORDER}; }}
QMenu::item:selected {{ background: {ACCENT}; color: #1A1206; }}
QSplitter::handle {{ background: {BG}; }}
"""
