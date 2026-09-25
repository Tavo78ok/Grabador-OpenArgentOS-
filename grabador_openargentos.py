#!/usr/bin/env python3
"""
Grabador de pantalla para OpenArgentOS (GTK4 + libadwaita).

Características:
- Captura de pantalla y grabación de video con ffmpeg (x11grab)
- Selector de tema (Sistema / Claro / Oscuro)
- Icono en la bandeja del sistema (Ayatana / AppIndicator / StatusNotifierItem)
- Controles multimedia vía MPRIS (aparecen en el panel de medios)
"""

import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib, Gtk


# ---------------------------------------------------------------------------
# Detección de backends de bandeja
# ---------------------------------------------------------------------------

def _try_import_indicator():
    """Intenta cargar AyatanaAppIndicator3 o AppIndicator3. Devuelve (module, name) o (None, None)."""
    for mod_name, ver in (
        ("AyatanaAppIndicator3", "0.1"),
        ("AppIndicator3", "0.1"),
    ):
        try:
            gi.require_version(mod_name, ver)
            mod = getattr(__import__("gi.repository", fromlist=[mod_name]), mod_name)
            return mod, mod_name
        except (ValueError, ImportError, AttributeError):
            continue
    return None, None


IndicatorModule, IndicatorBackendName = _try_import_indicator()


# ---------------------------------------------------------------------------
# Bandeja unificada (Ayatana / AppIndicator / StatusNotifierItem)
# ---------------------------------------------------------------------------

class TrayIcon:
    """
    Icono de bandeja orientado a GTK4 + Cinnamon/KDE/XFCE.

    Prioridad:
      1. StatusNotifierItem (D-Bus) — compatible con Cinnamon, KDE, XFCE…
      2. Ayatana/AppIndicator solo si el GIR está instalado y no rompe GTK4

    Clic en el icono → callback on_activate (menú de controles / mostrar ventana).
    """

    def __init__(self, app_id, title, icon_name, on_activate=None):
        self.app_id = app_id
        self.title = title
        self.icon_name = icon_name
        self.on_activate = on_activate
        self._backend = None
        self._indicator = None
        self._sni = None
        self._registered = False

    @property
    def active(self):
        # Releer estado del SNI por si el registro terminó después del start()
        if self._sni is not None and self._sni.registered:
            self._registered = True
        return self._registered

    @property
    def backend_name(self):
        return self._backend or "ninguno"

    def start(self):
        # En GTK4 preferimos SNI: Ayatana depende de GTK3 y suele fallar o
        # no ofrecer menú usable desde una app GTK4.
        if self._start_sni():
            return True
        if IndicatorModule is not None:
            return self._start_appindicator()
        return False

    def stop(self):
        if self._sni:
            self._sni.stop()
            self._sni = None
        self._indicator = None
        self._registered = False

    def set_recording(self, recording: bool, tooltip: str = ""):
        if recording:
            icon = "media-record"
            status_tooltip = tooltip or "Grabando pantalla…"
            sni_status = "NeedsAttention"
        else:
            icon = self.icon_name
            status_tooltip = tooltip or "Listo para grabar"
            sni_status = "Active"

        if self._indicator is not None:
            try:
                self._indicator.set_icon(icon)
                self._indicator.set_title(status_tooltip)
                cat = (
                    IndicatorModule.IndicatorStatus.ATTENTION
                    if recording
                    else IndicatorModule.IndicatorStatus.ACTIVE
                )
                self._indicator.set_status(cat)
            except Exception:
                pass

        if self._sni is not None:
            self._sni.set_icon(icon)
            self._sni.set_status(sni_status, status_tooltip)

    def _start_appindicator(self):
        try:
            ind = IndicatorModule.Indicator.new(
                self.app_id,
                self.icon_name,
                IndicatorModule.IndicatorCategory.APPLICATION_STATUS,
            )
            ind.set_status(IndicatorModule.IndicatorStatus.ACTIVE)
            ind.set_title(self.title)
            ind.connect("connection-changed", self._on_indicator_connection)
            self._indicator = ind
            self._backend = IndicatorBackendName or "appindicator"
            self._registered = True
            return True
        except Exception:
            self._indicator = None
            return False

    def _on_indicator_connection(self, indicator, connected):
        self._registered = bool(connected)

    def _start_sni(self):
        self._sni = _StatusNotifierItem(
            app_id=self.app_id,
            title=self.title,
            icon_name=self.icon_name,
            on_activate=self.on_activate,
        )
        ok = self._sni.start()
        if ok:
            self._backend = "sni"
            # El registro real es asíncrono; marcamos pendiente y se
            # actualizará solo cuando el watcher responda.
            self._registered = self._sni.registered
        return ok


