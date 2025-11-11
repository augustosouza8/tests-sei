"""Utilitários para serializar elementos de formulários HTML produzidos pelo SEI."""

from __future__ import annotations

from typing import Dict, List

from bs4 import Tag


def serializar_inputs(form: Tag) -> Dict[str, str]:
    """Extrai campos `input` do formulário respeitando tipos especiais como radio/checkbox."""
    data: Dict[str, str] = {}
    for inp in form.find_all("input"):
        if not isinstance(inp, Tag):
            continue
        name = inp.get("name")
        if not name:
            continue
        itype = (inp.get("type") or "").lower()
        val = inp.get("value", "")

        if itype in {"radio", "checkbox"}:
            if inp.has_attr("checked"):
                data[name] = val
        else:
            data[name] = val
    return data


def serializar_selects(form: Tag) -> Dict[str, str]:
    """Mapeia os `select` do formulário para seus valores selecionados."""
    data: Dict[str, str] = {}
    for sel in form.find_all("select"):
        if not isinstance(sel, Tag):
            continue
        name = sel.get("name")
        if not name:
            continue
        opt = sel.find("option", selected=True) or sel.find("option")
        if opt and isinstance(opt, Tag):
            data[name] = opt.get("value", "")
        else:
            data[name] = ""
    return data


def serializar_textareas(form: Tag) -> Dict[str, str]:
    """Coleta conteúdos de `textarea`, removendo espaços excedentes."""
    data: Dict[str, str] = {}
    for ta in form.find_all("textarea"):
        if not isinstance(ta, Tag):
            continue
        name = ta.get("name")
        if not name:
            continue
        data[name] = (ta.text or "").strip()
    return data


def processar_radios_nao_marcados(form: Tag, data: Dict[str, str]) -> Dict[str, str]:
    """Garante que ao menos um valor por grupo de rádio seja enviado, mesmo sem seleção."""
    radios_by_name: Dict[str, List[Tag]] = {}
    for radio in form.find_all("input", {"type": "radio"}):
        if not isinstance(radio, Tag):
            continue
        name = radio.get("name")
        if not name:
            continue
        radios_by_name.setdefault(name, []).append(radio)
    for name, radios in radios_by_name.items():
        if name not in data and radios:
            data[name] = radios[0].get("value", "")
    return data


def serializar_formulario(form: Tag) -> Dict[str, str]:
    """Serializa o formulário completo combinando inputs, selects e textareas."""
    data: Dict[str, str] = {}
    data.update(serializar_inputs(form))
    data.update(serializar_selects(form))
    data.update(serializar_textareas(form))
    return processar_radios_nao_marcados(form, data)

