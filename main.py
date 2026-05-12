"""
HA Quick Actions — окно с кнопками быстрых вызовов сервисов Home Assistant.
Конфигурация: config.json рядом с этим файлом (см. config.example.json).
"""
from __future__ import annotations
import json
import os
import sys
import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext, simpledialog, ttk
from typing import Any, Callable
from urllib.parse import urljoin, urlparse, urlunparse
import requests
CONFIG_NAME = "config.json"
EXAMPLE_NAME = "config.example.json"
try:
    import pystray
    from PIL import Image, ImageDraw
    _TRAY_OK = True
except ImportError:
    pystray = None  # type: ignore[assignment]
    _TRAY_OK = False
def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))
def app_dir() -> str:
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))
def config_path() -> str:
    return os.path.join(app_dir(), CONFIG_NAME)
def load_config() -> dict[str, Any]:
    path = config_path()
    if not os.path.isfile(path):
        example = os.path.join(app_dir(), EXAMPLE_NAME)
        if os.path.isfile(example):
            with open(example, encoding="utf-8") as f:
                data = json.load(f)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            messagebox.showinfo(
                "Первый запуск",
                f"Создан файл настроек:\n{path}\n\n"
                "Укажите URL и токен (Файл → Подключение), настройте кнопки "
                "(Файл → Редактор кнопок).",
            )
        else:
            default: dict[str, Any] = {
                "ha_url": "http://homeassistant.local:8123",
                "ha_token": "",
                "buttons": [],
                "button_tabs": [{"title": "Действия", "buttons": []}],
                "ui": {
                    "button_font_size": 11,
                    "button_pad_x": 6,
                    "button_pad_y": 6,
                    "columns": 2,
                    "buttons_per_page": 0,
                    "sensor_panel_collapsed": False,
                },
                "sensor_panel": [],
                "sensor_tabs": [
                    {
                        "title": "Датчики",
                        "columns": 1,
                        "item_layout": "row",
                        "icon_size": 16,
                        "label_font_size": 10,
                        "value_font_size": 11,
                        "label_width_chars": 22,
                        "sensors": [],
                    }
                ],
                "sensor_refresh_seconds": 60,
                "close_to_tray": True,
                "start_minimized": False,
                "verify_ssl": True,
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(default, f, ensure_ascii=False, indent=2)
            messagebox.showinfo(
                "Первый запуск",
                f"Создан файл:\n{path}\n\nЗаполните ha_token и кнопки через редактор или вручную.",
            )
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    for key, default in (
        ("close_to_tray", True),
        ("start_minimized", False),
        ("verify_ssl", True),
        ("sensor_panel", []),
        ("sensor_refresh_seconds", 60),
    ):
        if key not in cfg:
            cfg[key] = default

    if not isinstance(cfg.get("button_tabs"), list) or len(cfg["button_tabs"]) == 0:
        btns = cfg.get("buttons")
        if isinstance(btns, list) and len(btns) > 0:
            cfg["button_tabs"] = [
                {"title": str(cfg.get("default_tab_title", "Действия")), "buttons": [dict(x) for x in btns if isinstance(x, dict)]}
            ]
        else:
            cfg["button_tabs"] = [{"title": "Действия", "buttons": []}]
    if not isinstance(cfg.get("ui"), dict):
        cfg["ui"] = {}
    merge_ui_defaults(cfg)
    bt_main = cfg.get("buttons")
    if not isinstance(bt_main, list) or len(bt_main) == 0:
        t0 = cfg.get("button_tabs")
        if isinstance(t0, list) and t0 and isinstance(t0[0], dict):
            fb = t0[0].get("buttons")
            if isinstance(fb, list) and fb:
                cfg["buttons"] = [dict(x) for x in fb if isinstance(x, dict)]

    if not isinstance(cfg.get("sensor_tabs"), list) or len(cfg["sensor_tabs"]) == 0:
        cfg["sensor_tabs"] = [
            {
                "title": "Датчики",
                "columns": 1,
                "item_layout": "row",
                "icon_size": 16,
                "label_font_size": 10,
                "value_font_size": 11,
                "label_width_chars": 22,
                "sensors": parse_sensor_panel(cfg.get("sensor_panel")),
            }
        ]
    st0 = cfg.get("sensor_tabs")
    if isinstance(st0, list) and st0 and isinstance(st0[0], dict):
        fs = st0[0].get("sensors")
        if isinstance(fs, list) and fs and (
            not isinstance(cfg.get("sensor_panel"), list) or len(cfg["sensor_panel"]) == 0
        ):
            cfg["sensor_panel"] = [dict(x) for x in fs if isinstance(x, dict)]

    return cfg
def save_config(data: dict[str, Any]) -> None:
    with open(config_path(), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


_UI_DEFAULTS: dict[str, Any] = {
    "button_font_size": 11,
    "button_pad_x": 6,
    "button_pad_y": 6,
    "columns": 2,
    "buttons_per_page": 0,
    "sensor_panel_collapsed": False,
}


def merge_ui_defaults(cfg: dict[str, Any]) -> None:
    ui = cfg.get("ui")
    if not isinstance(ui, dict):
        ui = {}
        cfg["ui"] = ui
    for k, v in _UI_DEFAULTS.items():
        if k not in ui:
            ui[k] = v


def get_ui_settings(cfg: dict[str, Any]) -> dict[str, Any]:
    merge_ui_defaults(cfg)
    return cfg["ui"]  # type: ignore[return-value]


def get_button_tabs(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Вкладки с кнопками: [{title, buttons: [...]}]."""
    raw = cfg.get("button_tabs")
    if not isinstance(raw, list) or not raw:
        return [{"title": "Действия", "buttons": []}]
    out: list[dict[str, Any]] = []
    for t in raw:
        if not isinstance(t, dict):
            continue
        title = str(t.get("title", "Вкладка")).strip() or "Вкладка"
        bt = t.get("buttons")
        if not isinstance(bt, list):
            bt = []
        out.append({"title": title, "buttons": [dict(x) for x in bt if isinstance(x, dict)]})
    return out if out else [{"title": "Действия", "buttons": []}]


def normalize_base_url(url: str) -> str:
    u = (url or "").strip().rstrip("/")
    if not u:
        return ""
    if not u.startswith(("http://", "https://")):
        u = "http://" + u
    return u


def api_root_url(url: str) -> str:
    """Только схема + хост + порт — для REST API HA путь в URL не нужен."""
    u = normalize_base_url(url)
    if not u:
        return ""
    parsed = urlparse(u)
    if not parsed.scheme or not parsed.netloc:
        return u
    return urlunparse((parsed.scheme, parsed.netloc, "", "", "", ""))


def _clipboard_text(widget: tk.Misc) -> str | None:
    """Текст из системного буфера (для вставки в поля)."""
    top = widget.winfo_toplevel()
    try:
        data = top.clipboard_get()
    except tk.TclError:
        return None
    if isinstance(data, str):
        return data
    try:
        return str(data)
    except Exception:
        return None


def setup_entry_paste(entry: tk.Entry) -> None:
    """Ctrl+V, Shift+Insert, ПКМ — вставка из буфера (tk.Entry / ttk.Entry)."""
    top = entry.winfo_toplevel()

    def paste(_event: tk.Event | None = None) -> str:
        t = _clipboard_text(entry)
        if not t:
            return "break"
        try:
            entry.delete("sel.first", "sel.last")
        except tk.TclError:
            pass
        entry.insert(tk.INSERT, t)
        return "break"

    def copy(_event: tk.Event | None = None) -> str:
        try:
            if entry.selection_present():
                top.clipboard_clear()
                top.clipboard_append(entry.selection_get())
        except tk.TclError:
            pass
        return "break"

    def cut(_event: tk.Event | None = None) -> str:
        copy()
        try:
            entry.delete("sel.first", "sel.last")
        except tk.TclError:
            pass
        return "break"

    for seq in ("<<Paste>>", "<Shift-Insert>"):
        entry.bind(seq, paste)
    entry.bind("<Control-c>", copy)
    entry.bind("<Control-x>", cut)
    menu = tk.Menu(entry, tearoff=0)
    menu.add_command(label="Вставить", command=lambda: paste(None))
    menu.add_command(label="Копировать", command=lambda: copy(None))
    menu.add_command(label="Вырезать", command=lambda: cut(None))

    def show_menu(event: tk.Event) -> None:
        menu.tk_popup(event.x_root, event.y_root)

    entry.bind("<Button-3>", show_menu)


def setup_text_paste(text: tk.Text) -> None:
    """Копирование/вставка для tk.Text и ScrolledText."""
    top = text.winfo_toplevel()

    def paste(_event: tk.Event | None = None) -> str:
        t = _clipboard_text(text)
        if not t:
            return "break"
        try:
            text.delete(tk.SEL_FIRST, tk.SEL_LAST)
        except tk.TclError:
            pass
        text.insert(tk.INSERT, t)
        return "break"

    def copy(_event: tk.Event | None = None) -> str:
        try:
            if text.tag_ranges(tk.SEL):
                top.clipboard_clear()
                top.clipboard_append(text.get(tk.SEL_FIRST, tk.SEL_LAST))
        except tk.TclError:
            pass
        return "break"

    def cut(_event: tk.Event | None = None) -> str:
        copy()
        try:
            text.delete(tk.SEL_FIRST, tk.SEL_LAST)
        except tk.TclError:
            pass
        return "break"

    text.bind("<<Paste>>", paste)
    text.bind("<Shift-Insert>", paste)
    text.bind("<Control-c>", copy)
    text.bind("<Control-x>", cut)
    menu = tk.Menu(text, tearoff=0)
    menu.add_command(label="Вставить", command=lambda: paste(None))
    menu.add_command(label="Копировать", command=lambda: copy(None))
    menu.add_command(label="Вырезать", command=lambda: cut(None))

    def show_menu(event: tk.Event) -> None:
        menu.tk_popup(event.x_root, event.y_root)

    text.bind("<Button-3>", show_menu)


def _clean_token(token: str) -> str:
    t = (token or "").strip()
    return t.replace("\r", "").replace("\n", "")


def _request_verify(cfg: dict[str, Any]) -> bool | str:
    if cfg.get("verify_ssl", True) is False:
        return False
    return True


def _disable_insecure_warning_if_needed(verify: bool | str) -> None:
    if verify is False:
        try:
            import urllib3

            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        except Exception:
            pass


def check_ha_connection(cfg: dict[str, Any]) -> tuple[bool, str]:
    """GET /api/ — проверка URL и токена."""
    base = api_root_url(str(cfg.get("ha_url", "")))
    token = _clean_token(str(cfg.get("ha_token", "")))
    verify = _request_verify(cfg)
    _disable_insecure_warning_if_needed(verify)
    if not base:
        return False, (
            "Пустой или некорректный URL.\n\n"
            "Укажите адрес вида:\n"
            "  https://192.168.1.10:8123\n"
            "  http://homeassistant.local:8123\n\n"
            "Без пути к Lovelace — только протокол, хост и порт."
        )
    if not token:
        return False, "Пустой токен. Создайте Long-Lived Access Token в профиле Home Assistant (внизу страницы профиля)."
    url = urljoin(base + "/", "api/")
    try:
        r = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=25,
            verify=verify,
        )
    except requests.exceptions.SSLError as e:
        return False, (
            f"Ошибка SSL при запросе:\n{url}\n\n{str(e)}\n\n"
            "Если сертификат самоподписанный — снимите галку "
            "«Проверять SSL-сертификат» и нажмите «Проверить» снова."
        )
    except requests.exceptions.ConnectionError as e:
        return False, (
            f"Не удаётся установить соединение с:\n{base}\n\n{str(e)}\n\n"
            "Проверьте: HA запущен, IP/имя и порт верны, с этого компьютера "
            "сервер доступен (откройте тот же URL в браузере)."
        )
    except requests.RequestException as e:
        return False, f"Ошибка запроса к {url}\n\n{type(e).__name__}: {e}"
    if r.status_code == 200:
        return True, "Подключение успешно (GET /api/)."
    if r.status_code in (401, 403):
        return False, (
            f"HTTP {r.status_code} — неверный токен или нет прав.\n\n"
            "Создайте новый Long-Lived Access Token в профиле HA и вставьте "
            "его целиком, без пробелов в начале/конце."
        )
    return False, (
        f"HTTP {r.status_code}\nЗапрос: {url}\n\n"
        f"Ответ сервера:\n{r.text[:800]}"
    )


def call_service(
    cfg: dict[str, Any],
    domain: str,
    service: str,
    service_data: dict[str, Any] | None,
) -> tuple[bool, str]:
    base = api_root_url(str(cfg.get("ha_url", "")))
    token = _clean_token(str(cfg.get("ha_token", "")))
    verify = _request_verify(cfg)
    _disable_insecure_warning_if_needed(verify)
    if not base or not token:
        return False, "Не задан URL или токен"
    url = urljoin(base + "/", f"api/services/{domain}/{service}")
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    body = service_data if service_data else {}
    try:
        r = requests.post(url, headers=headers, json=body, timeout=30, verify=verify)
        if r.status_code in (200, 201):
            return True, f"OK ({r.status_code})"
        if r.status_code in (401, 403):
            return False, "HTTP 401/403 — проверьте токен в «Подключение…»."
        return False, f"HTTP {r.status_code}: {r.text[:500]}"
    except requests.exceptions.SSLError as e:
        return False, f"SSL: {e}. Включите «Проверять SSL» или отключите проверку в настройках."
    except requests.RequestException as e:
        return False, str(e)


def fetch_ha_states(cfg: dict[str, Any]) -> tuple[bool, str, list[dict[str, Any]]]:
    """GET /api/states — все сущности с именами и доменами."""
    base = api_root_url(str(cfg.get("ha_url", "")))
    token = _clean_token(str(cfg.get("ha_token", "")))
    verify = _request_verify(cfg)
    _disable_insecure_warning_if_needed(verify)
    if not base or not token:
        return False, "Сначала укажите URL и токен: Файл → Подключение…", []
    url = urljoin(base + "/", "api/states")
    try:
        r = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=60,
            verify=verify,
        )
    except requests.exceptions.SSLError as e:
        return False, f"SSL: {e}\n\nСнимите «Проверять SSL» в подключении, если сертификат свой.", []
    except requests.RequestException as e:
        return False, str(e), []
    if r.status_code == 200:
        data = r.json()
        if isinstance(data, list):
            return True, "", data
        return False, "Ответ /api/states не список", []
    if r.status_code in (401, 403):
        return False, "HTTP 401/403 — неверный токен.", []
    return False, f"HTTP {r.status_code}: {r.text[:400]}", []


def parse_ha_services_response(data: Any) -> dict[str, list[str]]:
    """Разбор ответа GET /api/services → domain -> [имена служб]."""
    out: dict[str, list[str]] = {}
    if not isinstance(data, list):
        return out
    for block in data:
        if not isinstance(block, dict):
            continue
        dom = str(block.get("domain", "")).strip().lower()
        if not dom:
            continue
        svc_def = block.get("services")
        names: list[str] = []
        if isinstance(svc_def, dict):
            names = sorted(svc_def.keys(), key=str.lower)
        elif isinstance(svc_def, list):
            for item in svc_def:
                if isinstance(item, dict) and item.get("service") is not None:
                    names.append(str(item["service"]))
                elif isinstance(item, str):
                    names.append(item)
            names.sort(key=str.lower)
        if names:
            out[dom] = names
    return out


def fetch_ha_services(cfg: dict[str, Any]) -> tuple[bool, str, dict[str, list[str]]]:
    """GET /api/services — реестр служб по доменам (как в «Инструменты разработчика» HA)."""
    base = api_root_url(str(cfg.get("ha_url", "")))
    token = _clean_token(str(cfg.get("ha_token", "")))
    verify = _request_verify(cfg)
    _disable_insecure_warning_if_needed(verify)
    if not base or not token:
        return False, "Нет URL или токена", {}
    url = urljoin(base + "/", "api/services")
    try:
        r = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=45,
            verify=verify,
        )
    except requests.exceptions.SSLError as e:
        return False, str(e), {}
    except requests.RequestException as e:
        return False, str(e), {}
    if r.status_code == 200:
        parsed = parse_ha_services_response(r.json())
        return True, "", parsed
    if r.status_code in (401, 403):
        return False, "HTTP 401/403", {}
    return False, f"HTTP {r.status_code}", {}


_FALLBACK_DOMAIN_SERVICES: dict[str, list[str]] = {
    "light": ["turn_on", "turn_off", "toggle"],
    "switch": ["turn_on", "turn_off", "toggle"],
    "fan": ["turn_on", "turn_off", "toggle", "set_percentage", "increase_speed", "decrease_speed"],
    "climate": ["set_temperature", "set_hvac_mode", "set_preset_mode", "turn_on", "turn_off"],
    "cover": ["open_cover", "close_cover", "stop_cover", "set_cover_position", "toggle"],
    "lock": ["lock", "unlock", "open"],
    "script": ["turn_on", "reload", "toggle"],
    "scene": ["turn_on", "reload", "apply"],
    "automation": ["trigger", "turn_on", "turn_off", "toggle"],
    "input_boolean": ["turn_on", "turn_off", "toggle"],
    "input_button": ["press"],
    "button": ["press"],
    "input_select": ["select_option", "reload"],
    "input_number": ["set_value", "increment", "decrement", "reload"],
    "input_text": ["set_value", "reload"],
    "media_player": ["turn_on", "turn_off", "toggle", "volume_set", "volume_mute", "media_play_pause"],
    "vacuum": ["start", "pause", "stop", "return_to_base", "locate"],
    "alarm_control_panel": ["alarm_disarm", "alarm_arm_home", "alarm_arm_away", "alarm_arm_night"],
    "notify": ["persistent_notification", "send_message"],
    "persistent_notification": ["create", "dismiss"],
    "homeassistant": ["restart", "reload_config_entry", "reload_core_config"],
    "group": ["set", "reload", "remove"],
    "timer": ["start", "pause", "cancel", "finish"],
    "counter": ["increment", "decrement", "reset", "set_value"],
    "update": ["install", "skip"],
}


def default_service_registry() -> dict[str, list[str]]:
    return {k: list(v) for k, v in _FALLBACK_DOMAIN_SERVICES.items()}


def merge_service_registry(api: dict[str, list[str]]) -> dict[str, list[str]]:
    merged = default_service_registry()
    for dom, names in api.items():
        if isinstance(names, list) and names:
            merged[dom.lower()] = list(names)
    return merged


def _state_domain(entity_id: str) -> str:
    if "." in entity_id:
        return entity_id.split(".", 1)[0]
    return "unknown"


def _friendly_name(state: dict[str, Any]) -> str:
    attrs = state.get("attributes")
    if isinstance(attrs, dict):
        fn = attrs.get("friendly_name")
        if isinstance(fn, str) and fn.strip():
            return fn.strip()
    return ""


def format_entity_state_text(st: dict[str, Any]) -> str:
    """Текст состояния для панели (значение + единица измерения)."""
    if not isinstance(st, dict):
        return "—"
    val = st.get("state")
    s = "?" if val is None else str(val)
    attrs = st.get("attributes")
    if isinstance(attrs, dict):
        u = attrs.get("unit_of_measurement")
        if u is not None and str(u).strip():
            s = f"{s} {u}"
    return s


def parse_sensor_panel(raw: Any) -> list[dict[str, str]]:
    """Список датчиков: entity_id, подпись label (или name), иконка icon (эмодзи или mdi:…)."""
    out: list[dict[str, str]] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if isinstance(item, str):
            eid = item.strip()
            if eid and "." in eid:
                out.append({"entity_id": eid, "label": "", "icon": ""})
        elif isinstance(item, dict):
            eid = str(item.get("entity_id", "")).strip()
            if eid and "." in eid:
                lab = str(item.get("label", "") or item.get("name", "") or "").strip()
                icon = str(item.get("icon", "") or "").strip()
                out.append({"entity_id": eid, "label": lab, "icon": icon})
    return out


_SENSOR_TAB_DEFAULTS: dict[str, Any] = {
    "columns": 1,
    "item_layout": "row",
    "icon_size": 16,
    "label_font_size": 10,
    "value_font_size": 11,
    "label_width_chars": 22,
}


def normalize_sensor_tab(tab: dict[str, Any]) -> dict[str, Any]:
    """Одна вкладка датчиков: заголовок, оформление, список sensors."""
    title = str(tab.get("title", "Вкладка")).strip() or "Вкладка"
    out: dict[str, Any] = {"title": title}
    for k, v in _SENSOR_TAB_DEFAULTS.items():
        out[k] = tab[k] if k in tab else v
    try:
        out["columns"] = max(1, min(8, int(out["columns"])))
    except (TypeError, ValueError):
        out["columns"] = 1
    il_raw = str(out.get("item_layout", "row")).lower()
    if il_raw in ("column", "vertical", "col", "вертикаль"):
        out["item_layout"] = "column"
    else:
        out["item_layout"] = "row"
    for key, lo, hi, fallback in (
        ("icon_size", 8, 36, 16),
        ("label_font_size", 7, 20, 10),
        ("value_font_size", 7, 22, 11),
        ("label_width_chars", 4, 48, 22),
    ):
        try:
            out[key] = max(lo, min(hi, int(out[key])))
        except (TypeError, ValueError):
            out[key] = fallback
    sens = tab.get("sensors")
    if not isinstance(sens, list):
        sens = []
    out["sensors"] = parse_sensor_panel(sens)
    return out


def get_sensor_tabs(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Вкладки датчиков с полями из normalize_sensor_tab."""
    raw = cfg.get("sensor_tabs")
    if not isinstance(raw, list) or not raw:
        leg = parse_sensor_panel(cfg.get("sensor_panel"))
        return [normalize_sensor_tab({"title": "Датчики", "sensors": leg})]
    out: list[dict[str, Any]] = []
    for t in raw:
        if isinstance(t, dict):
            out.append(normalize_sensor_tab(t))
    return out if out else [normalize_sensor_tab({"title": "Датчики", "sensors": []})]


def ha_attribute_icon_to_display(icon_val: Any) -> str:
    """Краткий текст для mdi:… из HA; эмодзи возвращаются как есть."""
    if not isinstance(icon_val, str) or not icon_val.strip():
        return ""
    s = icon_val.strip()
    if s.startswith("mdi:"):
        tail = s[4:].replace("_", " ")
        return tail[:14] if len(tail) > 14 else tail
    return s


def fetch_entity_state(cfg: dict[str, Any], entity_id: str) -> tuple[bool, str, dict[str, Any] | None]:
    """GET /api/states/<entity_id> — одна сущность (иконка из attributes)."""
    base = api_root_url(str(cfg.get("ha_url", "")))
    token = _clean_token(str(cfg.get("ha_token", "")))
    verify = _request_verify(cfg)
    _disable_insecure_warning_if_needed(verify)
    if not base or not token:
        return False, "Нет URL или токена", None
    eid = entity_id.strip()
    if not eid:
        return False, "Пустой entity_id", None
    url = urljoin(base + "/", f"api/states/{eid}")
    try:
        r = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=20,
            verify=verify,
        )
    except requests.RequestException as e:
        return False, str(e), None
    if r.status_code == 200:
        data = r.json()
        return (True, "", data) if isinstance(data, dict) else (False, "Неверный JSON", None)
    return False, f"HTTP {r.status_code}", None


def states_by_entity_id(states: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    m: dict[str, dict[str, Any]] = {}
    for st in states:
        if not isinstance(st, dict):
            continue
        eid = str(st.get("entity_id", "")).strip()
        if eid:
            m[eid] = st
    return m


def suggested_service_for_domain(domain: str) -> str:
    if domain in ("script", "scene"):
        return "turn_on"
    if domain in ("input_button", "button"):
        return "press"
    if domain == "automation":
        return "trigger"
    if domain in ("light", "switch", "fan", "input_boolean"):
        return "toggle"
    if domain == "lock":
        return "unlock"
    if domain == "cover":
        return "open_cover"
    if domain == "climate":
        return "turn_on"
    return "turn_on"


class EntityPickerDialog(tk.Toplevel):
    """Выбор сущности из списка, сгруппированного по доменам (категориям HA)."""

    def __init__(self, parent: tk.Widget, cfg: dict[str, Any], on_pick: Callable[[str, str, str], None]):
        super().__init__(parent)
        self.title("Сущности Home Assistant")
        self.cfg = cfg
        self.on_pick = on_pick
        self.transient(parent.winfo_toplevel())
        self._all_rows: list[tuple[str, str, str]] = []  # domain, entity_id, friendly
        self._status = tk.StringVar(value="Загрузка…")

        outer = ttk.Frame(self, padding=10)
        outer.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            outer,
            text="Категория — это домен сущности (light, switch, script…). "
            "Выберите строку с ID сущности и нажмите «Выбрать» или двойной щелчок.",
            wraplength=560,
            font=("Segoe UI", 9),
        ).pack(anchor=tk.W, pady=(0, 8))

        filt = ttk.Frame(outer)
        filt.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(filt, text="Домен:").pack(side=tk.LEFT, padx=(0, 6))
        self.domain_filter = ttk.Combobox(filt, width=22, state="readonly")
        self.domain_filter.pack(side=tk.LEFT, padx=(0, 12))
        self.domain_filter.bind("<<ComboboxSelected>>", lambda _e: self._rebuild_tree())
        ttk.Label(filt, text="Поиск:").pack(side=tk.LEFT, padx=(0, 6))
        self.search_var = tk.StringVar()
        self.search_entry = tk.Entry(filt, textvariable=self.search_var, width=28, font=("Segoe UI", 10))
        self.search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._search_trace_id = self.search_var.trace_add("write", lambda *_a: self._schedule_filter())
        setup_entry_paste(self.search_entry)

        tree_frame = ttk.Frame(outer)
        tree_frame.pack(fill=tk.BOTH, expand=True, pady=6)
        yscroll = ttk.Scrollbar(tree_frame)
        yscroll.pack(side=tk.RIGHT, fill=tk.Y)
        xscroll = ttk.Scrollbar(tree_frame, orient=tk.HORIZONTAL)
        xscroll.pack(side=tk.BOTTOM, fill=tk.X)
        self.tree = ttk.Treeview(
            tree_frame,
            columns=("eid", "state"),
            show="tree headings",
            selectmode="browse",
            yscrollcommand=yscroll.set,
            xscrollcommand=xscroll.set,
        )
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        yscroll.config(command=self.tree.yview)
        xscroll.config(command=self.tree.xview)
        self.tree.heading("#0", text="Название")
        self.tree.column("#0", width=320, minwidth=80, stretch=True)
        self.tree.heading("eid", text="ID сущности")
        self.tree.column("eid", width=220, minwidth=80, stretch=False)
        self.tree.heading("state", text="Состояние")
        self.tree.column("state", width=90, minwidth=50, stretch=False)
        self.tree.bind("<Double-1>", self._on_double)
        self.tree.bind("<<TreeviewSelect>>", self._on_sel)

        st = ttk.Label(outer, textvariable=self._status, relief=tk.SUNKEN, anchor=tk.W)
        st.pack(fill=tk.X, pady=(4, 8))

        btn_row = ttk.Frame(outer)
        btn_row.pack(fill=tk.X)
        ttk.Button(btn_row, text="Обновить список", command=self._start_load).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(btn_row, text="Выбрать", command=self._apply).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(btn_row, text="Отмена", command=self.destroy).pack(side=tk.LEFT)

        self.geometry("720x560")
        self.grab_set()
        self.after(10, self._ready)
        self._filter_after: str | None = None
        self._state_by_eid: dict[str, str] = {}
        self._start_load()

    def _ready(self) -> None:
        self.lift()
        self.focus_force()
        try:
            self.attributes("-topmost", True)
            self.after(150, lambda: self.attributes("-topmost", False))
        except tk.TclError:
            pass

    def _schedule_filter(self) -> None:
        if self._filter_after:
            self.after_cancel(self._filter_after)
        self._filter_after = self.after(200, self._rebuild_tree)

    def _start_load(self) -> None:
        self._status.set("Загрузка списка с сервера…")
        cfg = self.cfg

        def work() -> None:
            ok, err, states = fetch_ha_states(cfg)

            def done() -> None:
                if self._filter_after:
                    try:
                        self.after_cancel(self._filter_after)
                    except tk.TclError:
                        pass
                    self._filter_after = None
                if not ok:
                    self._status.set("Ошибка")
                    messagebox.showerror("Сущности", err, parent=self)
                    return
                rows: list[tuple[str, str, str]] = []
                state_map: dict[str, str] = {}
                for st in states:
                    if not isinstance(st, dict):
                        continue
                    eid = str(st.get("entity_id", "") or "").strip()
                    if not eid or "." not in eid:
                        continue
                    dom = _state_domain(eid)
                    fn = _friendly_name(st)
                    rows.append((dom, eid, fn))
                    sv = st.get("state")
                    state_map[eid] = (str(sv) if sv is not None else "")[:48]
                rows.sort(key=lambda x: (x[0].lower(), (x[2] or x[1]).lower()))
                self._all_rows = rows
                self._state_by_eid = state_map
                domains = sorted({d for d, _, _ in rows}, key=str.lower)
                self.domain_filter["values"] = ["(все)"] + domains
                self.domain_filter.set("(все)")
                self._rebuild_tree()
                self._status.set(f"Загружено сущностей: {len(rows)}")

            self.after(0, done)

        threading.Thread(target=work, daemon=True).start()

    def _matches_filter(self, domain: str, entity_id: str, friendly: str) -> bool:
        df = self.domain_filter.get()
        if df and df != "(все)" and domain != df:
            return False
        q = self.search_var.get().strip().lower()
        if not q:
            return True
        if q in entity_id.lower():
            return True
        if friendly and q in friendly.lower():
            return True
        return False

    def _rebuild_tree(self) -> None:
        self.tree.delete(*self.tree.get_children())
        by_dom: dict[str, list[tuple[str, str, str]]] = {}
        for dom, eid, fn in self._all_rows:
            if not self._matches_filter(dom, eid, fn):
                continue
            by_dom.setdefault(dom, []).append((dom, eid, fn))
        df = ""
        try:
            df = self.domain_filter.get()
        except tk.TclError:
            pass
        for dom in sorted(by_dom.keys(), key=str.lower):
            items = by_dom[dom]
            pid = "p:" + dom
            open_cat = bool(df and df != "(все)" and df == dom)
            self.tree.insert(
                "",
                "end",
                iid=pid,
                text=f"{dom}  ({len(items)})",
                values=("", ""),
                open=open_cat,
            )
            for _d, eid, fn in items:
                display = fn if fn else eid
                short_state = (self._state_by_eid.get(eid, "") or "")[:32]
                self.tree.insert(pid, "end", iid=eid, text=display, values=(eid, short_state))

    def _picked_entity_id(self) -> str | None:
        sel = self.tree.selection()
        if not sel:
            return None
        iid = sel[0]
        if isinstance(iid, str) and iid.startswith("p:"):
            return None
        return str(iid) if iid else None

    def _apply(self) -> None:
        eid = self._picked_entity_id()
        if not eid:
            messagebox.showinfo(
                "Выбор",
                "Выберите одну сущность (строку под категорией), а не саму категорию.",
                parent=self,
            )
            return
        dom = _state_domain(eid)
        fn = ""
        for d, e, f in self._all_rows:
            if e == eid:
                fn = f
                break
        self.on_pick(eid, dom, fn)
        self.destroy()

    def _on_double(self, _evt: tk.Event) -> None:
        if self._picked_entity_id():
            self._apply()

    def _on_sel(self, _evt: tk.Event | None = None) -> None:
        eid = self._picked_entity_id()
        if eid:
            self._status.set(f"Выбрано: {eid}")
        elif self.tree.selection():
            self._status.set("Разверните категорию и выберите сущность")

    def destroy(self) -> None:
        if self._filter_after:
            try:
                self.after_cancel(self._filter_after)
            except tk.TclError:
                pass
            self._filter_after = None
        try:
            self.search_var.trace_remove("write", self._search_trace_id)
        except (tk.TclError, ValueError, AttributeError):
            pass
        super().destroy()


# --- Windows autostart (HKCU Run) ---
AUTORUN_VALUE_NAME = "HA-Quick-Actions"
def _launch_command() -> str:
    if is_frozen():
        exe = os.path.normpath(sys.executable)
        return f'"{exe}"'
    py = os.path.normpath(sys.executable)
    script = os.path.normpath(os.path.join(app_dir(), "main.py"))
    if sys.platform == "win32" and py.lower().endswith("python.exe"):
        cand = py[:-10] + "pythonw.exe"
        if os.path.isfile(cand):
            py = cand
    return f'"{py}" "{script}"'
def autostart_enabled() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_READ,
        )
        try:
            winreg.QueryValueEx(key, AUTORUN_VALUE_NAME)
            return True
        except OSError:
            return False
        finally:
            winreg.CloseKey(key)
    except OSError:
        return False
def set_autostart(enabled: bool) -> tuple[bool, str]:
    if sys.platform != "win32":
        return False, "Только Windows"
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_SET_VALUE,
        )
        try:
            if enabled:
                winreg.SetValueEx(key, AUTORUN_VALUE_NAME, 0, winreg.REG_SZ, _launch_command())
            else:
                try:
                    winreg.DeleteValue(key, AUTORUN_VALUE_NAME)
                except OSError:
                    pass
            return True, ""
        finally:
            winreg.CloseKey(key)
    except OSError as e:
        return False, str(e)
