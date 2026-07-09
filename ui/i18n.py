import flet as ft
from translations import TRANSLATIONS

def get_lang(page: ft.Page):
    return page.session.store.get("lang") or "en"

def t(key, lang="en", **kwargs):
    if lang not in TRANSLATIONS:
        lang = "en"
    val = TRANSLATIONS[lang].get(key, TRANSLATIONS["en"].get(key, key))
    if kwargs:
        return val.format(**kwargs)
    return val