class _StatusNotifierItem:
    """Implementación de org.kde.StatusNotifierItem por D-Bus."""

    SNI_IFACE = "org.kde.StatusNotifierItem"
    WATCHERS = (
        ("org.kde.StatusNotifierWatcher", "/StatusNotifierWatcher", "org.kde.StatusNotifierWatcher"),
        ("org.freedesktop.StatusNotifierWatcher", "/StatusNotifierWatcher", "org.freedesktop.StatusNotifierWatcher"),
    )

    def __init__(self, app_id, title, icon_name, on_activate=None):
        self.app_id = app_id
        self.title = title
        self.icon_name = icon_name
        self.status = "Active"
        self.tooltip_title = title
        self.tooltip_body = ""
        self.on_activate = on_activate
        self.registered = False
        self._bus = None
        self._owner_id = 0
        self._bus_name = ""

        self._xml = f"""
        <node>
          <interface name="{self.SNI_IFACE}">
            <property name="Category" type="s" access="read"/>
            <property name="Id" type="s" access="read"/>
            <property name="Title" type="s" access="read"/>
            <property name="Status" type="s" access="read"/>
            <property name="WindowId" type="i" access="read"/>
            <property name="IconName" type="s" access="read"/>
            <property name="IconThemePath" type="s" access="read"/>
            <property name="OverlayIconName" type="s" access="read"/>
            <property name="AttentionIconName" type="s" access="read"/>
            <property name="AttentionMovieName" type="s" access="read"/>
            <property name="ToolTip" type="(sa(iiay)ss)" access="read"/>
            <property name="ItemIsMenu" type="b" access="read"/>
            <property name="Menu" type="o" access="read"/>
            <method name="ContextMenu">
              <arg direction="in" type="i" name="x"/>
              <arg direction="in" type="i" name="y"/>
            </method>
            <method name="Activate">
              <arg direction="in" type="i" name="x"/>
              <arg direction="in" type="i" name="y"/>
            </method>
            <method name="SecondaryActivate">
              <arg direction="in" type="i" name="x"/>
              <arg direction="in" type="i" name="y"/>
            </method>
            <method name="Scroll">
              <arg direction="in" type="i" name="delta"/>
              <arg direction="in" type="s" name="orientation"/>
            </method>
            <signal name="NewTitle"/>
            <signal name="NewIcon"/>
            <signal name="NewAttentionIcon"/>
            <signal name="NewOverlayIcon"/>
            <signal name="NewToolTip"/>
            <signal name="NewStatus">
              <arg type="s" name="status"/>
            </signal>
          </interface>
        </node>
        """

    def start(self):
        try:
            self._bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        except Exception:
            return False

        self._bus_name = f"org.kde.StatusNotifierItem-{os.getpid()}-1"
        self._owner_id = Gio.bus_own_name_on_connection(
            self._bus,
            self._bus_name,
            Gio.BusNameOwnerFlags.NONE,
            self._on_name_acquired,
            self._on_name_lost,
        )
        return True

    def stop(self):
        if self._owner_id:
            Gio.bus_unown_name(self._owner_id)
            self._owner_id = 0
        self.registered = False

    def set_status(self, status, tooltip_body=""):
        self.status = status
        self.tooltip_body = tooltip_body
        self._emit("NewStatus", GLib.Variant("(s)", (status,)))
        self._emit("NewToolTip", None)

    def set_icon(self, icon_name):
        self.icon_name = icon_name
        self._emit("NewIcon", None)
        self._emit("NewAttentionIcon", None)

    def _emit(self, signal_name, params):
        if not self.registered or not self._bus:
            return
        try:
            self._bus.emit_signal(
                None, "/StatusNotifierItem", self.SNI_IFACE, signal_name, params
            )
        except Exception:
            pass

    def _on_name_acquired(self, connection, name):
        node_info = Gio.DBusNodeInfo.new_for_xml(self._xml)
        connection.register_object(
            "/StatusNotifierItem",
            node_info.interfaces[0],
            self._handle_method,
            self._handle_get_property,
            None,
        )
        # Consideramos el servicio publicado aunque el watcher aún no
        # confirme: Cinnamon a veces descubre el ítem por NameOwnerChanged.
        self.registered = True

        # Probar ambos watchers (KDE / freedesktop) con varios formatos
        for dest, path, iface in self.WATCHERS:
            try:
                proxy = Gio.DBusProxy.new_sync(
                    connection,
                    Gio.DBusProxyFlags.NONE,
                    None,
                    dest,
                    path,
                    iface,
                    None,
                )
                for arg in (
                    name,
                    f"{name}/StatusNotifierItem",
                    "/StatusNotifierItem",
                ):
                    try:
                        proxy.call_sync(
                            "RegisterStatusNotifierItem",
                            GLib.Variant("(s)", (arg,)),
                            Gio.DBusCallFlags.NONE,
                            2000,
                            None,
                        )
                        return
                    except Exception:
                        continue
            except Exception:
                continue

    def _on_name_lost(self, connection, name):
        self.registered = False

    def _handle_method(self, connection, sender, path, interface, method, params, invocation):
        if method in ("Activate", "SecondaryActivate", "ContextMenu"):
            if self.on_activate:
                GLib.idle_add(self.on_activate)
            invocation.return_value(None)
        elif method == "Scroll":
            invocation.return_value(None)
        else:
            invocation.return_error_literal(
                Gio.DBusError.UNKNOWN_METHOD,
                Gio.DBusError.UNKNOWN_METHOD,
                f"Unknown method {method}",
            )

    def _handle_get_property(self, connection, sender, path, interface, prop):
        props = {
            "Category": GLib.Variant("s", "ApplicationStatus"),
            "Id": GLib.Variant("s", self.app_id),
            "Title": GLib.Variant("s", self.title),
            "Status": GLib.Variant("s", self.status),
            "WindowId": GLib.Variant("i", 0),
            "IconName": GLib.Variant("s", self.icon_name),
            "IconThemePath": GLib.Variant("s", ""),
            "OverlayIconName": GLib.Variant("s", ""),
            "AttentionIconName": GLib.Variant("s", "media-record"),
            "AttentionMovieName": GLib.Variant("s", ""),
            "ToolTip": GLib.Variant(
                "(sa(iiay)ss)",
                (self.icon_name, [], self.tooltip_title, self.tooltip_body),
            ),
            "ItemIsMenu": GLib.Variant("b", False),
            "Menu": GLib.Variant("o", "/MenuBar"),
        }
        return props.get(prop)