def tray_icon_image() -> "Image.Image":
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    margin = 6
    draw.rounded_rectangle(
        [margin, margin, size - margin, size - margin],
        radius=10,
        fill=(33, 150, 243, 255),
    )
    draw.text((18, 20), "HA", fill=(255, 255, 255, 255))
    return img
class ButtonItemDialog(tk.Toplevel):
    """Одна кнопка быстрого действия: вызов service в HA по entity_id."""

    _HELP = (
        "Что сюда вписывать (из Home Assistant):\n\n"
        "1) Подпись на кнопке — любой текст для себя (например «Свет в зале»).\n\n"
        "2) ID сущности (entity_id) — главное поле. В HA: Настройки → Устройства и службы "
        "→ вкладка «Сущности» → найдите лампу/выключатель/сценарий → откройте запись и "
        "скопируйте «ID сущности» (вид: light.gostinaya, switch.tv, script.good_night).\n"
        "   Кнопка «Из буфера» вставляет скопированный ID.\n"
        "   Кнопка «Список из HA…» загружает все сущности с сервера и позволяет выбрать из дерева по доменам.\n\n"
        "3) Домен (domain) и служба (service) — выпадающие списки: сначала типовые значения, "
        "после подключения к HA подгружается полный список с сервера (/api/services). "
        "Можно ввести своё значение вручную в поле комбобокса.\n\n"
        "4) Доп. JSON (service_data) — только если нужны редкие параметры (яркость и т.д.). "
        "Обычно достаточно entity_id + service.\n\n"
        "Вставка в поля: Ctrl+V, Shift+Insert, правый клик → «Вставить», либо «Из буфера»."
    )

    def __init__(
        self,
        parent: tk.Widget,
        title: str,
        initial: dict[str, Any] | None,
        on_ok: Callable[[dict[str, Any]], None],
        cfg: dict[str, Any],
    ):
        super().__init__(parent)
        self.title(title)
        self.on_ok = on_ok
        self.cfg = cfg
        self.transient(parent.winfo_toplevel())

        init = initial or {}
        sd = dict(init.get("service_data") or {}) if isinstance(init.get("service_data"), dict) else {}
        entity = init.get("entity_id") or sd.get("entity_id", "")
        for k in ("entity_id",):
            sd.pop(k, None)
        extra_txt = json.dumps(sd, ensure_ascii=False, indent=2) if sd else ""

        outer = ttk.Frame(self, padding=10)
        outer.pack(fill=tk.BOTH, expand=True)

        help_lf = ttk.LabelFrame(outer, text="Как это связано с Home Assistant", padding=8)
        help_lf.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(help_lf, text=self._HELP, wraplength=560, justify=tk.LEFT, font=("Segoe UI", 9)).pack(
            anchor=tk.W
        )

        frm = ttk.Frame(outer, padding=(0, 0, 0, 0))
        frm.pack(fill=tk.BOTH, expand=True)

        r = 0
        ttk.Label(frm, text="Подпись на кнопке (любой текст):").grid(row=r, column=0, sticky=tk.W)
        self.label_var = tk.StringVar(value=str(init.get("label", "")))
        self.label_entry = tk.Entry(frm, textvariable=self.label_var, font=("Segoe UI", 10))
        self.label_entry.grid(row=r + 1, column=0, sticky=tk.EW, pady=(0, 8))
        r += 2

        ttk.Label(
            frm,
            text="ID сущности entity_id (скопируйте в HA из карточки сущности):",
        ).grid(row=r, column=0, sticky=tk.W)
        ent_row = ttk.Frame(frm)
        ent_row.grid(row=r + 1, column=0, sticky=tk.EW, pady=(0, 8))
        ent_row.columnconfigure(0, weight=1)
        self.entity_var = tk.StringVar(value=str(entity or ""))
        self.entity_entry = tk.Entry(ent_row, textvariable=self.entity_var, font=("Segoe UI", 10))
        self.entity_entry.grid(row=0, column=0, sticky=tk.EW, padx=(0, 8))
        ttk.Button(ent_row, text="Из буфера", command=self._paste_entity).grid(row=0, column=1, padx=(0, 6))
        ttk.Button(ent_row, text="Список из HA…", command=self._open_entity_picker).grid(row=0, column=2)
        r += 2

        self._service_registry: dict[str, list[str]] = merge_service_registry({})
        self._domain_trace_id: str | None = None

        ttk.Label(
            frm,
            text="Домен (domain) и служба (service) — выберите из списка или введите вручную:",
        ).grid(row=r, column=0, sticky=tk.W)
        ds_row = ttk.Frame(frm)
        ds_row.grid(row=r + 1, column=0, sticky=tk.EW, pady=(0, 8))
        ds_row.columnconfigure(1, weight=1)
        ds_row.columnconfigure(3, weight=1)
        self.domain_var = tk.StringVar(value=str(init.get("domain", "")))
        ttk.Label(ds_row, text="domain").grid(row=0, column=0, padx=(0, 6), sticky=tk.W)
        self.domain_cb = ttk.Combobox(
            ds_row,
            textvariable=self.domain_var,
            width=18,
            font=("Segoe UI", 10),
        )
        self.domain_cb.grid(row=0, column=1, sticky=tk.EW, padx=(0, 16))
        self.service_var = tk.StringVar(value=str(init.get("service", "")))
        ttk.Label(ds_row, text="service").grid(row=0, column=2, padx=(0, 6), sticky=tk.W)
        self.service_cb = ttk.Combobox(
            ds_row,
            textvariable=self.service_var,
            width=22,
            font=("Segoe UI", 10),
        )
        self.service_cb.grid(row=0, column=3, sticky=tk.EW)
        r += 2

        ttk.Label(frm, text="Доп. параметры service_data (JSON-объект {…}, обычно не нужен):").grid(
            row=r, column=0, sticky=tk.W
        )
        self.extra = scrolledtext.ScrolledText(frm, width=60, height=5, font=("Consolas", 10))
        extra_row = r + 1
        self.extra.grid(row=extra_row, column=0, sticky=tk.NSEW, pady=(0, 10))
        if extra_txt.strip():
            self.extra.insert("1.0", extra_txt)
        r += 2

        btn_row = ttk.Frame(frm)
        btn_row.grid(row=r, column=0, sticky=tk.EW)
        ttk.Button(btn_row, text="OK", command=self._ok).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(btn_row, text="Отмена", command=self.destroy).pack(side=tk.LEFT)

        frm.columnconfigure(0, weight=1)
        frm.rowconfigure(extra_row, weight=1)

        setup_entry_paste(self.label_entry)
        setup_entry_paste(self.entity_entry)
        setup_text_paste(self.extra)

        self._populate_domain_combo()
        self._sync_service_list()
        self._domain_trace_id = self.domain_var.trace_add("write", lambda *_a: self.after_idle(self._sync_service_list))
        self.after(150, self._load_services_from_ha)

        self.geometry("640x720")
        self.grab_set()
        self.after(10, self._dialog_ready)

    def _dialog_ready(self) -> None:
        self.lift()
        self.focus_force()
        try:
            self.attributes("-topmost", True)
            self.after(200, lambda: self.attributes("-topmost", False))
        except tk.TclError:
            pass
        self.entity_entry.focus_set()

    def _paste_entity(self) -> None:
        t = _clipboard_text(self)
        if not t:
            messagebox.showwarning("Буфер", "Сначала скопируйте ID сущности в Home Assistant.", parent=self)
            return
        line = t.strip().splitlines()[0].strip()
        if line.startswith("http"):
            messagebox.showinfo(
                "Буфер",
                "В буфере похоже URL сайта, а нужен ID сущности вида light.kuhnya или switch.tv.",
                parent=self,
            )
            return
        token = line.split()[0]
        if "." not in token:
            messagebox.showinfo(
                "Буфер",
                "Нужна строка с точкой: domain.object_id\nнапример light.gostinaya или script.good_night.",
                parent=self,
            )
            return
        self.entity_var.set(token)
        if "." in token:
            self.domain_var.set(_state_domain(token))
        self._populate_domain_combo()
        self._sync_service_list()

    def _open_entity_picker(self) -> None:
        def on_pick(entity_id: str, domain: str, friendly: str) -> None:
            self.entity_var.set(entity_id)
            self.domain_var.set(domain)
            self.service_var.set(suggested_service_for_domain(domain))
            if friendly and not self.label_var.get().strip():
                self.label_var.set(friendly)
            self._populate_domain_combo()
            self._sync_service_list()

        EntityPickerDialog(self, load_config(), on_pick)

    def _services_for_domain(self, domain: str) -> list[str]:
        d = domain.strip().lower()
        if not d:
            return sorted({"turn_on", "turn_off", "toggle", "press", "trigger", "reload"}, key=str.lower)
        for k, v in self._service_registry.items():
            if k.lower() == d:
                return list(v)
        return list(_FALLBACK_DOMAIN_SERVICES.get(d, ["turn_on", "turn_off", "toggle", "press", "trigger"]))

    def _populate_domain_combo(self) -> None:
        domains = sorted(self._service_registry.keys(), key=str.lower)
        cur = self.domain_var.get().strip()
        if cur and cur.lower() not in {x.lower() for x in domains}:
            domains = sorted(domains + [cur], key=str.lower)
        self.domain_cb["values"] = tuple(domains)

    def _sync_service_list(self) -> None:
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return
        dom = self.domain_var.get().strip()
        svcs = self._services_for_domain(dom)
        self.service_cb["values"] = tuple(svcs)

    def _load_services_from_ha(self) -> None:
        def work() -> None:
            ok, _err, reg = fetch_ha_services(load_config())

            def done() -> None:
                try:
                    if not self.winfo_exists():
                        return
                except tk.TclError:
                    return
                if ok and reg:
                    self._service_registry = merge_service_registry(reg)
                    self._populate_domain_combo()
                    self._sync_service_list()

            self.after(0, done)

        threading.Thread(target=work, daemon=True).start()

    def destroy(self) -> None:
        tid = getattr(self, "_domain_trace_id", None)
        if tid is not None:
            try:
                self.domain_var.trace_remove("write", tid)
            except (tk.TclError, ValueError):
                pass
            self._domain_trace_id = None
        super().destroy()

    def _ok(self) -> None:
        label = self.label_var.get().strip()
        domain = self.domain_var.get().strip()
        service = self.service_var.get().strip()
        entity = self.entity_var.get().strip()
        extra_raw = self.extra.get("1.0", tk.END).strip()
        if not label:
            messagebox.showwarning("Проверка", "Укажите подпись кнопки.", parent=self)
            return
        if not service:
            messagebox.showwarning("Проверка", "Укажите service (например turn_on).", parent=self)
            return
        if not entity:
            messagebox.showwarning(
                "Проверка",
                "Укажите entity_id сущности из Home Assistant\nили заполните domain вручную для особых случаев.",
                parent=self,
            )
            return
        if not domain and "." in entity:
            domain = entity.split(".", 1)[0]
        if not domain:
            messagebox.showwarning(
                "Проверка",
                "Не удалось определить domain. Укажите entity_id с точкой (light.xxx) или введите domain вручную.",
                parent=self,
            )
            return
        service_data: dict[str, Any] = {}
        if extra_raw:
            try:
                parsed = json.loads(extra_raw)
            except json.JSONDecodeError as e:
                messagebox.showerror("JSON", f"Ошибка разбора JSON:\n{e}", parent=self)
                return
            if not isinstance(parsed, dict):
                messagebox.showerror(
                    "JSON", "В доп. полях нужен JSON-объект {...}, не массив и не строка.", parent=self
                )
                return
            service_data = dict(parsed)
        service_data["entity_id"] = entity
        out = {"label": label, "domain": domain, "service": service, "service_data": service_data}
        self.on_ok(out)
        self.destroy()
