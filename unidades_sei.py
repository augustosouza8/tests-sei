# file: listar_unidades_zeep.py
"""
Call SEI SOAP API (listarUnidades) using zeep and parse the encoded response.

- POST to: https://www.sei.mg.gov.br/sei/ws/SeiWS.php
- Header:  Content-Type: text/xml; charset=UTF-8  (and SOAPAction: "")
- Body:    SOAP envelope with <sei:listarUnidades>

How to run (Windows):
  uv venv
  .venv\\Scripts\\activate
  uv add zeep lxml requests
  setx SEI_SIGLA_SISTEMA "Automatiza_MG"
  setx SEI_IDENT_SERVICO "SUA_CHAVE_AQUI"
  python listar_unidades_zeep.py
"""

from __future__ import annotations

import os
import csv
from typing import List, Dict

import requests
from lxml import etree
from zeep.transports import Transport

# ------------------------- Configuration -------------------------------------

ENDPOINT = "https://www.sei.mg.gov.br/sei/ws/SeiWS.php"
SIGLA_SISTEMA = os.getenv("SEI_SIGLA_SISTEMA", "Automatiza_MG")
IDENT_SERVICO = os.getenv("SEI_IDENT_SERVICO", "e301b3ecd7274e15ae8edc2347483444a5a58472df6e368a8c6b16861cd08b67509e5def")

SAVE_CSV = True
CSV_PATH = "listar_unidades.csv"


# ---------------------- Envelope construction --------------------------------

def build_envelope_element(sigla_sistema: str, identificacao_servico: str) -> etree._Element:
    """
    Build the SOAP 1.1 XML envelope **as an lxml Element** (what zeep expects).

    We keep it close to your Postman body:
      <soap-env:Envelope ...>
        <soap-env:Body>
          <sei:listarUnidades xmlns:sei="Sei">
            <SiglaSistema>...</SiglaSistema>
            <IdentificacaoServico>...</IdentificacaoServico>
          </sei:listarUnidades>
        </soap-env:Body>
      </soap-env:Envelope>
    """
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<soap-env:Envelope xmlns:soap-env="http://schemas.xmlsoap.org/soap/envelope/">
  <soap-env:Body>
    <sei:listarUnidades xmlns:sei="Sei">
      <SiglaSistema>{sigla_sistema}</SiglaSistema>
      <IdentificacaoServico>{identificacao_servico}</IdentificacaoServico>
    </sei:listarUnidades>
  </soap-env:Body>
</soap-env:Envelope>"""
    # Convert string -> Element (NOT bytes for zeep.post_xml)
    return etree.fromstring(xml.encode("utf-8"))


# --------------------------- HTTP call ---------------------------------------

def call_sei(envelope_el: etree._Element, timeout: int = 60) -> requests.Response:
    """
    Send the SOAP request using zeep's Transport.

    NOTE:
      - On this zeep version, Transport.post_xml(address, envelope, headers)
        requires the `headers` argument.
      - The `envelope` must be an **lxml Element** (not bytes/str).
    """
    session = requests.Session()
    session.headers.update({
        "Content-Type": "text/xml; charset=UTF-8",
        "SOAPAction": ""
    })
    transport = Transport(session=session, timeout=timeout)

    resp = transport.post_xml(
        ENDPOINT,
        envelope_el,
        headers={"Content-Type": "text/xml; charset=UTF-8", "SOAPAction": ""}
    )
    resp.raise_for_status()
    return resp


# --------------------------- Parsing helpers ---------------------------------

def parse_unidades_from_response(xml_bytes: bytes) -> List[Dict[str, str]]:
    """
    Parse SOAP-ENC style response like:

      <listarUnidadesResponse>
        <parametros>
          <item>
            <IdUnidade>...</IdUnidade>
            <Sigla>...</Sigla>
            <Descricao>...</Descricao>
            <SinProtocolo>...</SinProtocolo>
            <SinArquivamento>...</SinArquivamento>
            <SinOuvidoria>...</SinOuvidoria>
          </item>
          ...
        </parametros>
      </listarUnidadesResponse>

    We match by local-name() to ignore prefixes (ns1, SOAP-ENV, etc.).
    """
    doc = etree.fromstring(xml_bytes)

    item_nodes = doc.xpath(
        '//*[local-name()="listarUnidadesResponse"]'
        '/*[local-name()="parametros"]'
        '/*[local-name()="item"]'
    )

    def get_child_text(node: etree._Element, child_local_name: str) -> str | None:
        result = node.xpath(f'*[local-name()="{child_local_name}"]/text()')
        if not result:
            return None
        value = result[0].strip() if result[0] else None
        return value or None

    unidades: List[Dict[str, str]] = []
    for it in item_nodes:
        unidades.append({
            "IdUnidade":       get_child_text(it, "IdUnidade"),
            "Sigla":           get_child_text(it, "Sigla"),
            "Descricao":       get_child_text(it, "Descricao"),
            "SinProtocolo":    get_child_text(it, "SinProtocolo"),
            "SinArquivamento": get_child_text(it, "SinArquivamento"),
            "SinOuvidoria":    get_child_text(it, "SinOuvidoria"),
        })
    return unidades


def distinct_by_key(rows: List[Dict[str, str]], key: str) -> List[Dict[str, str]]:
    """Deduplicate dicts by `key`, preserving original order."""
    seen = set()
    out: List[Dict[str, str]] = []
    for r in rows:
        k = r.get(key)
        if k and k not in seen:
            seen.add(k)
            out.append(r)
    return out


# --------------------------- Output helpers ----------------------------------

def save_to_csv(rows: List[Dict[str, str]], path: str) -> None:
    """Write list of dicts to CSV."""
    if not rows:
        print("Nothing to write to CSV.")
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"CSV saved: {path}  (rows: {len(rows)})")


# --------------------------------- Main --------------------------------------

def main() -> None:
    if IDENT_SERVICO == "COLE_SUA_CHAVE_AQUI":
        print("⚠️  Set SEI_IDENT_SERVICO with your real key before running.")

    print("→ Building envelope…")
    envelope_el = build_envelope_element(SIGLA_SISTEMA, IDENT_SERVICO)

    print(f"→ Calling SEI @ {ENDPOINT} …")
    resp = call_sei(envelope_el)
    print(f"HTTP {resp.status_code}; received {len(resp.content)} bytes")

    print("→ Parsing response…")
    unidades = parse_unidades_from_response(resp.content)
    print(f"Total unidades in payload: {len(unidades)}")

    print("→ Deduplicating by IdUnidade…")
    unidades_distinct = distinct_by_key(unidades, "IdUnidade")
    print(f"Distinct IdUnidade count: {len(unidades_distinct)}")

    print("\nFirst 10 unidades:")
    for i, u in enumerate(unidades_distinct[:10], 1):
        print(f"{i:02d}. IdUnidade={u.get('IdUnidade')}, Sigla={u.get('Sigla')}, Descricao={u.get('Descricao')}")

    if SAVE_CSV:
        save_to_csv(unidades_distinct, CSV_PATH)


if __name__ == "__main__":
    main()
