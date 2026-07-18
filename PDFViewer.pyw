import os
import sys
import threading
from collections import deque
from queue import Empty, PriorityQueue
import fitz

from PySide6.QtCore import QObject, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QLineEdit,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QHBoxLayout,
    QWidget,
    QSizePolicy,
    QFrame,
    QSlider,
)


_RENDER_DOC_CACHE = threading.local()


def get_thread_render_document(file_path):
    docs = getattr(_RENDER_DOC_CACHE, "docs", None)
    if docs is None:
        docs = {}
        _RENDER_DOC_CACHE.docs = docs

    doc = docs.get(file_path)
    if doc is None:
        doc = fitz.open(file_path)
        docs[file_path] = doc

    return doc


def render_page_bytes(file_path, page_index, zoom):
    doc = get_thread_render_document(file_path)
    page = doc.load_page(page_index)
    matrix = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=matrix, alpha=False)
    return bytes(pix.samples), pix.width, pix.height, pix.stride


class PageRenderSignals(QObject):
    page_rendered = Signal(int, int, float, object, int, int, int)
    page_failed = Signal(int, int, str)


class WheelPageScrollArea(QScrollArea):
    def __init__(self, viewer):
        super().__init__()
        self.viewer = viewer
        self.dragging = False
        self.last_drag_pos = QPoint()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton and self.viewer.doc:
            self.viewer.toggle_fullscreen()
            event.accept()
            return

        super().mouseDoubleClickEvent(event)

    def wheelEvent(self, event):
        if not self.viewer.doc:
            event.ignore()
            return

        delta = event.angleDelta().y()

        if self.viewer.continuous_mode:
            super().wheelEvent(event)
            return

        if delta < 0:
            self.viewer.next_logical_page()
        elif delta > 0:
            self.viewer.prev_logical_page()

        event.accept()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.viewer.can_drag_view():
            self.dragging = True
            self.last_drag_pos = event.position().toPoint()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.dragging:
            delta = event.position().toPoint() - self.last_drag_pos
            self.last_drag_pos = event.position().toPoint()

            hbar = self.horizontalScrollBar()
            vbar = self.verticalScrollBar()
            hbar.setValue(hbar.value() - delta.x())
            if self.viewer.can_drag_vertical_in_view():
                vbar.setValue(vbar.value() - delta.y())
            event.accept()
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.dragging:
            self.dragging = False
            self.unsetCursor()
            event.accept()
            return

        super().mouseReleaseEvent(event)


class PageDisplayLabel(QLabel):
    def __init__(self, viewer):
        super().__init__()
        self.viewer = viewer

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.viewer.toggle_fullscreen()
            event.accept()
            return

        super().mouseDoubleClickEvent(event)