class ButtonsEditorDialog(tk.Toplevel):
    """Редактор вкладок, кнопок и параметров отображения на главном окне."""

    _TOP_HELP = (
        "Вкладки группируют кнопки по темам. Внутри вкладки порядок строк = порядок кнопок.\n"
        "Ниже — размер шрифта кнопок, число колонок и сколько кнопок на одной «странице» "
        "(0 = показать все сразу).\n"
        "Список кнопок: Ctrl+C — копировать строку."
    )

    def __init__(self, parent: tk.Tk, cfg: dict[str, Any], on_saved: Callable[[], None]):
        super().__init__(parent)
        self.title("Редактор кнопок и вкладок")
        self.cfg = cfg
        self.on_saved = on_saved
        self.transient(parent)
        self.tabs: list[dict[str, Any]] = get_button_tabs(cfg)
        self.tab_idx = 0
        ui = get_ui_settings(cfg)

        frm = ttk.Frame(self, padding=10)
        frm.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frm, text=self._TOP_HELP, wraplength=620, justify=tk.LEFT, font=("Segoe UI", 9)).pack(
            anchor=tk.W, pady=(0, 8)
        )

        mid = ttk.Frame(frm)
        mid.pack(fill=tk.BOTH, expand=True, pady=4)
        left = ttk.LabelFrame(mid, text="Вкладки", padding=6)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 8))
        self.tab_lb = tk.Listbox(left, height=8, width=22, exportselection=False, font=("Segoe UI", 10))
        self.tab_lb.pack(fill=tk.BOTH, expand=True)
        self.tab_lb.bind("<<ListboxSelect>>", self._on_tab_select)
        tbf = ttk.Frame(left)
        tbf.pack(fill=tk.X, pady=(6, 0))
        ttk.Button(tbf, text="+", width=3, command=self._add_tab).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(tbf, text="Имя", command=self._rename_tab).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(tbf, text="−", width=3, command=self._delete_tab).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(tbf, text="↑", width=3, command=lambda: self._move_tab(-1)).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(tbf, text="↓", width=3, command=lambda: self._move_tab(1)).pack(side=tk.LEFT)

        right = ttk.LabelFrame(mid, text="Кнопки на выбранной вкладке", padding=6)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        list_frame = ttk.Frame(right)
        list_frame.pack(fill=tk.BOTH, expand=True)
        scroll = ttk.Scrollbar(list_frame)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.lb = tk.Listbox(list_frame, yscrollcommand=scroll.set, height=14, font=("Segoe UI", 10))
        self.lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.config(command=self.lb.yview)
        self.lb.bind("<Control-c>", self._copy_list_line)
        btns = ttk.Frame(right)
        btns.pack(fill=tk.X, pady=(6, 0))
        ttk.Button(btns, text="Добавить", command=self._add).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(btns, text="Изменить", command=self._edit).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(btns, text="Удалить", command=self._delete).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(btns, text="Вверх", command=lambda: self._move(-1)).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(btns, text="Вниз", command=lambda: self._move(1)).pack(side=tk.LEFT)

        ui_fr = ttk.LabelFrame(frm, text="Внешний вид главного окна", padding=8)
        ui_fr.pack(fill=tk.X, pady=(8, 0))
        u1 = ttk.Frame(ui_fr)
        u1.pack(fill=tk.X)
        ttk.Label(u1, text="Размер шрифта кнопок:").pack(side=tk.LEFT)
        self._v_font = tk.StringVar(value=str(int(ui.get("button_font_size", 11))))
        ttk.Spinbox(u1, from_=8, to=24, width=5, textvariable=self._v_font).pack(side=tk.LEFT, padx=(6, 16))
        ttk.Label(u1, text="Отступ X / Y:").pack(side=tk.LEFT)
        self._v_padx = tk.StringVar(value=str(int(ui.get("button_pad_x", 6))))
        ttk.Spinbox(u1, from_=0, to=24, width=4, textvariable=self._v_padx).pack(side=tk.LEFT, padx=(6, 4))
        self._v_pady = tk.StringVar(value=str(int(ui.get("button_pad_y", 6))))
        ttk.Spinbox(u1, from_=0, to=24, width=4, textvariable=self._v_pady).pack(side=tk.LEFT, padx=(0, 16))
        ttk.Label(u1, text="Колонок:").pack(side=tk.LEFT)
        self._v_cols = tk.StringVar(value=str(int(ui.get("columns", 2))))
        ttk.Spinbox(u1, from_=1, to=6, width=4, textvariable=self._v_cols).pack(side=tk.LEFT, padx=(6, 16))
        ttk.Label(u1, text="Кнопок на странице (0 = все):").pack(side=tk.LEFT)
        self._v_pp = tk.StringVar(value=str(int(ui.get("buttons_per_page", 0) or 0)))
        ttk.Spinbox(u1, from_=0, to=48, width=4, textvariable=self._v_pp).pack(side=tk.LEFT, padx=(6, 0))

        bottom = ttk.Frame(frm)
        bottom.pack(fill=tk.X, pady=(12, 0))
        ttk.Button(bottom, text="Сохранить", command=self._save).pack(side=tk.RIGHT, padx=(6, 0))
        ttk.Button(bottom, text="Отмена", command=self.destroy).pack(side=tk.RIGHT)
        self.geometry("720x620")
        self.grab_set()
        self._refresh_tab_list(select=0)
        self.after(10, self._editor_ready)

    def _editor_ready(self) -> None:
        self.lift()
        self.focus_force()
        try:
            self.attributes("-topmost", True)
            self.after(200, lambda: self.attributes("-topmost", False))
        except tk.TclError:
            pass

    def _items(self) -> list[dict[str, Any]]:
        return self.tabs[self.tab_idx]["buttons"]

    def _refresh_tab_list(self, select: int | None = None) -> None:
        self.tab_lb.delete(0, tk.END)
        for t in self.tabs:
            self.tab_lb.insert(tk.END, t.get("title", "?"))
        if self.tabs:
            i = 0 if select is None else max(0, min(select, len(self.tabs) - 1))
            self.tab_idx = i
            self.tab_lb.selection_clear(0, tk.END)
            self.tab_lb.selection_set(i)
            self.tab_lb.see(i)
        self._refresh_button_list()

    def _on_tab_select(self, _evt: tk.Event | None = None) -> None:
        sel = self.tab_lb.curselection()
        if not sel:
            return
        self.tab_idx = int(sel[0])
        self._refresh_button_list()

    def _add_tab(self) -> None:
        name = simpledialog.askstring("Новая вкладка", "Имя вкладки:", parent=self)
        if not name or not str(name).strip():
            return
        self.tabs.append({"title": str(name).strip(), "buttons": []})
        self._refresh_tab_list(select=len(self.tabs) - 1)

    def _rename_tab(self) -> None:
        if not self.tabs:
            return
        cur = str(self.tabs[self.tab_idx].get("title", ""))
        name = simpledialog.askstring("Переименовать", "Имя вкладки:", initialvalue=cur, parent=self)
        if name is None or not str(name).strip():
            return
        self.tabs[self.tab_idx]["title"] = str(name).strip()
        self._refresh_tab_list(select=self.tab_idx)

    def _delete_tab(self) -> None:
        if len(self.tabs) <= 1:
            messagebox.showinfo("Вкладки", "Нужна хотя бы одна вкладка.", parent=self)
            return
        del self.tabs[self.tab_idx]
        self.tab_idx = min(self.tab_idx, len(self.tabs) - 1)
        self._refresh_tab_list(select=self.tab_idx)

    def _move_tab(self, delta: int) -> None:
        j = self.tab_idx + delta
        if j < 0 or j >= len(self.tabs):
            return
        self.tabs[self.tab_idx], self.tabs[j] = self.tabs[j], self.tabs[self.tab_idx]
        self.tab_idx = j
        self._refresh_tab_list(select=j)

    def _copy_list_line(self, _event: tk.Event | None = None) -> str:
        i = self._sel_index()
        if i is None:
            return "break"
        try:
            self.clipboard_clear()
            self.clipboard_append(self.lb.get(i))
        except tk.TclError:
            pass
        return "break"

    def _line(self, b: dict[str, Any]) -> str:
        lab = b.get("label", "")
        dom = b.get("domain", "")
        svc = b.get("service", "")
        sd = b.get("service_data")
        eid = ""
        if isinstance(sd, dict):
            eid = str(sd.get("entity_id", "") or "")
        if not eid:
            eid = str(b.get("entity_id", "") or "")
        if eid:
            return f"{lab}  →  {dom}.{svc}  ({eid})"
        return f"{lab}  →  {dom}.{svc}"

    def _refresh_button_list(self) -> None:
        self.lb.delete(0, tk.END)
        for b in self._items():
            self.lb.insert(tk.END, self._line(b))

    def _sel_index(self) -> int | None:
        sel = self.lb.curselection()
        return int(sel[0]) if sel else None

    def _add(self) -> None:
        items = self._items()

        def on_ok(row: dict[str, Any]) -> None:
            items.append(row)
            self._refresh_button_list()
            self.lb.selection_clear(0, tk.END)
            self.lb.selection_set(tk.END)
            self.lb.see(tk.END)

        ButtonItemDialog(self, "Новая кнопка", None, on_ok, self.cfg)

    def _edit(self) -> None:
        items = self._items()
        i = self._sel_index()
        if i is None:
            messagebox.showinfo("Изменить", "Выберите строку в списке.", parent=self)
            return

        def on_ok(row: dict[str, Any]) -> None:
            items[i] = row
            self._refresh_button_list()
            self.lb.selection_set(i)

        ButtonItemDialog(self, "Кнопка", items[i], on_ok, self.cfg)

    def _delete(self) -> None:
        items = self._items()
        i = self._sel_index()
        if i is None:
            return
        del items[i]
        self._refresh_button_list()

    def _move(self, delta: int) -> None:
        items = self._items()
        i = self._sel_index()
        if i is None:
            return
        j = i + delta
        if j < 0 or j >= len(items):
            return
        items[i], items[j] = items[j], items[i]
        self._refresh_button_list()
        self.lb.selection_set(j)
        self.lb.see(j)

    def _save(self) -> None:
        try:
            fs = int(self._v_font.get().strip())
            cl = int(self._v_cols.get().strip())
            pp = int(self._v_pp.get().strip())
            px = int(self._v_padx.get().strip())
            py_ = int(self._v_pady.get().strip())
        except ValueError:
            messagebox.showwarning(
                "Проверка", "Размер шрифта, отступы, колонки и страница — целые числа.", parent=self
            )
            return
        fs = max(8, min(24, fs))
        cl = max(1, min(6, cl))
        pp = max(0, min(48, pp))
        px = max(0, min(24, px))
        py_ = max(0, min(24, py_))
        merge_ui_defaults(self.cfg)
        u = self.cfg["ui"]
        u["button_font_size"] = fs
        u["button_pad_x"] = px
        u["button_pad_y"] = py_
        u["columns"] = cl
        u["buttons_per_page"] = pp

        self.cfg["button_tabs"] = [
            {"title": str(t.get("title", "Вкладка")), "buttons": [dict(b) for b in t.get("buttons", [])]}
            for t in self.tabs
        ]
        if self.tabs:
            self.cfg["buttons"] = [dict(b) for b in self.tabs[0]["buttons"]]
        else:
            self.cfg["buttons"] = []
        save_config(self.cfg)
        self.on_saved()
        messagebox.showinfo("Сохранено", "Вкладки и настройки записаны в config.json.", parent=self)
        self.destroy()


