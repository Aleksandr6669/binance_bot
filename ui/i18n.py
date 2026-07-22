import flet as ft
import db
from translations import TRANSLATIONS

def get_lang(page: ft.Page):
    try:
        if hasattr(page.session, "store") and hasattr(page.session.store, "get"):
            lang = page.session.store.get("lang")
            if lang:
                return lang.lower()
        elif hasattr(page.session, "get"):
            lang = page.session.get("lang")
            if lang:
                return lang.lower()
        
        # Load from DB settings if not present in session
        settings = db.get_settings()
        if settings and settings.get("ui_language"):
            db_lang = settings.get("ui_language").lower()
            if db_lang in ["en", "ru", "uk"]:
                # Save to session cache
                if hasattr(page.session, "store") and hasattr(page.session.store, "set"):
                    page.session.store.set("lang", db_lang)
                elif hasattr(page.session, "set"):
                    page.session.set("lang", db_lang)
                return db_lang
        return "en"
    except Exception:
        return "en"

def t(key, lang="en", **kwargs):
    if lang not in TRANSLATIONS:
        lang = "en"
    val = TRANSLATIONS[lang].get(key, TRANSLATIONS["en"].get(key, key))
    if kwargs:
        return val.format(**kwargs)
    return val