# ---------------------------------------------------------------------------
# MPRIS2 (controles multimedia del panel)
# ---------------------------------------------------------------------------

class MprisServer:
    BUS_NAME = "org.mpris.MediaPlayer2.OpenArgentOSRecorder"
    OBJECT_PATH = "/org/mpris/MediaPlayer2"

    def __init__(self, on_play=None, on_pause=None, on_stop=None, on_raise=None):
        self._on_play = on_play
        self._on_pause = on_pause
        self._on_stop = on_stop
        self._on_raise = on_raise
        self._playback_status = "Stopped"
        self._connection = None
        self._owner_id = 0
        self._xml = """
        <node>
          <interface name="org.mpris.MediaPlayer2">
            <method name="Raise"/>
            <method name="Quit"/>
            <property name="CanQuit" type="b" access="read"/>
            <property name="CanRaise" type="b" access="read"/>
            <property name="HasTrackList" type="b" access="read"/>
            <property name="Identity" type="s" access="read"/>
            <property name="DesktopEntry" type="s" access="read"/>
            <property name="SupportedUriSchemes" type="as" access="read"/>
            <property name="SupportedMimeTypes" type="as" access="read"/>
          </interface>
          <interface name="org.mpris.MediaPlayer2.Player">
            <method name="Next"/>
            <method name="Previous"/>
            <method name="Pause"/>
            <method name="PlayPause"/>
            <method name="Stop"/>
            <method name="Play"/>
            <method name="Seek"><arg direction="in" type="x" name="Offset"/></method>
            <method name="SetPosition">
              <arg direction="in" type="o" name="TrackId"/>
              <arg direction="in" type="x" name="Position"/>
            </method>
            <method name="OpenUri"><arg direction="in" type="s" name="Uri"/></method>
            <property name="PlaybackStatus" type="s" access="read"/>
            <property name="LoopStatus" type="s" access="readwrite"/>
            <property name="Rate" type="d" access="readwrite"/>
            <property name="Shuffle" type="b" access="readwrite"/>
            <property name="Metadata" type="a{sv}" access="read"/>
            <property name="Volume" type="d" access="readwrite"/>
            <property name="Position" type="x" access="read"/>
            <property name="MinimumRate" type="d" access="read"/>
            <property name="MaximumRate" type="d" access="read"/>
            <property name="CanGoNext" type="b" access="read"/>
            <property name="CanGoPrevious" type="b" access="read"/>
            <property name="CanPlay" type="b" access="read"/>
            <property name="CanPause" type="b" access="read"/>
            <property name="CanSeek" type="b" access="read"/>
            <property name="CanControl" type="b" access="read"/>
            <signal name="Seeked"><arg name="Position" type="x"/></signal>
          </interface>
        </node>
        """

    def start(self):
        try:
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        except Exception:
            return False
        self._owner_id = Gio.bus_own_name_on_connection(
            bus, self.BUS_NAME, Gio.BusNameOwnerFlags.NONE,
            self._on_name_acquired, None,
        )
        return True

    def stop(self):
        if self._owner_id:
            Gio.bus_unown_name(self._owner_id)
            self._owner_id = 0

    def set_playback_status(self, status):
        if status == self._playback_status:
            return
        self._playback_status = status
        if not self._connection:
            return
        try:
            self._connection.emit_signal(
                None, self.OBJECT_PATH,
                "org.freedesktop.DBus.Properties", "PropertiesChanged",
                GLib.Variant("(sa{sv}as)", (
                    "org.mpris.MediaPlayer2.Player",
                    {
                        "PlaybackStatus": GLib.Variant("s", status),
                        "Metadata": self._metadata_variant(),
                    },
                    [],
                )),
            )
        except Exception:
            pass

    def _metadata_variant(self):
        return GLib.Variant("a{sv}", {
            "mpris:trackid": GLib.Variant("o", "/org/openargentos/recorder/track/1"),
            "xesam:title": GLib.Variant("s", "Grabación de pantalla"),
            "xesam:artist": GLib.Variant("as", ["OpenArgentOS Grabador"]),
            "xesam:album": GLib.Variant("s", "Grabador OpenArgentOS"),
        })

    def _on_name_acquired(self, connection, name):
        self._connection = connection
        node_info = Gio.DBusNodeInfo.new_for_xml(self._xml)
        for iface in node_info.interfaces:
            connection.register_object(
                self.OBJECT_PATH, iface,
                self._handle_method, self._handle_get_property, self._handle_set_property,
            )

    def _handle_method(self, connection, sender, path, interface, method, params, invocation):
        if interface == "org.mpris.MediaPlayer2":
            if method == "Raise" and self._on_raise:
                GLib.idle_add(self._on_raise)
            invocation.return_value(None)
            return

        if interface == "org.mpris.MediaPlayer2.Player":
            if method == "Play" and self._on_play:
                GLib.idle_add(self._on_play)
            elif method == "Pause" and self._on_pause:
                GLib.idle_add(self._on_pause)
            elif method == "PlayPause":
                if self._playback_status == "Playing":
                    if self._on_pause:
                        GLib.idle_add(self._on_pause)
                else:
                    if self._on_play:
                        GLib.idle_add(self._on_play)
            elif method == "Stop" and self._on_stop:
                GLib.idle_add(self._on_stop)
            invocation.return_value(None)
            return

        invocation.return_error_literal(
            Gio.DBusError.UNKNOWN_METHOD, Gio.DBusError.UNKNOWN_METHOD, method
        )

    def _handle_get_property(self, connection, sender, path, interface, prop):
        if interface == "org.mpris.MediaPlayer2":
            return {
                "CanQuit": GLib.Variant("b", False),
                "CanRaise": GLib.Variant("b", True),
                "HasTrackList": GLib.Variant("b", False),
                "Identity": GLib.Variant("s", "Grabador OpenArgentOS"),
                "DesktopEntry": GLib.Variant("s", "org.openargentos.recorder"),
                "SupportedUriSchemes": GLib.Variant("as", []),
                "SupportedMimeTypes": GLib.Variant("as", []),
            }.get(prop)

        if interface == "org.mpris.MediaPlayer2.Player":
            return {
                "PlaybackStatus": GLib.Variant("s", self._playback_status),
                "LoopStatus": GLib.Variant("s", "None"),
                "Rate": GLib.Variant("d", 1.0),
                "Shuffle": GLib.Variant("b", False),
                "Metadata": self._metadata_variant(),
                "Volume": GLib.Variant("d", 1.0),
                "Position": GLib.Variant("x", 0),
                "MinimumRate": GLib.Variant("d", 1.0),
                "MaximumRate": GLib.Variant("d", 1.0),
                "CanGoNext": GLib.Variant("b", False),
                "CanGoPrevious": GLib.Variant("b", False),
                "CanPlay": GLib.Variant("b", True),
                "CanPause": GLib.Variant("b", True),
                "CanSeek": GLib.Variant("b", False),
                "CanControl": GLib.Variant("b", True),
            }.get(prop)
        return None

    def _handle_set_property(self, connection, sender, path, interface, prop, value):
        return True