class SensorItemAppearanceDialog(tk.Toplevel):
    """Имя и иконка для одной строки панели датчиков."""

    _ICON_PRESETS = (
        "",
        "🌡",
        "💧",
        "☀️",
        "🌙",
        "🏠",
        "⚡",
        "📶",
        "🔔",
        "🌬",
        "💡",
        "🔒",
        "🌤",
        "📊",
        "mdi:thermometer",
        "mdi:humidity",
        "mdi:weather-partly-cloudy",
        "mdi:home-thermometer",
    )

    def __init__(
        self,
        parent: tk.Widget,
        entity_id: str,
        label: str,
        icon: str,
        on_save: Callable[[str, str], None],
    ):
        super().__init__(parent)
        self.title("Имя и иконка")
        self.entity_id = entity_id
        self.on_save = on_save
        self.transient(parent.winfo_toplevel())

        frm = ttk.Frame(self, padding=12)
        frm.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frm, text=f"Сущность: {entity_id}", font=("Segoe UI", 9), foreground="#444").grid(
            row=0, column=0, columnspan=2, sticky=tk.W, pady=(0, 10)
        )

        ttk.Label(frm, text="Имя на панели (пусто — взять из Home Assistant):").grid(
            row=1, column=0, columnspan=2, sticky=tk.W
        )
        self.name_var = tk.StringVar(value=label)
        self.name_entry = tk.Entry(frm, textvariable=self.name_var, width=48, font=("Segoe UI", 10))
        self.name_entry.grid(row=2, column=0, columnspan=2, sticky=tk.EW, pady=(0, 12))

        ttk.Label(
            frm,
            text="Иконка: эмодзи или mdi:… (как в HA). Можно выбрать из списка или ввести свою:",
        ).grid(row=3, column=0, columnspan=2, sticky=tk.W)
        self.icon_var = tk.StringVar(value=icon)
        self.icon_cb = ttk.Combobox(
            frm,
            textvariable=self.icon_var,
            values=self._ICON_PRESETS,
            width=46,
            font=("Segoe UI", 11),
        )
        self.icon_cb.grid(row=4, column=0, columnspan=2, sticky=tk.EW, pady=(0, 8))

        ha_row = ttk.Frame(frm)
        ha_row.grid(row=5, column=0, columnspan=2, sticky=tk.W, pady=(0, 12))
        ttk.Button(ha_row, text="Подставить имя и иконку из Home Assistant", command=self._from_ha).pack(
            side=tk.LEFT
        )

        btn_row = ttk.Frame(frm)
        btn_row.grid(row=6, column=0, columnspan=2, sticky=tk.EW)
        ttk.Button(btn_row, text="OK", command=self._ok).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(btn_row, text="Отмена", command=self.destroy).pack(side=tk.LEFT)

        frm.columnconfigure(0, weight=1)
        self.geometry("520x320")
        self.grab_set()
        self.after(10, self._ready)

    def _ready(self) -> None:
        self.lift()
        self.focus_force()
        try:
            self.attributes("-topmost", True)
            self.after(200, lambda: self.attributes("-topmost", False))
        except tk.TclError:
            pass
        self.name_entry.focus_set()
        setup_entry_paste(self.name_entry)

    def _from_ha(self) -> None:
        eid = self.entity_id

        def work() -> None:
            ok, err, st = fetch_entity_state(load_config(), eid)

            def done() -> None:
                try:
                    if not self.winfo_exists():
                        return
                except tk.TclError:
                    return
                if not ok or not st:
                    messagebox.showwarning("Home Assistant", err or "Нет ответа", parent=self)
                    return
                attrs = st.get("attributes")
                if isinstance(attrs, dict):
                    ic = attrs.get("icon")
                    if isinstance(ic, str) and ic.strip():
                        self.icon_var.set(ic.strip())
                fn = _friendly_name(st)
                if fn and not self.name_var.get().strip():
                    self.name_var.set(fn)

            self.after(0, done)

        threading.Thread(target=work, daemon=True).start()

    def _ok(self) -> None:
        self.on_save(self.name_var.get().strip(), self.icon_var.get().strip())
        self.destroy()