class PDFViewer(QMainWindow):
    SIDEBAR_BUTTON_STYLE = """
        QPushButton {
            background-color: #f4f6f8;
            color: #22303c;
            border: 1px solid #c5d0db;
            border-radius: 6px;
            font-weight: 500;
            font-size: 13px;
            padding: 0 8px;
            min-height: 28px;
        }
        QPushButton:hover {
            background-color: #e8f0fe;
            border-color: #7ea6d9;
        }
        QPushButton:pressed {
            background-color: #d6e4f7;
            border-color: #5d89c3;
        }
        QPushButton:disabled {
            background-color: #eef1f4;
            color: #8a97a3;
            border-color: #d7dde4;
        }
    """

    NAV_SLIDER_STYLE = """
        QSlider::groove:vertical {
            background: #d8dee6;
            width: 6px;
            border-radius: 3px;
        }
        QSlider::handle:vertical {
            background: #d70000;
            border: 1px solid #5d89c3;
            height: 36px;
            margin: -2px -8px;
            border-radius: 8px;
        }
        QSlider::handle:vertical:hover {
            background: #d70000;
        }
        QSlider::sub-page:vertical {
            background: #7ea6d9;
            border-radius: 3px;
        }
        QSlider::add-page:vertical {
            background: #edf1f5;
            border-radius: 3px;
        }
    """

    SEARCH_INPUT_STYLE = """
        QLineEdit {
            background-color: #fbfcfd;
            color: #22303c;
            border: 1px solid #c5d0db;
            border-right: none;
            border-top-left-radius: 6px;
            border-bottom-left-radius: 6px;
            padding: 0 8px;
            min-height: 28px;
        }
        QLineEdit:focus {
            border-color: #7ea6d9;
            background-color: #ffffff;
        }
    """

    SEARCH_ARROW_STYLE = """
        QPushButton {
            background: transparent;
            color: #5d89c3;
            border: 1px solid #c5d0db;
            border-left: none;
            border-top-right-radius: 1px;
            border-bottom-right-radius: 1px;
            font-size: 18px;
            font-weight: 800;
            min-height: 32px;
            padding: 0 4px 1px 4px;
        }
        QPushButton:hover {
            color: #3f6fae;
            background-color: #f6f9fc;
            border-color: #7ea6d9;
        }
        QPushButton:pressed {
            color: #2f5f99;
            background-color: #e9f0f8;
        }
    """

    PLACEHOLDER_LABEL_STYLE = """
        QLabel {
            color: #8a97a3;
            background: #f7f8fa;
            border: 1px solid #d7dde4;
        }
    """

    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDF Viewer")

        self.doc = None
        self.file_path = None

        self.zoom = 1.0
        self.current_index = 0
        self.fit_mode = True

        self.continuous_mode = False
        self.two_page_mode = True
        self.cover_mode = True

        self.page_labels = []
        self.search_matches = {}
        self.search_result_pages = []
        self.search_result_index = -1
        self.active_search_query = ""
        self.single_page_scroll_position = (0, 0)
        self.pending_single_page_scroll_restore = False
        self.pending_continuous_scroll_restore = False
        self.continuous_restore_page_index = 0
        self.updating_slider = False
        self.was_maximized_before_fullscreen = False
        self.render_generation = 0
        self.page_label_lookup = {}
        self.active_render_jobs = set()
        self.queued_render_jobs = set()
        self.render_queue = deque()
        self.page_size_cache = {}
        self.rendered_page_cache = {}
        self.render_thread_count = max(1, (os.cpu_count() or 2) - 1)
        #self.render_thread_count = 7
        self.render_queue_lock = threading.Lock()
        self.render_task_queue = PriorityQueue()
        self.render_request_sequence = 0
        self.stop_render_workers = False
        self.render_workers = []
        self.deferred_parallel_pages = []
        self.deferred_parallel_index = 0
        self.deferred_parallel_generation = 0
        self.deferred_parallel_zoom = 1.0
        self.fallback_render_pages = []
        self.fallback_render_index = 0
        self.fallback_render_generation = 0
        self.render_signals = PageRenderSignals()
        self.render_signals.page_rendered.connect(self.on_page_rendered)
        self.render_signals.page_failed.connect(self.on_page_render_failed)
        self.start_render_workers()
        self.resize_render_timer = QTimer(self)
        self.resize_render_timer.setSingleShot(True)
        self.resize_render_timer.timeout.connect(self.handle_delayed_resize)
        self.deferred_parallel_timer = QTimer(self)
        self.deferred_parallel_timer.setSingleShot(False)
        self.deferred_parallel_timer.setInterval(0)
        self.deferred_parallel_timer.timeout.connect(self.process_deferred_parallel_render)
        self.fallback_render_timer = QTimer(self)
        self.fallback_render_timer.setSingleShot(False)
        self.fallback_render_timer.setInterval(0)
        self.fallback_render_timer.timeout.connect(self.process_fallback_render)
        self.render_progress_timer = QTimer(self)
        self.render_progress_timer.setSingleShot(False)
        self.render_progress_timer.setInterval(30)
        self.render_progress_timer.timeout.connect(self.on_render_progress_tick)
        self.render_progress_timer.start()

        self.sidebar = self._build_sidebar()

        self.scroll_area = WheelPageScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_area.setStyleSheet("QScrollArea { border: none; background: white; }")
        self.scroll_area.horizontalScrollBar().rangeChanged.connect(
            self.on_single_page_scrollbar_range_changed
        )
        self.scroll_area.verticalScrollBar().valueChanged.connect(self.on_view_scrolled)
        self.scroll_area.verticalScrollBar().rangeChanged.connect(
            self.on_single_page_scrollbar_range_changed
        )
        self.scroll_area.verticalScrollBar().rangeChanged.connect(
            self.on_continuous_scrollbar_range_changed
        )

        self.page_container = QWidget()
        self.page_container.setStyleSheet("background: white;")
        self.page_layout = QVBoxLayout(self.page_container)
        self.page_layout.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        self.page_layout.setContentsMargins(0, 0, 0, 0)
        self.page_layout.setSpacing(0)

        self.scroll_area.setWidget(self.page_container)

        central = QWidget()
        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        root_layout.addWidget(self.sidebar)
        root_layout.addWidget(self.scroll_area, 1)

        self.setCentralWidget(central)

    def create_sidebar_button(self, text, handler):
        button = QPushButton(text)
        button.clicked.connect(handler)
        button.setCursor(Qt.PointingHandCursor)
        button.setStyleSheet(self.SIDEBAR_BUTTON_STYLE)
        return button

    def _build_sidebar(self):
        sidebar = QWidget()
        sidebar.setFixedWidth(120)

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignTop)

        self.open_button = self.create_sidebar_button("Open PDF", self.open_pdf)
        layout.addWidget(self.open_button)

        self.zoom_in_button = self.create_sidebar_button("Zoom +", self.zoom_in)
        layout.addWidget(self.zoom_in_button)

        self.zoom_out_button = self.create_sidebar_button("Zoom -", self.zoom_out)
        layout.addWidget(self.zoom_out_button)

        self.fit_button = self.create_sidebar_button("Fit page", self.fit_to_window)
        layout.addWidget(self.fit_button)

        self.single_cont_button = self.create_sidebar_button(
            "Continuous", self.toggle_continuous_mode
        )
        layout.addWidget(self.single_cont_button)

        self.two_page_button = self.create_sidebar_button(
            "2 Pages", self.toggle_two_page_mode
        )
        layout.addWidget(self.two_page_button)

        self.cover_button = self.create_sidebar_button(
            "Cover mode", self.toggle_cover_mode
        )
        layout.addWidget(self.cover_button)

        search_container = QWidget()
        search_layout = QHBoxLayout(search_container)
        search_layout.setContentsMargins(0, 0, 0, 0)
        search_layout.setSpacing(0)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search text")
        self.search_input.textChanged.connect(self.on_search_text_changed)
        self.search_input.returnPressed.connect(self.jump_to_next_search_result)
        self.search_input.setStyleSheet(self.SEARCH_INPUT_STYLE)
        search_layout.addWidget(self.search_input, 1)

        self.search_next_button = QPushButton(">")
        self.search_next_button.setCursor(Qt.PointingHandCursor)
        self.search_next_button.setStyleSheet(self.SEARCH_ARROW_STYLE)
        self.search_next_button.clicked.connect(self.jump_to_next_search_result)
        search_layout.addWidget(self.search_next_button)

        layout.addWidget(search_container)

        slider_container = QWidget()
        slider_layout = QHBoxLayout(slider_container)
        slider_layout.setContentsMargins(0, 0, 0, 0)
        slider_layout.setSpacing(0)

        slider_layout.addStretch(1)

        self.nav_slider = QSlider(Qt.Vertical)
        self.nav_slider.setMinimum(0)
        self.nav_slider.setMaximum(0)
        self.nav_slider.setValue(0)
        self.nav_slider.setEnabled(False)
        self.nav_slider.setInvertedAppearance(True)
        self.nav_slider.setInvertedControls(False)
        self.nav_slider.valueChanged.connect(self.on_slider_changed)
        self.nav_slider.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.nav_slider.setFixedWidth(30)
        self.nav_slider.setStyleSheet(self.NAV_SLIDER_STYLE)

        slider_layout.addWidget(self.nav_slider)
        slider_layout.addStretch(1)

        layout.addWidget(slider_container, 1)

        self.status_label = QLabel("No PDF loaded")
        self.status_label.setWordWrap(True)
        self.status_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        layout.addWidget(self.status_label)

        return sidebar

    def load_pdf(self, file_path):
        if not file_path:
            return

        if not os.path.exists(file_path):
            QMessageBox.critical(self, "Fehler", f"Datei nicht gefunden:\n{file_path}")
            return

        try:
            self.doc = fitz.open(file_path)
            self.file_path = file_path
            self.current_index = 0
            self.zoom = 1.0
            self.fit_mode = True
            self.search_matches = {}
            self.search_result_pages = []
            self.search_result_index = -1
            self.active_search_query = ""
            self.single_page_scroll_position = (0, 0)
            self.pending_single_page_scroll_restore = False
            self.page_size_cache = {}
            self.rendered_page_cache = {}
            self.setWindowTitle(f"PDF Viewer - {os.path.basename(file_path)}")
            self.render_view()
        except Exception as e:
            QMessageBox.critical(self, "Fehler", f"PDF konnte nicht geöffnet werden:\n{e}")

    def open_pdf(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Open PDF", "", "PDF Files (*.pdf)"
        )
        if not file_path:
            return
        self.load_pdf(file_path)

    def clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            child_layout = item.layout()

            if widget is not None:
                widget.deleteLater()
            elif child_layout is not None:
                self.clear_layout(child_layout)

    def make_page_label(self, pixmap, page_index):
        label = PageDisplayLabel(self)
        label.setAlignment(Qt.AlignCenter)
        label.setPixmap(pixmap)
        label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        label.page_index = page_index
        self.page_labels.append(label)
        self.page_label_lookup[page_index] = label
        return label

    def make_placeholder_page_label(self, page_index, zoom):
        width, height = self.get_page_display_size(page_index, zoom)
        label = PageDisplayLabel(self)
        label.setAlignment(Qt.AlignCenter)
        label.setText("Rendering...")
        label.setStyleSheet(self.PLACEHOLDER_LABEL_STYLE)
        label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        label.setFixedSize(width, height)
        label.page_index = page_index
        self.page_labels.append(label)
        self.page_label_lookup[page_index] = label
        return label

    def get_page_display_size(self, page_index, zoom):
        rect = self.page_size_cache.get(page_index)
        if rect is None:
            rect = self.doc.load_page(page_index).rect
            self.page_size_cache[page_index] = rect
        width = max(1, int(round(rect.width * zoom)))
        height = max(1, int(round(rect.height * zoom)))
        return width, height

    def get_render_cache_key(self, page_index, zoom):
        return (page_index, round(zoom, 4))

    def get_cached_base_pixmap(self, page_index, zoom):
        return self.rendered_page_cache.get(self.get_render_cache_key(page_index, zoom))

    def get_display_pixmap(self, page_index, zoom):
        base_pixmap = self.get_cached_base_pixmap(page_index, zoom)
        if base_pixmap is None:
            return None

        return self.apply_search_highlights(base_pixmap, page_index, zoom)

    def set_cached_base_pixmap(self, page_index, zoom, pixmap):
        self.rendered_page_cache[self.get_render_cache_key(page_index, zoom)] = pixmap

    def build_pixmap_from_bytes(self, samples, width, height, stride):
        image = QImage(samples, width, height, stride, QImage.Format_RGB888).copy()
        return QPixmap.fromImage(image)

    def page_to_pixmap(self, page_index, zoom):
        page = self.doc.load_page(page_index)
        matrix = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=matrix, alpha=False)

        image = QImage(
            pix.samples,
            pix.width,
            pix.height,
            pix.stride,
            QImage.Format_RGB888
        )
        pixmap = QPixmap.fromImage(image)
        return self.apply_search_highlights(pixmap, page_index, zoom)

    def apply_search_highlights(self, pixmap, page_index, zoom):
        rects = self.search_matches.get(page_index)
        if not rects:
            return pixmap

        highlighted = QPixmap(pixmap)
        painter = QPainter(highlighted)
        highlight_color = QColor(255, 255, 0, 110)

        for rect in rects:
            painter.fillRect(
                rect.x0 * zoom,
                rect.y0 * zoom,
                rect.width * zoom,
                rect.height * zoom,
                highlight_color,
            )

        painter.end()
        return highlighted

    def on_search_text_changed(self, _text):
        self.search_result_index = -1
        if not self.doc:
            self.search_matches = {}
            self.search_result_pages = []
            self.active_search_query = ""
            return

        if not self.search_input.text().strip():
            self.search_matches = {}
            self.search_result_pages = []
            self.active_search_query = ""
            self.render_view()

    def ensure_search_results(self):
        query = self.search_input.text().strip()

        if query == self.active_search_query:
            return False

        self.refresh_search_results(render=False)
        return True

    def refresh_search_results(self, render=True):
        query = self.search_input.text().strip()

        if not self.doc or not query:
            self.search_matches = {}
            self.search_result_pages = []
            self.search_result_index = -1
            self.active_search_query = ""
            if render and self.doc:
                self.render_view()
            return

        matches = {}
        result_pages = []

        for page_index in range(len(self.doc)):
            rects = self.doc.load_page(page_index).search_for(query)
            if rects:
                matches[page_index] = rects
                result_pages.append(page_index)

        self.search_matches = matches
        self.search_result_pages = result_pages
        self.search_result_index = -1
        self.active_search_query = query

        if render:
            self.render_view()

    def get_visible_page_range(self):
        if not self.doc:
            return (0, 0)

        if self.continuous_mode:
            current_page = self.get_most_visible_page_in_continuous()
            return (current_page, current_page)

        if self.two_page_mode:
            left, right = self.get_current_spread_pages_for_index(self.current_index)
            return (left, right if right is not None else left)

        return (self.current_index, self.current_index)

    def get_initial_search_result_index(self, forward=True):
        visible_start, visible_end = self.get_visible_page_range()

        if forward:
            return next(
                (
                    idx
                    for idx, page_index in enumerate(self.search_result_pages)
                    if page_index > visible_end
                ),
                0,
            )

        return next(
            (
                idx
                for idx in range(len(self.search_result_pages) - 1, -1, -1)
                if self.search_result_pages[idx] < visible_start
            ),
            len(self.search_result_pages) - 1,
        )

    def find_page_label(self, page_index):
        for label in self.page_labels:
            if getattr(label, "page_index", -1) == page_index:
                return label
        return None

    def get_centered_scroll_value_for_label(self, label):
        if label is None:
            return None

        scroll_bar = self.scroll_area.verticalScrollBar()
        viewport_height = self.scroll_area.viewport().height()
        label_top = label.mapTo(self.page_container, label.rect().topLeft()).y()
        label_center = label_top + (label.height() / 2)
        target_value = int(label_center - (viewport_height / 2))
        return max(scroll_bar.minimum(), min(scroll_bar.maximum(), target_value))

    def get_search_navigation_target(self, page_index):
        if self.continuous_mode:
            label = self.find_page_label(page_index)
            target_value = self.get_centered_scroll_value_for_label(label)
            return target_value if target_value is not None else page_index

        return self.logical_index_for_page(page_index)

    def get_current_search_navigation_target(self):
        if self.continuous_mode:
            return self.scroll_area.verticalScrollBar().value()

        return self.logical_index_for_page(self.current_index)

    def get_next_distinct_search_result_index(self, forward=True):
        if not self.search_result_pages:
            return -1

        current_target = self.get_current_search_navigation_target()
        step = 1 if forward else -1
        result_count = len(self.search_result_pages)
        start_index = self.search_result_index

        if start_index == -1:
            start_index = self.get_initial_search_result_index(forward)

        candidate_index = start_index
        for _ in range(result_count):
            candidate_page = self.search_result_pages[candidate_index]
            if self.get_search_navigation_target(candidate_page) != current_target:
                return candidate_index
            candidate_index = (candidate_index + step) % result_count

        return start_index

    def logical_index_for_page(self, page_index):
        if not self.two_page_mode:
            return page_index

        if self.cover_mode:
            if page_index <= 0:
                return 0
            return page_index if page_index % 2 == 1 else page_index - 1

        return page_index if page_index % 2 == 0 else page_index - 1

    def jump_to_search_page(self, page_index):
        try:
            self.search_result_index = self.search_result_pages.index(page_index)
        except ValueError:
            pass

        if not self.continuous_mode:
            self.remember_single_page_scroll_position()

        self.current_index = self.logical_index_for_page(page_index)
        self.normalize_current_index()

        if self.continuous_mode and self.scroll_to_page_in_continuous(page_index):
            return

        self.render_view()

    def jump_to_next_search_result(self):
        self.jump_to_search_result(forward=True)

    def jump_to_search_result(self, forward=True):
        search_changed = self.ensure_search_results()

        if not self.search_result_pages:
            return

        if search_changed:
            if not self.continuous_mode:
                self.remember_single_page_scroll_position()
            self.render_view()

        if self.search_result_index == -1:
            self.search_result_index = self.get_next_distinct_search_result_index(forward)
            self.jump_to_search_page(self.search_result_pages[self.search_result_index])
            return

        step = 1 if forward else -1
        self.search_result_index = (self.search_result_index + step) % len(self.search_result_pages)
        self.search_result_index = self.get_next_distinct_search_result_index(forward)

        self.jump_to_search_page(self.search_result_pages[self.search_result_index])

    def get_single_fit_zoom(self, page_index):
        page = self.doc.load_page(page_index)
        rect = page.rect

        viewport = self.scroll_area.viewport().size()
        available_width = max(50, viewport.width())
        available_height = max(50, viewport.height())

        zoom_x = available_width / rect.width
        zoom_y = available_height / rect.height
        return min(zoom_x, zoom_y)

    def get_spread_fit_zoom(self, left_index, right_index=None):
        viewport = self.scroll_area.viewport().size()
        available_width = max(50, viewport.width())
        available_height = max(50, viewport.height())

        left_rect = self.doc.load_page(left_index).rect
        total_width = left_rect.width
        max_height = left_rect.height

        if right_index is not None and right_index < len(self.doc):
            right_rect = self.doc.load_page(right_index).rect
            total_width += right_rect.width
            max_height = max(max_height, right_rect.height)

        zoom_x = available_width / total_width
        zoom_y = available_height / max_height
        return min(zoom_x, zoom_y)

    def get_current_spread_pages_for_index(self, index):
        if not self.two_page_mode:
            return (index, None)

        if self.cover_mode:
            if index == 0:
                return (0, None)
            left = index
            right = left + 1
            return (left, right if right < len(self.doc) else None)

        left = index
        right = left + 1
        return (left, right if right < len(self.doc) else None)

    def get_current_zoom(self):
        if not self.doc:
            self.zoom = 1.0
            return self.zoom

        if not self.fit_mode:
            return self.zoom

        if self.continuous_mode:
            if self.two_page_mode:
                pages = self.get_current_spread_pages_for_index(self.current_index)
                self.zoom = self.get_spread_fit_zoom(*pages)
                return self.zoom
            self.zoom = self.get_single_fit_zoom(self.current_index)
            return self.zoom

        if self.two_page_mode:
            pages = self.get_current_spread_pages_for_index(self.current_index)
            self.zoom = self.get_spread_fit_zoom(*pages)
            return self.zoom

        self.zoom = self.get_single_fit_zoom(self.current_index)
        return self.zoom

    def logical_indices(self):
        if not self.doc:
            return []

        total = len(self.doc)

        if not self.two_page_mode:
            return list(range(total))

        indices = []
        if self.cover_mode and total > 0:
            indices.append(0)
            i = 1
            while i < total:
                indices.append(i)
                i += 2
            return indices

        i = 0
        while i < total:
            indices.append(i)
            i += 2
        return indices

    def normalize_current_index(self):
        indices = self.logical_indices()
        if not indices:
            self.current_index = 0
            return

        if self.current_index in indices:
            return

        nearest = indices[0]
        for idx in indices:
            if idx <= self.current_index:
                nearest = idx
        self.current_index = nearest

    def remember_single_page_scroll_position(self):
        if not self.doc or self.continuous_mode:
            return

        self.single_page_scroll_position = (
            self.scroll_area.horizontalScrollBar().value(),
            self.scroll_area.verticalScrollBar().value(),
        )

    def restore_current_page_scroll_position(self):
        if not self.doc or self.continuous_mode or not self.pending_single_page_scroll_restore:
            return

        x_pos, y_pos = self.single_page_scroll_position
        self.scroll_area.horizontalScrollBar().setValue(x_pos)
        self.scroll_area.verticalScrollBar().setValue(y_pos)

    def finish_single_page_scroll_restore(self):
        if self.continuous_mode:
            self.pending_single_page_scroll_restore = False
            return

        self.restore_current_page_scroll_position()
        self.pending_single_page_scroll_restore = False

    def schedule_single_page_scroll_restore(self):
        if not self.doc or self.continuous_mode:
            return

        self.pending_single_page_scroll_restore = True
        QTimer.singleShot(0, self.restore_current_page_scroll_position)

    def on_single_page_scrollbar_range_changed(self, _minimum, _maximum):
        if not self.pending_single_page_scroll_restore or self.continuous_mode:
            return

        self.restore_current_page_scroll_position()
        QTimer.singleShot(0, self.finish_single_page_scroll_restore)

    def on_continuous_scrollbar_range_changed(self, _minimum, _maximum):
        if not self.pending_continuous_scroll_restore or not self.continuous_mode:
            return

        QTimer.singleShot(0, self.scroll_to_current_page_in_continuous)

    def can_drag_view(self):
        if not self.doc:
            return False

        hbar = self.scroll_area.horizontalScrollBar()
        vbar = self.scroll_area.verticalScrollBar()

        if self.continuous_mode:
            return hbar.maximum() > 0 or vbar.maximum() > 0

        return hbar.maximum() > 0 or vbar.maximum() > 0

    def can_drag_vertical_in_view(self):
        if not self.doc:
            return False

        return self.scroll_area.verticalScrollBar().maximum() > 0

    def next_logical_page(self):
        indices = self.logical_indices()
        if not indices:
            return

        self.remember_single_page_scroll_position()
        self.normalize_current_index()
        pos = indices.index(self.current_index)

        if pos < len(indices) - 1:
            self.current_index = indices[pos + 1]
            self.render_view()

    def prev_logical_page(self):
        indices = self.logical_indices()
        if not indices:
            return

        self.remember_single_page_scroll_position()
        self.normalize_current_index()
        pos = indices.index(self.current_index)

        if pos > 0:
            self.current_index = indices[pos - 1]
            self.render_view()

    def get_visible_priority_pages(self):
        if not self.doc:
            return []

        pages = []
        seen = set()
        total_pages = len(self.doc)

        def add(page_index):
            if page_index is None or page_index in seen:
                return
            if 0 <= page_index < total_pages:
                seen.add(page_index)
                pages.append(page_index)

        if self.continuous_mode:
            if self.two_page_mode:
                logical_indices = self.logical_indices()
                try:
                    current_pos = logical_indices.index(self.current_index)
                except ValueError:
                    current_pos = 0

                spread_radius = 6
                start = max(0, current_pos - spread_radius)
                end = min(len(logical_indices), current_pos + spread_radius + 1)

                for pos in range(start, end):
                    left, right = self.get_current_spread_pages_for_index(logical_indices[pos])
                    add(left)
                    add(right)
            else:
                page_radius = 12
                for offset in range(page_radius + 1):
                    add(self.current_index + offset)
                    if offset:
                        add(self.current_index - offset)

            return pages

        if self.two_page_mode:
            left, right = self.get_current_spread_pages_for_index(self.current_index)
            add(left)
            add(right)
            logical_indices = self.logical_indices()
            try:
                current_pos = logical_indices.index(self.current_index)
            except ValueError:
                current_pos = 0

            if current_pos > 0:
                left, right = self.get_current_spread_pages_for_index(logical_indices[current_pos - 1])
                add(left)
                add(right)

            if current_pos < len(logical_indices) - 1:
                left, right = self.get_current_spread_pages_for_index(logical_indices[current_pos + 1])
                add(left)
                add(right)
            return pages

        add(self.current_index)
        add(self.current_index - 1)
        add(self.current_index + 1)
        return pages

    def start_parallel_render(self, zoom, generation):
        pages = self.get_parallel_render_pages()

        if self.continuous_mode:
            for priority, page_index in enumerate(pages):
                self.enqueue_page_render(
                    page_index,
                    self.get_render_zoom_for_page(page_index, zoom),
                    generation,
                    priority,
                )
            return

        visible_pages = self.get_visible_priority_pages()
        visible_count = len(visible_pages)

        for priority, page_index in enumerate(pages[:visible_count]):
            self.enqueue_page_render(
                page_index,
                self.get_render_zoom_for_page(page_index, zoom),
                generation,
                priority,
            )

        self.deferred_parallel_pages = pages[visible_count:]
        self.deferred_parallel_index = 0
        self.deferred_parallel_generation = generation
        self.deferred_parallel_zoom = zoom

        if self.deferred_parallel_pages:
            self.deferred_parallel_timer.start()
        else:
            self.deferred_parallel_timer.stop()

    def process_deferred_parallel_render(self):
        if not self.doc or self.deferred_parallel_generation != self.render_generation:
            self.deferred_parallel_timer.stop()
            return

        processed_pages = 0
        chunk_size = 1
        base_priority = len(self.get_visible_priority_pages())

        while self.deferred_parallel_index < len(self.deferred_parallel_pages):
            page_index = self.deferred_parallel_pages[self.deferred_parallel_index]
            priority = base_priority + self.deferred_parallel_index
            self.deferred_parallel_index += 1
            self.enqueue_page_render(
                page_index,
                self.get_render_zoom_for_page(page_index, self.deferred_parallel_zoom),
                self.deferred_parallel_generation,
                priority,
            )
            processed_pages += 1

            if processed_pages >= chunk_size:
                return

        self.deferred_parallel_timer.stop()

    def get_render_zoom_for_page(self, page_index, default_zoom):
        if not self.doc or self.continuous_mode or not self.fit_mode:
            return default_zoom

        if self.two_page_mode:
            logical_index = self.logical_index_for_page(page_index)
            left_index, right_index = self.get_current_spread_pages_for_index(logical_index)
            return self.get_spread_fit_zoom(left_index, right_index)

        return self.get_single_fit_zoom(page_index)

    def get_parallel_render_pages(self):
        if not self.doc:
            return []

        visible_pages = self.get_visible_priority_pages()
        if self.continuous_mode:
            return visible_pages

        pages = []
        seen = set()

        for page_index in visible_pages:
            if page_index not in seen:
                seen.add(page_index)
                pages.append(page_index)

        for page_index in range(len(self.doc)):
            if page_index not in seen:
                seen.add(page_index)
                pages.append(page_index)

        return pages

    def get_fallback_render_pages(self):
        if not self.doc:
            return []

        if self.continuous_mode:
            return list(range(len(self.doc)))

        return self.get_visible_priority_pages()

    def start_fallback_render(self, zoom, generation):
        page_source = self.get_fallback_render_pages()

        fallback_pages = []
        for page_index in page_source:
            if self.get_cached_base_pixmap(page_index, zoom) is None:
                fallback_pages.append((generation, page_index, zoom))

        self.fallback_render_pages = fallback_pages
        self.fallback_render_index = 0
        self.fallback_render_generation = generation

        if self.fallback_render_pages and not self.fallback_render_timer.isActive():
            self.fallback_render_timer.start()
        elif not self.fallback_render_pages:
            self.fallback_render_timer.stop()

    def process_fallback_render(self):
        if not self.doc:
            self.fallback_render_timer.stop()
            return

        if self.fallback_render_generation != self.render_generation:
            self.fallback_render_timer.stop()
            return

        processed_pages = 0
        chunk_size = 1 if self.continuous_mode else 1

        while self.fallback_render_index < len(self.fallback_render_pages):
            generation, page_index, zoom = self.fallback_render_pages[self.fallback_render_index]
            self.fallback_render_index += 1

            if generation != self.render_generation:
                continue

            if self.get_cached_base_pixmap(page_index, zoom) is not None:
                continue

            pixmap = self.page_to_pixmap(page_index, zoom)
            self.set_cached_base_pixmap(page_index, zoom, pixmap)

            label = self.page_label_lookup.get(page_index)
            if label is not None:
                label.setText("")
                label.setStyleSheet("")
                label.setPixmap(pixmap)
                label.setFixedSize(pixmap.size())

            processed_pages += 1
            if processed_pages >= chunk_size:
                return

        self.fallback_render_timer.stop()

    def on_render_progress_tick(self):
        if not self.doc:
            return

        if self.fallback_render_index < len(self.fallback_render_pages):
            self.process_fallback_render()

    def render_page_to_label_immediately(self, page_index, zoom):
        label = self.page_label_lookup.get(page_index)
        if label is None:
            return

        pixmap = self.get_display_pixmap(page_index, zoom)
        if pixmap is None:
            pixmap = self.page_to_pixmap(page_index, zoom)
            self.set_cached_base_pixmap(page_index, zoom, pixmap)

        label.setText("")
        label.setStyleSheet("")
        label.setPixmap(pixmap)
        label.setFixedSize(pixmap.size())

    def apply_cached_pixmap_to_label(self, label, page_index, zoom):
        cached_pixmap = self.get_display_pixmap(page_index, zoom)
        if cached_pixmap is None:
            return False

        label.setText("")
        label.setStyleSheet("")
        label.setPixmap(cached_pixmap)
        label.setFixedSize(cached_pixmap.size())
        return True

    def render_initial_visible_pages(self, zoom):
        if not self.doc:
            return

        if self.continuous_mode:
            initial_count = 8 if self.two_page_mode else 6
            for page_index in self.get_visible_priority_pages()[:initial_count]:
                self.render_page_to_label_immediately(page_index, zoom)
            return

        for page_index in self.get_visible_priority_pages()[:2 if self.two_page_mode else 1]:
            self.render_page_to_label_immediately(page_index, zoom)

    def start_render_workers(self):
        for worker_index in range(self.render_thread_count):
            worker = threading.Thread(
                target=self.render_worker_loop,
                name=f"pdf-render-{worker_index}",
                daemon=True,
            )
            worker.start()
            self.render_workers.append(worker)

    def enqueue_page_render(self, page_index, zoom, generation, priority):
        render_key = (generation, page_index, round(zoom, 4))
        try:
            if not self.file_path:
                return

            with self.render_queue_lock:
                if (
                    render_key in self.active_render_jobs
                    or render_key in self.queued_render_jobs
                    or self.get_cached_base_pixmap(page_index, zoom) is not None
                ):
                    return

                self.queued_render_jobs.add(render_key)
                self.render_request_sequence += 1
                sequence = self.render_request_sequence

            self.render_task_queue.put(
                (-generation, priority, sequence, self.file_path, page_index, zoom)
            )
        except RuntimeError:
            return

    def render_worker_loop(self):
        while not self.stop_render_workers:
            try:
                generation_key, priority, sequence, file_path, page_index, zoom = (
                    self.render_task_queue.get(timeout=0.1)
                )
            except Empty:
                continue

            generation = -generation_key
            render_key = (generation, page_index, round(zoom, 4))

            with self.render_queue_lock:
                self.queued_render_jobs.discard(render_key)
                should_skip = (
                    self.stop_render_workers
                    or generation != self.render_generation
                    or file_path != self.file_path
                    or self.get_cached_base_pixmap(page_index, zoom) is not None
                )

                if not should_skip:
                    self.active_render_jobs.add(render_key)

            if should_skip:
                self.render_task_queue.task_done()
                continue

            try:
                samples, width, height, stride = render_page_bytes(file_path, page_index, zoom)
            except Exception as exc:
                self.render_signals.page_failed.emit(generation, page_index, str(exc))
            else:
                self.render_signals.page_rendered.emit(
                    generation,
                    page_index,
                    zoom,
                    samples,
                    width,
                    height,
                    stride,
                )
            finally:
                self.render_task_queue.task_done()

    def on_page_rendered(self, generation, page_index, zoom, samples, width, height, stride):
        self.active_render_jobs.discard((generation, page_index, round(zoom, 4)))
        pixmap = self.build_pixmap_from_bytes(samples, width, height, stride)
        self.set_cached_base_pixmap(page_index, zoom, pixmap)

        if generation != self.render_generation:
            return

        label = self.page_label_lookup.get(page_index)
        if label is None:
            return

        pixmap = self.apply_search_highlights(pixmap, page_index, zoom)
        label.setText("")
        label.setStyleSheet("")
        label.setPixmap(pixmap)
        label.setFixedSize(pixmap.size())

    def on_page_render_failed(self, generation, page_index, message):
        active_key = next(
            (
                key for key in self.active_render_jobs
                if key[0] == generation and key[1] == page_index
            ),
            None,
        )
        if active_key is not None:
            self.active_render_jobs.discard(active_key)
        if generation != self.render_generation:
            return

        label = self.page_label_lookup.get(page_index)
        if label is None:
            return

        label.setText(f"Render failed\n{message}")

    def render_single_page(self, page_index, zoom):
        label = self.make_placeholder_page_label(page_index, zoom)
        self.apply_cached_pixmap_to_label(label, page_index, zoom)
        self.page_layout.addWidget(label, 0, Qt.AlignHCenter)

    def render_spread(self, left_index, right_index, zoom):
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(0)
        row_layout.setAlignment(Qt.AlignCenter)

        left_label = self.make_placeholder_page_label(left_index, zoom)
        self.apply_cached_pixmap_to_label(left_label, left_index, zoom)
        row_layout.addWidget(left_label)

        if right_index is not None and right_index < len(self.doc):
            right_label = self.make_placeholder_page_label(right_index, zoom)
            self.apply_cached_pixmap_to_label(right_label, right_index, zoom)
            row_layout.addWidget(right_label)

        self.page_layout.addWidget(row, 0, Qt.AlignHCenter)

    def render_continuous(self, zoom):
        total = len(self.doc)

        if not self.two_page_mode:
            for i in range(total):
                self.render_single_page(i, zoom)
            return

        if self.cover_mode and total > 0:
            self.render_single_page(0, zoom)
            i = 1
            while i < total:
                right = i + 1 if i + 1 < total else None
                self.render_spread(i, right, zoom)
                i += 2
            return

        i = 0
        while i < total:
            right = i + 1 if i + 1 < total else None
            self.render_spread(i, right, zoom)
            i += 2

    def render_non_continuous(self, zoom):
        if self.two_page_mode:
            left, right = self.get_current_spread_pages_for_index(self.current_index)
            self.render_spread(left, right, zoom)
            text = f"{left + 1}/{len(self.doc)}"
        else:
            self.render_single_page(self.current_index, zoom)
            text = f"{self.current_index + 1}/{len(self.doc)}"

        self.status_label.setText(self.build_status_text(text, zoom))

    def build_status_text(self, page_text, zoom):
        mode_text = "Continuous" if self.continuous_mode else "Single"
        search_text = ""

        if self.search_input.text().strip():
            search_text = f"\nMatches: {len(self.search_result_pages)}"

        return f"{page_text}\nZoom: {zoom:.2f}x{search_text}"

    def get_most_visible_page_in_continuous(self):
        if not self.doc or not self.page_labels:
            return self.current_index

        viewport_top = self.scroll_area.verticalScrollBar().value()
        viewport_bottom = viewport_top + self.scroll_area.viewport().height()

        best_page = self.current_index
        best_visible_height = -1

        for label in self.page_labels:
            top = label.mapTo(self.page_container, label.rect().topLeft()).y()
            bottom = top + label.height()

            visible_top = max(top, viewport_top)
            visible_bottom = min(bottom, viewport_bottom)
            visible_height = max(0, visible_bottom - visible_top)

            if visible_height > best_visible_height:
                best_visible_height = visible_height
                best_page = label.page_index

        return best_page

    def scroll_to_current_page_in_continuous(self):
        if not self.page_labels:
            return

        target_page = self.continuous_restore_page_index

        if self.two_page_mode:
            target_page, _ = self.get_current_spread_pages_for_index(target_page)

        target_label = None
        for label in self.page_labels:
            if getattr(label, "page_index", -1) == target_page:
                target_label = label
                break

        if target_label is not None:
            target_value = self.get_centered_scroll_value_for_label(target_label)
            if target_value is None:
                return

            scroll_bar = self.scroll_area.verticalScrollBar()
            scroll_bar.setValue(target_value)
            self.current_index = target_page

            restore_ready = (
                target_page == 0
                or target_value > scroll_bar.minimum()
                or scroll_bar.maximum() > scroll_bar.minimum()
            )
            if restore_ready:
                self.pending_continuous_scroll_restore = False

    def schedule_continuous_scroll_restore(self):
        if not self.doc or not self.continuous_mode:
            return

        self.pending_continuous_scroll_restore = True
        self.continuous_restore_page_index = self.current_index
        QTimer.singleShot(0, self.scroll_to_current_page_in_continuous)

    def center_page_label_in_view(self, label):
        target_value = self.get_centered_scroll_value_for_label(label)
        if target_value is not None:
            self.scroll_area.verticalScrollBar().setValue(target_value)

    def scroll_to_page_in_continuous(self, page_index):
        if not self.continuous_mode or not self.page_labels:
            return False

        target_page = page_index

        if self.two_page_mode:
            target_page = self.logical_index_for_page(page_index)

        for label in self.page_labels:
            if getattr(label, "page_index", -1) == target_page:
                self.center_page_label_in_view(label)
                self.current_index = target_page
                self.update_slider_range()
                return True

        return False

    def update_slider_range(self):
        if not self.doc:
            self.updating_slider = True
            self.nav_slider.setEnabled(False)
            self.nav_slider.setMinimum(0)
            self.nav_slider.setMaximum(0)
            self.nav_slider.setValue(0)
            self.updating_slider = False
            return

        self.updating_slider = True

        if self.continuous_mode:
            sb = self.scroll_area.verticalScrollBar()
            self.nav_slider.setEnabled(True)
            self.nav_slider.setMinimum(sb.minimum())
            self.nav_slider.setMaximum(sb.maximum())
            self.nav_slider.setValue(sb.value())
        else:
            indices = self.logical_indices()
            self.nav_slider.setEnabled(True)
            self.nav_slider.setMinimum(0)
            self.nav_slider.setMaximum(max(0, len(indices) - 1))

            try:
                pos = indices.index(self.current_index)
            except ValueError:
                pos = 0

            self.nav_slider.setValue(pos)

        self.updating_slider = False

    def on_slider_changed(self, value):
        if self.updating_slider or not self.doc:
            return

        if self.continuous_mode:
            sb = self.scroll_area.verticalScrollBar()
            sb.setValue(value)
        else:
            self.remember_single_page_scroll_position()
            indices = self.logical_indices()
            if not indices:
                return

            value = max(0, min(value, len(indices) - 1))
            new_index = indices[value]

            if new_index != self.current_index:
                self.current_index = new_index
                self.render_view()

    def on_view_scrolled(self, value):
        if (
            self.updating_slider
            or not self.doc
            or not self.continuous_mode
            or self.pending_continuous_scroll_restore
        ):
            return

        self.current_index = self.get_most_visible_page_in_continuous()

        self.updating_slider = True
        sb = self.scroll_area.verticalScrollBar()
        self.nav_slider.setMinimum(sb.minimum())
        self.nav_slider.setMaximum(sb.maximum())
        self.nav_slider.setValue(value)
        self.updating_slider = False

        zoom = self.get_current_zoom() if self.fit_mode else self.zoom
        self.status_label.setText(
            self.build_status_text(f"{self.current_index + 1}/{len(self.doc)}", zoom)
        )
        self.render_initial_visible_pages(zoom)
        self.start_parallel_render(zoom, self.render_generation)

    def render_view(self):
        if not self.doc:
            return

        self.render_generation += 1
        generation = self.render_generation
        self.normalize_current_index()
        self.page_labels = []
        self.page_label_lookup = {}
        with self.render_queue_lock:
            self.active_render_jobs = set()
            self.queued_render_jobs = set()
            self.render_queue = deque()
        self.fallback_render_pages = []
        self.fallback_render_index = 0
        self.fallback_render_generation = generation
        self.deferred_parallel_pages = []
        self.deferred_parallel_index = 0
        self.deferred_parallel_generation = generation
        self.deferred_parallel_timer.stop()
        self.fallback_render_timer.stop()
        self.clear_layout(self.page_layout)

        zoom = self.get_current_zoom()

        if self.continuous_mode:
            self.continuous_restore_page_index = self.current_index
            self.render_continuous(zoom)
            self.render_initial_visible_pages(zoom)
            self.status_label.setText(
                self.build_status_text(f"{self.current_index + 1}/{len(self.doc)}", zoom)
            )
            self.schedule_continuous_scroll_restore()
            QTimer.singleShot(60, self.update_slider_range)
        else:
            self.render_non_continuous(zoom)
            self.render_initial_visible_pages(zoom)
            self.schedule_single_page_scroll_restore()
            self.update_slider_range()

        self.start_parallel_render(zoom, generation)
        self.start_fallback_render(zoom, generation)
        self.update_buttons()

    def update_buttons(self):
        self.single_cont_button.setText(
            "Single-scroll" if self.continuous_mode else "Continuous"
        )
        self.two_page_button.setText(
            "Two pages" if not self.two_page_mode else "Single page"
        )
        self.cover_button.setText(
            "Covermode" if not self.cover_mode else "No cover"
        )

    def zoom_in(self):
        if not self.doc:
            return

        if self.continuous_mode:
            self.current_index = self.get_most_visible_page_in_continuous()
        else:
            self.remember_single_page_scroll_position()
    
        base_zoom = self.get_current_zoom() if self.fit_mode else self.zoom
        self.fit_mode = False
        self.zoom = base_zoom * 1.1
        self.render_view()
    
    def zoom_out(self):
        if not self.doc:
            return

        if self.continuous_mode:
            self.current_index = self.get_most_visible_page_in_continuous()
        else:
            self.remember_single_page_scroll_position()
    
        base_zoom = self.get_current_zoom() if self.fit_mode else self.zoom
        self.fit_mode = False
        self.zoom = base_zoom / 1.1
        self.render_view()

    def fit_to_window(self):
        if not self.doc:
            return

        if self.continuous_mode:
            self.current_index = self.get_most_visible_page_in_continuous()
        else:
            self.remember_single_page_scroll_position()
        self.fit_mode = True
        self.render_view()

    def toggle_continuous_mode(self):
        if not self.doc:
            return

        if self.continuous_mode:
            self.current_index = self.get_most_visible_page_in_continuous()
            self.continuous_mode = False
            self.normalize_current_index()
            self.render_view()
        else:
            self.remember_single_page_scroll_position()
            self.continuous_mode = True
            self.normalize_current_index()
            self.render_view()

    def toggle_two_page_mode(self):
        if not self.doc:
            return
        if not self.continuous_mode:
            self.remember_single_page_scroll_position()
        self.two_page_mode = not self.two_page_mode
        self.normalize_current_index()
        self.render_view()

    def toggle_cover_mode(self):
        if not self.doc:
            return
        if not self.continuous_mode:
            self.remember_single_page_scroll_position()
        self.cover_mode = not self.cover_mode
        self.normalize_current_index()
        self.render_view()

    def toggle_fullscreen(self):        
        if self.doc and self.continuous_mode:
            self.current_index = self.get_most_visible_page_in_continuous()
            self.fit_mode = False

        if self.isFullScreen():
            target_state = self.windowState() & ~Qt.WindowFullScreen
            if self.was_maximized_before_fullscreen:
                target_state |= Qt.WindowMaximized
            else:
                target_state &= ~Qt.WindowMaximized
            self.setWindowState(target_state)
            self.show()
            self.was_maximized_before_fullscreen = False
            return

        self.was_maximized_before_fullscreen = self.isMaximized()
        self.showFullScreen()

    def handle_delayed_resize(self):
        if not self.doc or not self.fit_mode:
            return

        self.render_view()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.doc and self.fit_mode:
            if self.continuous_mode:
                self.current_index = self.get_most_visible_page_in_continuous()
                self.resize_render_timer.start(120)
                return

            self.remember_single_page_scroll_position()
            self.render_view()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_F3:
            self.jump_to_search_result(
                forward=not bool(event.modifiers() & Qt.ShiftModifier)
            )
            event.accept()
            return

        super().keyPressEvent(event)

    def closeEvent(self, event):
        self.render_generation += 1
        self.stop_render_workers = True
        self.deferred_parallel_timer.stop()
        self.fallback_render_timer.stop()
        self.render_progress_timer.stop()
        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    viewer = PDFViewer()

    if len(sys.argv) > 1:
        viewer.load_pdf(sys.argv[1])

    viewer.showMaximized()
    sys.exit(app.exec())