# ---------------------------------------------------------------------------
# Aplicación
# ---------------------------------------------------------------------------

class RecorderApp(Adw.Application):
    def __init__(self):
        super().__init__(
            application_id="org.openargentos.recorder",
            flags=Gio.ApplicationFlags.FLAGS_NONE,
        )
        self.main_window = None
        self.tray = None
        self.mpris = None

    def do_startup(self):
        Adw.Application.do_startup(self)
        Gtk.Window.set_default_icon_name("camera-video")

    def do_activate(self):
        if not self.main_window:
            self.main_window = MainWindow(application=self)
            self._setup_tray_and_mpris()
        self.main_window.present()

    def _setup_tray_and_mpris(self):
        win = self.main_window

        self.tray = TrayIcon(
            app_id="org.openargentos.recorder",
            title="Grabador OpenArgentOS",
            icon_name="camera-video",
            on_activate=self._on_tray_activate,
        )
        self.tray.start()

        self.mpris = MprisServer(
            on_play=win._mpris_play,
            on_pause=win._mpris_pause,
            on_stop=win._mpris_stop,
            on_raise=lambda: win.present(),
        )
        self.mpris.start()

        # Dar tiempo al registro asíncrono del SNI (Cinnamon)
        GLib.timeout_add(1500, self._report_tray_status)

    def _report_tray_status(self):
        if not self.main_window:
            return False
        if self.tray and self.tray.active:
            self.main_window.show_toast(
                f"Bandeja OK ({self.tray.backend_name}) — clic en el icono para controles"
            )
        else:
            self.main_window.show_toast(
                "Sin icono de bandeja — al grabar usá el icono de sonido/medios del panel"
            )
        return False

    def _on_tray_activate(self):
        """Clic en el icono de bandeja → menú de controles rápidos."""
        self._show_tray_controls()

    def _show_tray_controls(self):
        win = self.main_window
        if win is None:
            return

        pop = Gtk.Window(
            title="Grabador",
            transient_for=win,
            modal=True,
            resizable=False,
            default_width=260,
        )
        pop.set_hide_on_close(True)

        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=8,
            margin_top=12,
            margin_bottom=12,
            margin_start=12,
            margin_end=12,
        )

        recording = win.recording_process is not None

        lbl = Gtk.Label()
        lbl.set_markup(
            "<b>Grabando…</b>" if recording else "<b>Grabador OpenArgentOS</b>"
        )
        box.append(lbl)

        def add_btn(label, css, callback):
            b = Gtk.Button(label=label)
            if css:
                b.add_css_class(css)
            b.connect(
                "clicked",
                lambda *_: (callback(), pop.close()),
            )
            box.append(b)
            return b

        if recording:
            add_btn("Detener grabación", "destructive-action", win.stop_recording)
        else:
            add_btn("Iniciar grabación", "suggested-action", win._start_countdown)

        add_btn("Capturar pantalla", None, lambda: win.on_take_screenshot(None))
        add_btn(
            "Mostrar ventana",
            None,
            lambda: win.present(),
        )
        add_btn("Ocultar ventana", None, lambda: win.set_visible(False))
        add_btn("Salir", "destructive-action", lambda: self.quit())

        pop.set_child(box)
        pop.present()

    def do_shutdown(self):
        if self.tray:
            self.tray.stop()
        if self.mpris:
            self.mpris.stop()
        Adw.Application.do_shutdown(self)


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.set_title("Grabador OpenArgentOS")
        self.set_default_size(450, 600)
        self.set_icon_name("camera-video")

        self.recording_process = None
        self.output_file = None
        self.start_time = 0
        self.timer_id = None
        self.countdown_id = None
        self.countdown_remaining = 0
        self.snap_countdown_id = None
        self.snap_countdown_remaining = 0
        self._ffmpeg_log = None
        self._stop_watch_id = None
        self._startup_check_id = None
        self.session_type = self._detect_session_type()

        self.videos_dir = self._get_user_dir(
            GLib.UserDirectory.DIRECTORY_VIDEOS, "~/Videos"
        )
        self.pictures_dir = self._get_user_dir(
            GLib.UserDirectory.DIRECTORY_PICTURES, "~/Pictures"
        )
        os.makedirs(self.videos_dir, exist_ok=True)
        os.makedirs(self.pictures_dir, exist_ok=True)

        self.build_ui()
        self.connect("close-request", self.on_close_request)

    @staticmethod
    def _get_user_dir(special_dir, fallback):
        path = GLib.get_user_special_dir(special_dir)
        return path if path else os.path.expanduser(fallback)

    @staticmethod
    def _detect_session_type():
        session = os.environ.get("XDG_SESSION_TYPE", "").strip().lower()
        if session in ("x11", "wayland"):
            return session
        if os.environ.get("WAYLAND_DISPLAY"):
            return "wayland"
        if os.environ.get("DISPLAY"):
            return "x11"
        return "unknown"

    def build_ui(self):
        header_bar = Adw.HeaderBar()
        page = Adw.PreferencesPage()

        # --- Apariencia ---
        appearance_group = Adw.PreferencesGroup(
            title="Apariencia",
            description="Elige el tema de la aplicación",
        )
        self.theme_model = Gtk.StringList.new(["Sistema", "Claro", "Oscuro"])
        self.theme_row = Adw.ComboRow(
            title="Tema",
            subtitle="Claro, oscuro o seguir la preferencia del sistema",
            model=self.theme_model,
        )
        self.theme_row.set_selected(0)
        self.theme_row.connect("notify::selected", self._on_theme_changed)
        appearance_group.add(self.theme_row)

        # --- Captura ---
        snap_group = Adw.PreferencesGroup(
            title="Captura de Pantalla",
            description="Toma una captura en la resolución nativa de tu monitor",
        )
        self.snap_countdown_adjustment = Gtk.Adjustment(
            value=3, lower=0, upper=10, step_increment=1
        )
        self.snap_countdown_row = Adw.SpinRow(
            title="Cuenta regresiva antes de capturar",
            subtitle="Segundos de margen para salir de esta ventana (0 = sin espera)",
            adjustment=self.snap_countdown_adjustment,
        )
        snap_group.add(self.snap_countdown_row)

        snap_row = Adw.ActionRow(title="Capturar Pantalla Completa")
        self.snap_btn = Gtk.Button(label="Capturar")
        self.snap_btn.add_css_class("suggested-action")
        self.snap_btn.set_valign(Gtk.Align.CENTER)
        self.snap_btn.connect("clicked", self.on_snap_button_clicked)
        snap_row.add_suffix(self.snap_btn)
        snap_group.add(snap_row)

        # --- Grabación ---
        rec_group = Adw.PreferencesGroup(
            title="Grabación de Pantalla",
            description="Ajusta el formato y la tasa de refresco antes de grabar",
        )
        self.format_model = Gtk.StringList.new(
            ["MP4 (H.264)", "MKV (H.264)", "WEBM (VP9)"]
        )
        self.format_row = Adw.ComboRow(title="Formato de salida", model=self.format_model)
        self.format_row.set_selected(0)
        rec_group.add(self.format_row)

        self.fps_model = Gtk.StringList.new(
            ["30 FPS (Recomendado)", "60 FPS (Más fluido, más CPU)"]
        )
        self.fps_row = Adw.ComboRow(title="Cuadros por segundo", model=self.fps_model)
        self.fps_row.set_selected(0)
        rec_group.add(self.fps_row)

        self.countdown_adjustment = Gtk.Adjustment(
            value=3, lower=0, upper=10, step_increment=1
        )
        self.countdown_row = Adw.SpinRow(
            title="Cuenta regresiva antes de grabar",
            subtitle="Segundos de margen para salir de esta ventana (0 = sin espera)",
            adjustment=self.countdown_adjustment,
        )
        rec_group.add(self.countdown_row)

        self.status_row = Adw.ActionRow(title="Estado", subtitle="Listo para grabar")
        rec_group.add(self.status_row)

        self.rec_btn = Gtk.Button(label="Iniciar Grabación")
        self.rec_btn.add_css_class("pill")
        self.rec_btn.add_css_class("suggested-action")
        self.rec_btn.set_margin_top(15)
        self.rec_btn.set_margin_bottom(15)
        self.rec_btn.connect("clicked", self.toggle_recording)
        rec_group.add(self.rec_btn)

        page.add(appearance_group)
        page.add(snap_group)
        page.add(rec_group)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.append(header_bar)
        box.append(page)

        self.toast_overlay = Adw.ToastOverlay()
        self.toast_overlay.set_child(box)
        self.set_content(self.toast_overlay)

        self._apply_session_restrictions()
        self._apply_theme(0)

    def _on_theme_changed(self, row, _param):
        self._apply_theme(row.get_selected())

    def _apply_theme(self, index):
        style = Adw.StyleManager.get_default()
        if index == 1:
            style.set_color_scheme(Adw.ColorScheme.FORCE_LIGHT)
        elif index == 2:
            style.set_color_scheme(Adw.ColorScheme.FORCE_DARK)
        else:
            style.set_color_scheme(Adw.ColorScheme.DEFAULT)

    def _apply_session_restrictions(self):
        if self.session_type == "wayland":
            self.snap_btn.set_sensitive(False)
            self.snap_countdown_row.set_sensitive(False)
            self.rec_btn.set_sensitive(False)
            self.countdown_row.set_sensitive(False)
            self.status_row.set_subtitle(
                "Sesión Wayland detectada — captura y grabación aún no disponibles"
            )
        elif self.session_type == "unknown":
            self.status_row.set_subtitle(
                "No se detectó el tipo de sesión (X11/Wayland); puede fallar"
            )

    @staticmethod
    def _ffmpeg_available():
        return shutil.which("ffmpeg") is not None

    def on_snap_button_clicked(self, button):
        if self.snap_countdown_id is not None:
            self._cancel_snap_countdown()
            return
        self._start_snap_countdown()

    def _start_snap_countdown(self):
        if self.session_type == "wayland":
            self.show_toast("Captura no disponible en Wayland todavía.")
            return
        if not self._ffmpeg_available():
            self.show_toast("ffmpeg no está instalado en el sistema.")
            return
        if self.recording_process is not None or self.countdown_id is not None:
            self.show_toast("No se puede capturar mientras se graba o hay cuenta regresiva.")
            return

        seconds = int(self.snap_countdown_adjustment.get_value())
        if seconds <= 0:
            self._do_take_screenshot()
            return

        self.snap_countdown_remaining = seconds
        self.snap_btn.set_label("Cancelar")
        self.snap_btn.remove_css_class("suggested-action")
        self.snap_btn.add_css_class("destructive-action")
        self.snap_countdown_row.set_sensitive(False)
        self.status_row.set_subtitle(
            f"Captura en {self.snap_countdown_remaining}..."
        )
        self.snap_countdown_id = GLib.timeout_add(1000, self._snap_countdown_tick)

    def _snap_countdown_tick(self):
        self.snap_countdown_remaining -= 1
        if self.snap_countdown_remaining <= 0:
            self.snap_countdown_id = None
            self._reset_snap_btn()
            self._do_take_screenshot()
            return False
        self.status_row.set_subtitle(
            f"Captura en {self.snap_countdown_remaining}..."
        )
        return True

    def _reset_snap_btn(self):
        self.snap_btn.set_label("Capturar")
        self.snap_btn.remove_css_class("destructive-action")
        self.snap_btn.add_css_class("suggested-action")
        self.snap_countdown_row.set_sensitive(True)
        if self.recording_process is None and self.countdown_id is None:
            self.status_row.set_subtitle("Listo para grabar")

    def _cancel_snap_countdown(self):
        if self.snap_countdown_id:
            GLib.source_remove(self.snap_countdown_id)
            self.snap_countdown_id = None
        self._reset_snap_btn()
        self.show_toast("Captura cancelada.")

    def on_take_screenshot(self, button):
        # Compatibilidad con el menú de bandeja y llamadas directas.
        self._do_take_screenshot()

    def _do_take_screenshot(self):
        if self.session_type == "wayland":
            self.show_toast("Captura no disponible en Wayland todavía.")
            return
        if not self._ffmpeg_available():
            self.show_toast("ffmpeg no está instalado en el sistema.")
            return

        timestamp = time.strftime("%Y%m%d_%H%M%S")
        output_file = os.path.join(self.pictures_dir, f"captura_{timestamp}.png")
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "x11grab", "-i", os.environ.get("DISPLAY", ":0.0"),
            "-vframes", "1", output_file,
        ]
        try:
            result = subprocess.run(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=10
            )
            if result.returncode != 0:
                lines = result.stderr.decode(errors="ignore").strip().splitlines()
                detail = lines[-1] if lines else "error desconocido"
                self.show_toast(f"Error al capturar: {detail}")
                return
            self.show_toast(f"Captura guardada en Imágenes/captura_{timestamp}.png")
            if self.recording_process is None and self.countdown_id is None:
                self.status_row.set_subtitle("Listo para grabar")
        except subprocess.TimeoutExpired:
            self.show_toast("La captura tardó demasiado y se canceló.")
        except Exception as e:
            self.show_toast(f"Error al capturar: {e}")

    def toggle_recording(self, button):
        if self.recording_process is not None:
            self.stop_recording()
        elif self.countdown_id is not None:
            self._cancel_countdown()
        else:
            self._start_countdown()

    def _start_countdown(self):
        if self.session_type == "wayland":
            self.show_toast("Grabación no disponible en Wayland todavía.")
            return
        if not self._ffmpeg_available():
            self.show_toast("ffmpeg no está instalado en el sistema.")
            return

        seconds = int(self.countdown_adjustment.get_value())
        self.format_row.set_sensitive(False)
        self.fps_row.set_sensitive(False)
        self.countdown_row.set_sensitive(False)

        if seconds <= 0:
            self._begin_capture()
            return

        self.countdown_remaining = seconds
        self.rec_btn.set_label("Cancelar")
        self.rec_btn.remove_css_class("suggested-action")
        self.rec_btn.add_css_class("destructive-action")
        self.status_row.set_subtitle(f"Grabación en {self.countdown_remaining}...")
        self.countdown_id = GLib.timeout_add(1000, self._countdown_tick)

    def _countdown_tick(self):
        self.countdown_remaining -= 1
        if self.countdown_remaining <= 0:
            self.countdown_id = None
            self._begin_capture()
            return False
        self.status_row.set_subtitle(f"Grabación en {self.countdown_remaining}...")
        return True

    def _reset_idle_ui(self, subtitle="Listo para grabar"):
        self.rec_btn.set_label("Iniciar Grabación")
        self.rec_btn.remove_css_class("destructive-action")
        self.rec_btn.add_css_class("suggested-action")
        self.format_row.set_sensitive(True)
        self.fps_row.set_sensitive(True)
        self.countdown_row.set_sensitive(True)
        self.status_row.set_subtitle(subtitle)

    def _cancel_countdown(self):
        if self.countdown_id:
            GLib.source_remove(self.countdown_id)
            self.countdown_id = None
        self._reset_idle_ui()

    def _begin_capture(self):
        fmt_idx = self.format_row.get_selected()
        fps_idx = self.fps_row.get_selected()
        ext = ["mp4", "mkv", "webm"][fmt_idx]
        fps = "30" if fps_idx == 0 else "60"

        timestamp = time.strftime("%Y%m%d_%H%M%S")
        self.output_file = os.path.join(
            self.videos_dir, f"grabacion_{timestamp}.{ext}"
        )
        display = os.environ.get("DISPLAY", ":0.0")
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "warning",
            "-f", "x11grab", "-framerate", fps, "-i", display, "-vsync", "cfr",
        ]
        if ext in ("mp4", "mkv"):
            cmd.extend([
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                "-pix_fmt", "yuv420p", "-threads", "0",
            ])
        else:
            cmd.extend([
                "-c:v", "libvpx-vp9", "-deadline", "realtime", "-cpu-used", "8",
                "-crf", "32", "-b:v", "0", "-row-mt", "1",
            ])
        cmd.append(self.output_file)

        self._ffmpeg_log = tempfile.TemporaryFile(mode="w+b")
        try:
            self.recording_process = subprocess.Popen(
                cmd, stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL, stderr=self._ffmpeg_log,
                start_new_session=True,
            )
        except FileNotFoundError:
            self.show_toast("No se pudo iniciar ffmpeg.")
            self._cleanup_log()
            self._reset_idle_ui()
            return
        except Exception as e:
            self.show_toast(f"Error al lanzar ffmpeg: {e}")
            self._cleanup_log()
            self._reset_idle_ui()
            return

        self.status_row.set_subtitle("Iniciando grabación...")
        self._startup_check_id = GLib.timeout_add(400, self._check_startup_success)

    def _check_startup_success(self):
        self._startup_check_id = None
        if self.recording_process is None:
            return False
        if self.recording_process.poll() is not None:
            detail = self._read_last_log_line()
            self._cleanup_log()
            self.recording_process = None
            self.show_toast(f"No se pudo iniciar la grabación: {detail}")
            self._reset_idle_ui()
            return False

        self.start_time = time.time()
        self.timer_id = GLib.timeout_add(1000, self.update_timer)
        self.rec_btn.set_label("Detener Grabación")
        self.rec_btn.remove_css_class("suggested-action")
        self.rec_btn.add_css_class("destructive-action")
        self.format_row.set_sensitive(False)
        self.fps_row.set_sensitive(False)
        self.status_row.set_subtitle("Grabando... 00:00:00")

        app = self.get_application()
        if app and app.tray:
            app.tray.set_recording(True, "Grabando pantalla…")
        if app and app.mpris:
            app.mpris.set_playback_status("Playing")
        return False

    def stop_recording(self):
        if self._startup_check_id:
            GLib.source_remove(self._startup_check_id)
            self._startup_check_id = None
        if self.timer_id:
            GLib.source_remove(self.timer_id)
            self.timer_id = None

        if not self.recording_process:
            self._cleanup_log()
            self._reset_idle_ui("Grabación finalizada y guardada.")
            self._update_tray_idle()
            return

        try:
            self.recording_process.send_signal(signal.SIGINT)
        except ProcessLookupError:
            pass

        self.status_row.set_subtitle("Finalizando grabación...")
        self.rec_btn.set_sensitive(False)
        self._stop_deadline = time.time() + 6.0
        self._stop_watch_id = GLib.timeout_add(200, self._watch_stop)

    def _watch_stop(self):
        proc = self.recording_process
        if proc is None or proc.poll() is not None:
            self._finish_stop()
            return False
        if time.time() < self._stop_deadline:
            return True
        try:
            proc.terminate()
        except ProcessLookupError:
            self._finish_stop()
            return False
        self._stop_deadline = time.time() + 2.0
        self._stop_watch_id = GLib.timeout_add(200, self._force_kill_watch)
        return False

    def _force_kill_watch(self):
        proc = self.recording_process
        if proc is None or proc.poll() is not None:
            self._finish_stop()
            return False
        if time.time() < self._stop_deadline:
            return True
        try:
            proc.kill()
            proc.wait(timeout=1)
        except Exception:
            pass
        self._finish_stop()
        return False

    def _finish_stop(self):
        self.recording_process = None
        self._cleanup_log()
        self.rec_btn.set_sensitive(True)
        self._reset_idle_ui("Grabación finalizada y guardada.")
        self._update_tray_idle()
        if self.output_file:
            self.show_toast(f"Video guardado en {os.path.basename(self.output_file)}")

    def _update_tray_idle(self):
        app = self.get_application()
        if app and app.tray:
            app.tray.set_recording(False)
        if app and app.mpris:
            app.mpris.set_playback_status("Stopped")

    def _cleanup_log(self):
        if self._ffmpeg_log:
            try:
                self._ffmpeg_log.close()
            except Exception:
                pass
            self._ffmpeg_log = None

    def _read_last_log_line(self):
        if not self._ffmpeg_log:
            return "error desconocido"
        try:
            self._ffmpeg_log.seek(0)
            lines = self._ffmpeg_log.read().decode(errors="ignore").strip().splitlines()
            return lines[-1] if lines else "error desconocido"
        except Exception:
            return "error desconocido"

    def update_timer(self):
        if self.recording_process and self.recording_process.poll() is not None:
            detail = self._read_last_log_line()
            self.recording_process = None
            self._cleanup_log()
            if self.timer_id:
                GLib.source_remove(self.timer_id)
                self.timer_id = None
            self.show_toast(f"La grabación se detuvo inesperadamente: {detail}")
            self._reset_idle_ui("Error en la grabación")
            self._update_tray_idle()
            return False

        elapsed = int(time.time() - self.start_time)
        mins, secs = divmod(elapsed, 60)
        hours, mins = divmod(mins, 60)
        self.status_row.set_subtitle(f"Grabando... {hours:02d}:{mins:02d}:{secs:02d}")
        return True

    def _mpris_play(self):
        if self.recording_process is None and self.countdown_id is None:
            self._start_countdown()

    def _mpris_pause(self):
        if self.recording_process is not None:
            self.stop_recording()

    def _mpris_stop(self):
        if self.recording_process is not None:
            self.stop_recording()
        elif self.countdown_id is not None:
            self._cancel_countdown()

    def on_close_request(self, *args):
        if self.countdown_id:
            GLib.source_remove(self.countdown_id)
            self.countdown_id = None
        if self.snap_countdown_id:
            GLib.source_remove(self.snap_countdown_id)
            self.snap_countdown_id = None
        if self._startup_check_id:
            GLib.source_remove(self._startup_check_id)
            self._startup_check_id = None
        if self._stop_watch_id:
            GLib.source_remove(self._stop_watch_id)
            self._stop_watch_id = None

        if self.recording_process is not None:
            try:
                self.recording_process.send_signal(signal.SIGINT)
            except ProcessLookupError:
                pass
            try:
                self.recording_process.wait(timeout=1.5)
            except subprocess.TimeoutExpired:
                try:
                    self.recording_process.kill()
                except Exception:
                    pass
            self.recording_process = None
            self._cleanup_log()
        return False

    def show_toast(self, message):
        toast = Adw.Toast.new(message)
        toast.set_timeout(4)
        self.toast_overlay.add_toast(toast)


if __name__ == "__main__":
    app = RecorderApp()
    app.run(sys.argv)