class SensorsPanelEditorDialog(tk.Toplevel):
    """Вкладки датчиков, список сущностей на вкладке и оформление (сетка, шрифты)."""

    def __init__(self, parent: tk.Tk, cfg: dict[str, Any], on_saved: Callable[[], None]):
        super().__init__(parent)
        self.title("Датчики на главном окне")
        self.cfg = cfg
        self.on_saved = on_saved
        self.transient(parent)

        self.tabs: list[dict[str, Any]] = [normalize_sensor_tab(dict(t)) for t in get_sensor_tabs(cfg)]
        self.tab_idx = 0

        self._refresh_sec = tk.StringVar(value=str(int(cfg.get("sensor_refresh_seconds", 60) or 60)))
        self._v_cols = tk.StringVar(value="1")
        self._item_layout_var = tk.StringVar(value="row")
        self._v_icon = tk.StringVar(value="16")
        self._v_lab = tk.StringVar(value="10")
        self._v_val = tk.StringVar(value="11")
        self._v_lw = tk.StringVar(value="22")

        frm = ttk.Frame(self, padding=10)
        frm.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            frm,
            text="Вкладки — как группы датчиков на главном окне. Для каждой сущности можно задать имя и иконку. "
            "Сетка: сколько датчиков в ряд; «в столбик» — иконка, имя и значение друг под другом в ячейке.",
            wraplength=640,
            justify=tk.LEFT,
            font=("Segoe UI", 9),
        ).pack(anchor=tk.W, pady=(0, 8))

        row_sec = ttk.Frame(frm)
        row_sec.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(row_sec, text="Обновлять значения каждые (секунд):").pack(side=tk.LEFT, padx=(0, 8))
        ttk.Spinbox(row_sec, from_=15, to=3600, width=8, textvariable=self._refresh_sec).pack(side=tk.LEFT)

        mid = ttk.Frame(frm)
        mid.pack(fill=tk.BOTH, expand=True, pady=4)
        left = ttk.LabelFrame(mid, text="Вкладки", padding=6)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 8))
        self.tab_lb = tk.Listbox(left, height=7, width=20, exportselection=False, font=("Segoe UI", 10))
        self.tab_lb.pack(fill=tk.BOTH, expand=True)
        self.tab_lb.bind("<<ListboxSelect>>", self._on_tab_select)
        tbf = ttk.Frame(left)
        tbf.pack(fill=tk.X, pady=(6, 0))
        ttk.Button(tbf, text="+", width=3, command=self._add_tab).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(tbf, text="Имя", command=self._rename_tab).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(tbf, text="−", width=3, command=self._delete_tab).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(tbf, text="↑", width=3, command=lambda: self._move_tab(-1)).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(tbf, text="↓", width=3, command=lambda: self._move_tab(1)).pack(side=tk.LEFT)

        right = ttk.Frame(mid)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        ap_fr = ttk.LabelFrame(right, text="Оформление выбранной вкладки", padding=8)
        ap_fr.pack(fill=tk.X, pady=(0, 8))
        r1 = ttk.Frame(ap_fr)
        r1.pack(fill=tk.X)
        ttk.Label(r1, text="Колонок сетки (в ряд):").pack(side=tk.LEFT)
        ttk.Spinbox(r1, from_=1, to=8, width=4, textvariable=self._v_cols).pack(side=tk.LEFT, padx=(6, 16))
        ttk.Label(r1, text="Иконка (pt):").pack(side=tk.LEFT)
        ttk.Spinbox(r1, from_=8, to=36, width=4, textvariable=self._v_icon).pack(side=tk.LEFT, padx=(6, 16))
        ttk.Label(r1, text="Имя (pt):").pack(side=tk.LEFT)
        ttk.Spinbox(r1, from_=7, to=20, width=4, textvariable=self._v_lab).pack(side=tk.LEFT, padx=(6, 16))
        ttk.Label(r1, text="Значение (pt):").pack(side=tk.LEFT)
        ttk.Spinbox(r1, from_=7, to=22, width=4, textvariable=self._v_val).pack(side=tk.LEFT, padx=(6, 16))
        r2 = ttk.Frame(ap_fr)
        r2.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(r2, text="Ширина имени (симв.):").pack(side=tk.LEFT)
        ttk.Spinbox(r2, from_=4, to=48, width=4, textvariable=self._v_lw).pack(side=tk.LEFT, padx=(6, 24))
        ttk.Label(r2, text="Ячейка датчика:").pack(side=tk.LEFT)
        ttk.Radiobutton(
            r2, text="в строку", variable=self._item_layout_var, value="row"
        ).pack(side=tk.LEFT, padx=(6, 4))
        ttk.Radiobutton(
            r2, text="в столбик", variable=self._item_layout_var, value="column"
        ).pack(side=tk.LEFT)

        ttk.Label(right, text="Датчики на вкладке (порядок = порядок в сетке по строкам):", font=("Segoe UI", 10, "bold")).pack(
            anchor=tk.W
        )
        list_frame = ttk.Frame(right)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=6)
        scroll = ttk.Scrollbar(list_frame)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.lb = tk.Listbox(list_frame, yscrollcommand=scroll.set, height=10, font=("Segoe UI", 10))
        self.lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.config(command=self.lb.yview)

        btns = ttk.Frame(right)
        btns.pack(fill=tk.X, pady=4)
        ttk.Button(btns, text="Добавить из HA…", command=self._add).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(btns, text="Имя и иконка…", command=self._edit_appearance).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(btns, text="Удалить", command=self._delete).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(btns, text="Вверх", command=lambda: self._move(-1)).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(btns, text="Вниз", command=lambda: self._move(1)).pack(side=tk.LEFT, padx=(0, 6))

        bottom = ttk.Frame(frm)
        bottom.pack(fill=tk.X, pady=(10, 0))
        ttk.Button(bottom, text="Сохранить", command=self._save).pack(side=tk.RIGHT, padx=(6, 0))
        ttk.Button(bottom, text="Отмена", command=self.destroy).pack(side=tk.RIGHT)

        self.geometry("700x640")
        self.grab_set()
        self._refresh_tab_list(select=0)
        self.after(10, self._ready)

    def _ready(self) -> None:
        self.lift()
        self.focus_force()
        try:
            self.attributes("-topmost", True)
            self.after(200, lambda: self.attributes("-topmost", False))
        except tk.TclError:
            pass

    def _sensors(self) -> list[dict[str, str]]:
        return self.tabs[self.tab_idx]["sensors"]

    def _flush_appearance_to_tab(self, idx: int) -> None:
        if idx < 0 or idx >= len(self.tabs):
            return
        t = self.tabs[idx]
        try:
            t["columns"] = max(1, min(8, int(self._v_cols.get().strip())))
            t["icon_size"] = max(8, min(36, int(self._v_icon.get().strip())))
            t["label_font_size"] = max(7, min(20, int(self._v_lab.get().strip())))
            t["value_font_size"] = max(7, min(22, int(self._v_val.get().strip())))
            t["label_width_chars"] = max(4, min(48, int(self._v_lw.get().strip())))
        except ValueError:
            pass
        il = self._item_layout_var.get()
        t["item_layout"] = "column" if il == "column" else "row"

    def _load_appearance_from_tab(self, idx: int) -> None:
        t = self.tabs[idx]
        self._v_cols.set(str(int(t["columns"])))
        self._v_icon.set(str(int(t["icon_size"])))
        self._v_lab.set(str(int(t["label_font_size"])))
        self._v_val.set(str(int(t["value_font_size"])))
        self._v_lw.set(str(int(t["label_width_chars"])))
        self._item_layout_var.set(str(t.get("item_layout", "row")))

    def _refresh_tab_list(self, select: int | None = None) -> None:
        self.tab_lb.delete(0, tk.END)
        for t in self.tabs:
            self.tab_lb.insert(tk.END, t.get("title", "?"))
        if self.tabs:
            i = 0 if select is None else max(0, min(select, len(self.tabs) - 1))
            self.tab_idx = i
            self.tab_lb.selection_clear(0, tk.END)
            self.tab_lb.selection_set(i)
            self.tab_lb.see(i)
        self._load_appearance_from_tab(self.tab_idx)
        self._refresh_sensor_list()

    def _on_tab_select(self, _evt: tk.Event | None = None) -> None:
        self._flush_appearance_to_tab(self.tab_idx)
        sel = self.tab_lb.curselection()
        if not sel:
            return
        self.tab_idx = int(sel[0])
        self._load_appearance_from_tab(self.tab_idx)
        self._refresh_sensor_list()

    def _add_tab(self) -> None:
        name = simpledialog.askstring("Новая вкладка", "Имя вкладки:", parent=self)
        if not name or not str(name).strip():
            return
        self.tabs.append(
            normalize_sensor_tab({"title": str(name).strip(), "sensors": []})
        )
        self._refresh_tab_list(select=len(self.tabs) - 1)

    def _rename_tab(self) -> None:
        if not self.tabs:
            return
        cur = str(self.tabs[self.tab_idx].get("title", ""))
        name = simpledialog.askstring("Переименовать", "Имя вкладки:", initialvalue=cur, parent=self)
        if name is None or not str(name).strip():
            return
        self.tabs[self.tab_idx]["title"] = str(name).strip()
        self._refresh_tab_list(select=self.tab_idx)

    def _delete_tab(self) -> None:
        if len(self.tabs) <= 1:
            messagebox.showinfo("Вкладки", "Нужна хотя бы одна вкладка.", parent=self)
            return
        del self.tabs[self.tab_idx]
        self.tab_idx = min(self.tab_idx, len(self.tabs) - 1)
        self._refresh_tab_list(select=self.tab_idx)

    def _move_tab(self, delta: int) -> None:
        j = self.tab_idx + delta
        if j < 0 or j >= len(self.tabs):
            return
        self.tabs[self.tab_idx], self.tabs[j] = self.tabs[j], self.tabs[self.tab_idx]
        self.tab_idx = j
        self._refresh_tab_list(select=j)

    def _line(self, it: dict[str, str]) -> str:
        lab = it.get("label", "").strip()
        ic = it.get("icon", "").strip()
        eid = it.get("entity_id", "")
        prefix = f"{ic}  " if ic else ""
        if lab:
            return f"{prefix}{lab}  —  {eid}"
        return f"{prefix}{eid}"

    def _refresh_sensor_list(self) -> None:
        self.lb.delete(0, tk.END)
        for it in self._sensors():
            self.lb.insert(tk.END, self._line(it))

    def _sel_index(self) -> int | None:
        sel = self.lb.curselection()
        return int(sel[0]) if sel else None

    def _add(self) -> None:
        items = self._sensors()

        def on_pick(entity_id: str, domain: str, friendly: str) -> None:
            for it in items:
                if it.get("entity_id") == entity_id:
                    messagebox.showinfo("Датчики", "Эта сущность уже на этой вкладке.", parent=self)
                    return
            items.append(
                {
                    "entity_id": entity_id,
                    "label": friendly.strip() if friendly else "",
                    "icon": "",
                }
            )
            self._refresh_sensor_list()
            self.lb.selection_clear(0, tk.END)
            self.lb.selection_set(tk.END)
            self.lb.see(tk.END)

        EntityPickerDialog(self, load_config(), on_pick)

    def _edit_appearance(self) -> None:
        items = self._sensors()
        i = self._sel_index()
        if i is None:
            messagebox.showinfo("Имя и иконка", "Выберите строку в списке.", parent=self)
            return
        it = items[i]

        def on_save(name: str, icon: str) -> None:
            it["label"] = name
            it["icon"] = icon
            self._refresh_sensor_list()
            self.lb.selection_set(i)

        SensorItemAppearanceDialog(
            self,
            str(it.get("entity_id", "")),
            str(it.get("label", "")),
            str(it.get("icon", "")),
            on_save,
        )

    def _delete(self) -> None:
        items = self._sensors()
        i = self._sel_index()
        if i is None:
            return
        del items[i]
        self._refresh_sensor_list()

    def _move(self, delta: int) -> None:
        items = self._sensors()
        i = self._sel_index()
        if i is None:
            return
        j = i + delta
        if j < 0 or j >= len(items):
            return
        items[i], items[j] = items[j], items[i]
        self._refresh_sensor_list()
        self.lb.selection_set(j)
        self.lb.see(j)

    def _save(self) -> None:
        self._flush_appearance_to_tab(self.tab_idx)
        try:
            sec = int(self._refresh_sec.get().strip())
        except ValueError:
            messagebox.showwarning("Интервал", "Укажите целое число секунд.", parent=self)
            return
        sec = max(15, min(3600, sec))
        self.cfg["sensor_refresh_seconds"] = sec
        exported: list[dict[str, Any]] = []
        for t in self.tabs:
            exported.append(
                normalize_sensor_tab(
                    {
                        "title": t.get("title", "Вкладка"),
                        "columns": t.get("columns", 1),
                        "item_layout": t.get("item_layout", "row"),
                        "icon_size": t.get("icon_size", 16),
                        "label_font_size": t.get("label_font_size", 10),
                        "value_font_size": t.get("value_font_size", 11),
                        "label_width_chars": t.get("label_width_chars", 22),
                        "sensors": [dict(s) for s in t.get("sensors", [])],
                    }
                )
            )
        self.cfg["sensor_tabs"] = exported
        if self.tabs:
            self.cfg["sensor_panel"] = [dict(s) for s in self.tabs[0]["sensors"]]
        else:
            self.cfg["sensor_panel"] = []
        save_config(self.cfg)
        self.on_saved()
        messagebox.showinfo("Сохранено", "Вкладки и датчики записаны в config.json.", parent=self)
        self.destroy()


class ConnectionDialog(tk.Toplevel):
    def __init__(self, parent: tk.Tk, cfg: dict[str, Any], on_save):
        super().__init__(parent)
        self.title("Подключение к Home Assistant")
        self.cfg = cfg
        self.on_save = on_save
        self.transient(parent)

        frm = ttk.Frame(self, padding=12)
        frm.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frm, text="URL сервера (например https://192.168.1.10:8123):").grid(
            row=0, column=0, columnspan=2, sticky=tk.W, pady=(0, 4)
        )
        url_line = ttk.Frame(frm)
        url_line.grid(row=1, column=0, columnspan=2, sticky=tk.EW, pady=(0, 10))
        url_line.columnconfigure(0, weight=1)
        self.url_var = tk.StringVar(value=cfg.get("ha_url", ""))
        self.url_entry = tk.Entry(url_line, textvariable=self.url_var, font=("Segoe UI", 10))
        self.url_entry.grid(row=0, column=0, sticky=tk.EW, padx=(0, 8))
        ttk.Button(url_line, text="Из буфера", command=self._paste_url).grid(row=0, column=1)

        ttk.Label(frm, text="Long-Lived Access Token:").grid(
            row=2, column=0, columnspan=2, sticky=tk.W, pady=(0, 4)
        )
        tok_line = ttk.Frame(frm)
        tok_line.grid(row=3, column=0, columnspan=2, sticky=tk.EW, pady=(0, 8))
        tok_line.columnconfigure(0, weight=1)
        self.token_var = tk.StringVar(value=cfg.get("ha_token", ""))
        self.token_entry = tk.Entry(tok_line, textvariable=self.token_var, show="*", font=("Segoe UI", 10))
        self.token_entry.grid(row=0, column=0, sticky=tk.EW, padx=(0, 8))
        ttk.Button(tok_line, text="Из буфера", command=self._paste_token).grid(row=0, column=1)

        self.verify_var = tk.BooleanVar(value=bool(cfg.get("verify_ssl", True)))
        ttk.Checkbutton(
            frm,
            text="Проверять SSL-сертификат (снимите при самоподписанном HTTPS)",
            variable=self.verify_var,
        ).grid(row=4, column=0, columnspan=2, sticky=tk.W, pady=(0, 8))

        ttk.Label(
            frm,
            text="Вставка: Ctrl+V, Shift+Insert или ПКМ по полю → «Вставить». "
            "Если горячие клавиши не срабатывают — скопируйте в браузере и нажмите «Из буфера».",
            wraplength=540,
            justify=tk.LEFT,
            font=("Segoe UI", 9),
            foreground="#444",
        ).grid(row=5, column=0, columnspan=2, sticky=tk.W, pady=(0, 10))

        btn_row = ttk.Frame(frm)
        btn_row.grid(row=6, column=0, columnspan=2, sticky=tk.EW)
        ttk.Button(btn_row, text="Проверить", command=self._test).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(btn_row, text="Сохранить", command=self._save).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(btn_row, text="Отмена", command=self.destroy).pack(side=tk.LEFT)

        frm.columnconfigure(0, weight=1)
        self.geometry("600x380")

        setup_entry_paste(self.url_entry)
        setup_entry_paste(self.token_entry)

        self.grab_set()
        self.after(10, self._dialog_ready)

    def _dialog_ready(self) -> None:
        self.lift()
        self.focus_force()
        try:
            self.attributes("-topmost", True)
            self.after(200, lambda: self.attributes("-topmost", False))
        except tk.TclError:
            pass
        self.url_entry.focus_set()

    def _paste_url(self) -> None:
        t = _clipboard_text(self)
        if not t:
            messagebox.showwarning(
                "Буфер обмена",
                "Буфер пуст или недоступен.\n\nСкопируйте адрес Home Assistant и нажмите «Из буфера» снова.",
                parent=self,
            )
            return
        line = t.strip().splitlines()[0].strip()
        self.url_var.set(line)

    def _paste_token(self) -> None:
        t = _clipboard_text(self)
        if not t:
            messagebox.showwarning(
                "Буфер обмена",
                "Буфер пуст.\n\nСкопируйте токен на странице профиля HA и нажмите «Из буфера» снова.",
                parent=self,
            )
            return
        self.token_var.set(_clean_token(t))

    def _test(self) -> None:
        test_cfg = {
            "ha_url": self.url_var.get(),
            "ha_token": self.token_var.get(),
            "verify_ssl": self.verify_var.get(),
        }
        ok, msg = check_ha_connection(test_cfg)
        if ok:
            messagebox.showinfo("Проверка", msg, parent=self)
        else:
            messagebox.showerror("Подключение не удалось", msg, parent=self)

    def _save(self) -> None:
        raw = self.url_var.get().strip()
        self.cfg["ha_url"] = api_root_url(raw) or normalize_base_url(raw)
        self.cfg["ha_token"] = _clean_token(self.token_var.get())
        self.cfg["verify_ssl"] = bool(self.verify_var.get())
        save_config(self.cfg)
        self.on_save()
        self.destroy()
class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("HA Quick Actions")
        self.minsize(400, 320)
        self.geometry("520x460")
        self.cfg: dict[str, Any] = load_config()
        self._tray_icon: Any = None
        self._tray_thread: threading.Thread | None = None
        self._sensor_after_id: str | None = None
        self._sensor_refs: list[tuple[str, str, str, tk.StringVar, tk.StringVar, tk.StringVar]] = []
        self._autostart_var = tk.BooleanVar(value=autostart_enabled())
        self._close_tray_var = tk.BooleanVar(value=bool(self.cfg.get("close_to_tray", True)))
        self._start_min_var = tk.BooleanVar(value=bool(self.cfg.get("start_minimized", False)))
        menubar = tk.Menu(self)
        self.config(menu=menubar)
        m_file = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Файл", menu=m_file)
        m_file.add_command(label="Подключение…", command=self._open_connection)
        m_file.add_command(label="Датчики на главной…", command=self._open_sensors_editor)
        m_file.add_command(label="Редактор кнопок…", command=self._open_editor)
        m_file.add_command(label="Перезагрузить из config…", command=self._reload_from_config)
        m_file.add_separator()
        m_file.add_checkbutton(
            label="Сворачивать в трей при закрытии окна",
            variable=self._close_tray_var,
            command=self._toggle_close_tray,
        )
        m_file.add_checkbutton(
            label="Запускать свёрнуто в трей",
            variable=self._start_min_var,
            command=self._toggle_start_min,
        )
        if sys.platform == "win32":
            m_file.add_checkbutton(
                label="Автозапуск Windows",
                variable=self._autostart_var,
                command=self._toggle_autostart,
            )
        m_file.add_separator()
        m_file.add_command(label="Открыть папку с config.json", command=self._open_config_dir)
        m_file.add_separator()
        m_file.add_command(label="Выход", command=self._quit_app)
        self.sensor_host = ttk.Frame(self)
        self.sensor_host.pack(fill=tk.X, padx=8, pady=(8, 0))
        self._rebuild_sensor_panel()
        self.main_frame = ttk.Frame(self, padding=10)
        self.main_frame.pack(fill=tk.BOTH, expand=True)
        self.status = tk.StringVar(value="Готово")
        status_bar = ttk.Label(self, textvariable=self.status, relief=tk.SUNKEN, anchor=tk.W)
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)
        self.protocol("WM_DELETE_WINDOW", self._on_user_close)
        self.bind("<Unmap>", self._on_unmap)
        self._rebuild_buttons()
        self._setup_tray()
        if self._start_min_var.get() and _TRAY_OK and self._tray_icon:
            self.after(200, self._hide_to_tray)
    def _toggle_close_tray(self) -> None:
        self.cfg["close_to_tray"] = self._close_tray_var.get()
        save_config(self.cfg)
    def _toggle_start_min(self) -> None:
        self.cfg["start_minimized"] = self._start_min_var.get()
        save_config(self.cfg)
    def _toggle_autostart(self) -> None:
        ok, err = set_autostart(self._autostart_var.get())
        if not ok:
            self._autostart_var.set(not self._autostart_var.get())
            messagebox.showerror("Автозапуск", err or "Не удалось изменить автозапуск")
    def _setup_tray(self) -> None:
        if not _TRAY_OK or pystray is None:
            self._close_tray_var.set(False)
            self.cfg["close_to_tray"] = False
            self._start_min_var.set(False)
            self.cfg["start_minimized"] = False
            save_config(self.cfg)
            return
        image = tray_icon_image()
        def show(_: Any = None) -> None:
            self.after(0, self._show_window)
        def quit_app(_: Any = None) -> None:
            self.after(0, self._quit_app)
        menu = pystray.Menu(
            pystray.MenuItem("Показать окно", show, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Выход", quit_app),
        )
        self._tray_icon = pystray.Icon("ha_quick_actions", image, "HA Quick Actions", menu)
        def run_icon() -> None:
            self._tray_icon.run()
        self._tray_thread = threading.Thread(target=run_icon, daemon=True)
        self._tray_thread.start()
    def _on_unmap(self, event: tk.Event) -> None:
        if event.widget is not self:
            return
        if not _TRAY_OK or not self._close_tray_var.get() or not self._tray_icon:
            return
        if self.state() == "iconic":
            self.after(80, self._hide_to_tray)
    def _hide_to_tray(self) -> None:
        if not _TRAY_OK:
            return
        self.withdraw()
    def _show_window(self) -> None:
        self.deiconify()
        self.state("normal")
        self.lift()
        self.focus_force()
    def _on_user_close(self) -> None:
        if _TRAY_OK and self._close_tray_var.get() and self._tray_icon:
            self.withdraw()
        else:
            self._quit_app()
    def _quit_app(self) -> None:
        self._cancel_sensor_timer()
        if self._tray_icon:
            try:
                self._tray_icon.stop()
            except Exception:
                pass
            self._tray_icon = None
        self.destroy()

    def _open_connection(self) -> None:
        self.cfg = load_config()
        ConnectionDialog(self, self.cfg, on_save=self._on_connection_saved)

    def _on_connection_saved(self) -> None:
        self.status.set("Настройки сохранены")
        self.cfg = load_config()
        self._rebuild_sensor_panel()

    def _open_sensors_editor(self) -> None:
        self.cfg = load_config()
        SensorsPanelEditorDialog(self, self.cfg, on_saved=self._on_sensors_saved)

    def _on_sensors_saved(self) -> None:
        self.cfg = load_config()
        self._rebuild_sensor_panel()

    def _cancel_sensor_timer(self) -> None:
        if self._sensor_after_id is not None:
            try:
                self.after_cancel(self._sensor_after_id)
            except tk.TclError:
                pass
            self._sensor_after_id = None

    def _sensor_refresh_ms(self) -> int:
        try:
            sec = int(load_config().get("sensor_refresh_seconds", 60))
        except (TypeError, ValueError):
            sec = 60
        return max(15, min(3600, sec)) * 1000

    def _toggle_sensor_panel(self) -> None:
        self.cfg = load_config()
        merge_ui_defaults(self.cfg)
        u = self.cfg["ui"]
        u["sensor_panel_collapsed"] = not bool(u.get("sensor_panel_collapsed", False))
        save_config(self.cfg)
        self._rebuild_sensor_panel()

    def _rebuild_sensor_panel(self) -> None:
        self._cancel_sensor_timer()
        for w in self.sensor_host.winfo_children():
            w.destroy()
        self._sensor_refs = []
        self.cfg = load_config()
        ui = get_ui_settings(self.cfg)
        collapsed = bool(ui.get("sensor_panel_collapsed", False))

        head = ttk.Frame(self.sensor_host)
        head.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(head, text="Показания с Home Assistant", font=("Segoe UI", 10, "bold")).pack(
            side=tk.LEFT, anchor=tk.W
        )
        if collapsed:
            ttk.Button(head, text="Развернуть ▼", width=14, command=self._toggle_sensor_panel).pack(
                side=tk.RIGHT
            )
            return
        ttk.Button(head, text="Свернуть ▲", width=14, command=self._toggle_sensor_panel).pack(side=tk.RIGHT)

        body = ttk.Frame(self.sensor_host)
        body.pack(fill=tk.BOTH, expand=True)
        tool = ttk.Frame(body)
        tool.pack(fill=tk.X, pady=(0, 4))
        ttk.Button(tool, text="Обновить сейчас", command=self._sensor_refresh_now).pack(side=tk.LEFT)

        tabs_data = get_sensor_tabs(self.cfg)
        total_any = any(len(t.get("sensors", [])) > 0 for t in tabs_data)
        if not total_any:
            ttk.Label(
                body,
                text="Панель датчиков пуста — добавьте сущности: «Файл → Датчики на главной…»",
                font=("Segoe UI", 9),
                foreground="#555",
            ).pack(anchor=tk.W, pady=(0, 2))
            return

        nb = ttk.Notebook(body)
        nb.pack(fill=tk.BOTH, expand=True)
        for tab in tabs_data:
            outer = ttk.Frame(nb, padding=(4, 6))
            nb.add(outer, text=str(tab.get("title", "Вкладка")))
            ents = tab.get("sensors") or []
            if not ents:
                ttk.Label(
                    outer,
                    text="На этой вкладке нет датчиков — добавьте их в редакторе.",
                    font=("Segoe UI", 9),
                    foreground="#666",
                ).pack(anchor=tk.CENTER, pady=12)
                continue
            inner = ttk.Frame(outer)
            inner.pack(fill=tk.BOTH, expand=True)
            ncols = int(tab["columns"])
            for idx, ent in enumerate(ents):
                gr, gc = divmod(idx, ncols)
                self._place_sensor_cell(inner, ent, tab, gr, gc)
            for c in range(ncols):
                inner.columnconfigure(c, weight=1)
        self.after(200, lambda: self._fetch_sensor_values(schedule_next=True))

    def _place_sensor_cell(
        self,
        parent: ttk.Frame,
        ent: dict[str, str],
        tab: dict[str, Any],
        grid_row: int,
        grid_col: int,
    ) -> None:
        eid = ent["entity_id"]
        fixed = (ent.get("label") or ent.get("name") or "").strip()
        fixed_icon = (ent.get("icon") or "").strip()
        title_v = tk.StringVar(value=fixed if fixed else eid)
        disp_icon = ha_attribute_icon_to_display(fixed_icon) if fixed_icon else ""
        icon_v = tk.StringVar(value=disp_icon)
        val_v = tk.StringVar(value="…")
        self._sensor_refs.append((eid, fixed, fixed_icon, title_v, icon_v, val_v))

        isz = int(tab["icon_size"])
        lfs = int(tab["label_font_size"])
        vfs = int(tab["value_font_size"])
        lw = int(tab["label_width_chars"])
        il = str(tab.get("item_layout", "row"))
        ic_w = max(2, min(8, isz // 4))

        cell = ttk.Frame(parent)
        cell.grid(row=grid_row, column=grid_col, sticky="nsew", padx=4, pady=4)
        if il == "column":
            tk.Label(
                cell,
                textvariable=icon_v,
                font=("Segoe UI Emoji", isz),
                width=ic_w,
                anchor=tk.CENTER,
            ).grid(row=0, column=0, sticky=tk.N)
            ttk.Label(
                cell,
                textvariable=title_v,
                width=lw,
                anchor=tk.CENTER,
                font=("Segoe UI", lfs),
                wraplength=max(120, lw * 8),
            ).grid(row=1, column=0, sticky=tk.N, pady=(4, 0))
            ttk.Label(
                cell,
                textvariable=val_v,
                anchor=tk.CENTER,
                font=("Segoe UI", vfs, "bold"),
                wraplength=max(120, lw * 10),
            ).grid(row=2, column=0, sticky=tk.N, pady=(4, 0))
        else:
            tk.Label(
                cell,
                textvariable=icon_v,
                font=("Segoe UI Emoji", isz),
                width=ic_w,
                anchor=tk.CENTER,
            ).grid(row=0, column=0, sticky=tk.NS, padx=(0, 6), pady=2)
            ttk.Label(
                cell,
                textvariable=title_v,
                width=lw,
                anchor=tk.W,
                font=("Segoe UI", lfs),
            ).grid(row=0, column=1, sticky=tk.W, padx=(0, 8), pady=2)
            ttk.Label(
                cell,
                textvariable=val_v,
                anchor=tk.W,
                font=("Segoe UI", vfs, "bold"),
            ).grid(row=0, column=2, sticky=tk.EW, pady=2)
            cell.columnconfigure(2, weight=1)

    def _sensor_refresh_now(self) -> None:
        self._cancel_sensor_timer()
        self._fetch_sensor_values(schedule_next=True)

    def _sensor_poll_tick(self) -> None:
        self._sensor_after_id = None
        self._fetch_sensor_values(schedule_next=True)

    def _fetch_sensor_values(self, schedule_next: bool) -> None:
        refs = getattr(self, "_sensor_refs", [])
        if not refs:
            if schedule_next and self.winfo_exists():
                self._sensor_after_id = self.after(self._sensor_refresh_ms(), self._sensor_poll_tick)
            return
        cfg = load_config()

        def work() -> None:
            ok, err, states = fetch_ha_states(cfg)
            by_eid = states_by_entity_id(states) if ok else {}

            def done() -> None:
                if not self.winfo_exists():
                    return
                if not ok:
                    short = (err or "ошибка")[:120]
                    for _eid, _fix, _fic, _tv, ic_v, val_v in refs:
                        val_v.set(short)
                else:
                    for eid, fixed, fixed_icon, title_v, icon_v, val_v in refs:
                        st = by_eid.get(eid)
                        if not st:
                            val_v.set("— нет в ответе —")
                            if not fixed_icon:
                                icon_v.set("")
                        else:
                            val_v.set(format_entity_state_text(st))
                            if not fixed:
                                title_v.set(_friendly_name(st) or eid)
                            if not fixed_icon:
                                attrs = st.get("attributes") or {}
                                raw_ic = attrs.get("icon") if isinstance(attrs, dict) else None
                                icon_v.set(
                                    ha_attribute_icon_to_display(raw_ic) if raw_ic else ""
                                )
                if schedule_next:
                    self._sensor_after_id = self.after(self._sensor_refresh_ms(), self._sensor_poll_tick)

            self.after(0, done)

        threading.Thread(target=work, daemon=True).start()

    def _open_config_dir(self) -> None:
        d = app_dir()
        if sys.platform == "win32":
            os.startfile(d)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            os.system(f'open "{d}"')
        else:
            os.system(f'xdg-open "{d}"')

    def _open_editor(self) -> None:
        self.cfg = load_config()
        ButtonsEditorDialog(self, self.cfg, on_saved=self._rebuild_buttons)
    def _rebuild_buttons(self) -> None:
        self.cfg = load_config()
        self._close_tray_var.set(bool(self.cfg.get("close_to_tray", True)))
        self._start_min_var.set(bool(self.cfg.get("start_minimized", False)))
        for w in self.main_frame.winfo_children():
            w.destroy()
        tabs = get_button_tabs(self.cfg)
        ui = get_ui_settings(self.cfg)
        cols = max(1, min(6, int(ui.get("columns", 2))))
        try:
            pp = max(0, min(48, int(ui.get("buttons_per_page", 0) or 0)))
        except (TypeError, ValueError):
            pp = 0
        try:
            fs = max(8, min(24, int(ui.get("button_font_size", 11))))
        except (TypeError, ValueError):
            fs = 11
        try:
            pad_x = max(0, min(24, int(ui.get("button_pad_x", 6))))
            pad_y = max(0, min(24, int(ui.get("button_pad_y", 6))))
        except (TypeError, ValueError):
            pad_x, pad_y = 6, 6

        any_buttons = any(len(t.get("buttons", [])) > 0 for t in tabs)
        if not any_buttons:
            ttk.Label(
                self.main_frame,
                text="Нет кнопок.\nОткройте «Файл → Редактор кнопок»\nили добавьте их на вкладках в config.json.",
                justify=tk.CENTER,
            ).pack(expand=True)
            self.status.set("Нет кнопок в конфиге")
            return

        style = ttk.Style()
        style.configure("HAAction.TButton", font=("Segoe UI", fs), padding=(pad_x, pad_y))

        nb = ttk.Notebook(self.main_frame)
        nb.pack(fill=tk.BOTH, expand=True)
        self._tab_page_indices = [0] * len(tabs)

        for ti, tab in enumerate(tabs):
            title = str(tab.get("title", "Вкладка"))
            buttons = [dict(b) for b in tab.get("buttons", []) if isinstance(b, dict)]
            outer = ttk.Frame(nb, padding=4)
            nb.add(outer, text=title)
            nav = ttk.Frame(outer)
            grid_holder = ttk.Frame(outer)
            show_nav = pp > 0 and len(buttons) > pp
            if show_nav:
                nav.pack(fill=tk.X, pady=(0, 6))
            grid_holder.pack(fill=tk.BOTH, expand=True)

            def fill_tab_grid(
                tab_index: int,
                holder: ttk.Frame,
                all_buttons: list[dict[str, Any]],
            ) -> None:
                for ch in holder.winfo_children():
                    ch.destroy()
                nbtns = len(all_buttons)
                if pp <= 0 or nbtns <= pp:
                    chunk = all_buttons
                else:
                    npages = max(1, (nbtns + pp - 1) // pp)
                    page = max(0, min(self._tab_page_indices[tab_index], npages - 1))
                    self._tab_page_indices[tab_index] = page
                    start = page * pp
                    chunk = all_buttons[start : start + pp]
                for i, btn in enumerate(chunk):
                    if not isinstance(btn, dict):
                        continue
                    label = str(btn.get("label", "Действие"))
                    domain = str(btn.get("domain", "")).strip()
                    service = str(btn.get("service", "")).strip()
                    service_data = btn.get("service_data")
                    if isinstance(service_data, dict):
                        data = dict(service_data)
                    else:
                        data = {}
                    entity_id = btn.get("entity_id")
                    if entity_id and "entity_id" not in data:
                        data["entity_id"] = entity_id
                    row, col = divmod(i, cols)
                    b = ttk.Button(
                        holder,
                        text=label,
                        style="HAAction.TButton",
                        command=lambda d=domain, s=service, sd=data.copy(): self._on_action(d, s, sd),
                    )
                    b.grid(row=row, column=col, sticky=tk.NSEW, padx=4, pady=4)
                for c in range(cols):
                    holder.columnconfigure(c, weight=1)

            def refresh_nav(tab_index: int = ti, all_b: list[dict[str, Any]] = buttons) -> None:
                for ch in nav.winfo_children():
                    ch.destroy()
                if pp <= 0 or len(all_b) <= pp:
                    return
                nbtns = len(all_b)
                npages = max(1, (nbtns + pp - 1) // pp)
                p = max(0, min(self._tab_page_indices[tab_index], npages - 1))
                self._tab_page_indices[tab_index] = p
                ttk.Label(nav, text=f"Страница {p + 1} из {npages}").pack(side=tk.LEFT, padx=(0, 8))

                def go(delta: int, idx: int = tab_index, nb_: int = nbtns, per: int = pp) -> None:
                    np = max(1, (nb_ + per - 1) // per)
                    self._tab_page_indices[idx] = max(0, min(self._tab_page_indices[idx] + delta, np - 1))
                    refresh_nav(idx, all_b)
                    fill_tab_grid(idx, grid_holder, all_b)

                ttk.Button(nav, text="Назад", command=lambda: go(-1)).pack(side=tk.LEFT, padx=(0, 4))
                ttk.Button(nav, text="Вперёд", command=lambda: go(1)).pack(side=tk.LEFT)

            fill_tab_grid(ti, grid_holder, buttons)
            if show_nav:
                refresh_nav(ti, buttons)

        self.status.set("Готово")

    def _reload_from_config(self) -> None:
        self._rebuild_buttons()
        self._rebuild_sensor_panel()

    def _on_action(self, domain: str, service: str, service_data: dict[str, Any]) -> None:
        if not domain or not service:
            self.status.set("Ошибка: в кнопке не заданы domain/service")
            messagebox.showerror("Ошибка", "В конфиге кнопки не указаны domain и service.")
            return
        self.status.set("Выполняется…")
        def work() -> None:
            ok, msg = call_service(self.cfg, domain, service, service_data)
            def done() -> None:
                self.status.set(msg if ok else f"Ошибка: {msg}")
                if not ok:
                    messagebox.showerror("Home Assistant", msg)
            self.after(0, done)
        threading.Thread(target=work, daemon=True).start()
def main() -> None:
    app = App()
    app.mainloop()
if __name__ == "__main__":
    main()
