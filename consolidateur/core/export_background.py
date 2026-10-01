"""
core/export_background.py

Applique une image de FOND DE FEUILLE aux classeurs exportés.

openpyxl ne sait pas écrire cet élément : il faut retoucher le paquet .xlsx
(qui est une archive zip) après l'enregistrement, en ajoutant l'image dans
xl/media/, une relation vers elle pour chaque feuille, et une balise
<picture r:id="…"/> dans le XML de la feuille.

Limite connue d'Excel, indépendante de ce code : un fond de feuille s'affiche
à l'écran mais ne s'imprime pas, et il se répète en mosaïque. Aucune image
n'est fournie avec le projet : l'appelant passe la sienne.
"""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path

_REL_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"
_RELS_NS = "http://schemas.openxmlformats.org/package/2006/relationships"

# <picture/> doit être placé juste avant </worksheet>, mais après les autres
# éléments de fin (drawing, legacyDrawing…). Excel refuse d'ouvrir un fichier
# dont les éléments sont dans le désordre, d'où l'insertion en toute fin.
_PICTURE_TAG = '<picture r:id="{rid}"/>'

_NS_R = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'


def _ensure_r_namespace(sheet_xml: str) -> str:
    """Déclare le préfixe `r:` sur l'élément <worksheet> s'il manque.

    openpyxl ne l'écrit que si la feuille possède déjà une relation. Or la
    balise <picture r:id="…"/> l'utilise : sans déclaration, le XML produit
    est invalide (« unbound prefix ») et Excel refuse d'ouvrir le classeur.
    """
    if "xmlns:r=" in sheet_xml[:600]:
        return sheet_xml
    return sheet_xml.replace("<worksheet ", f"<worksheet {_NS_R} ", 1)


def _sheet_targets(zin: zipfile.ZipFile) -> list[str]:
    return [n for n in zin.namelist() if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n)]


def _next_rid(rels_xml: str) -> str:
    ids = [int(m) for m in re.findall(r'Id="rId(\d+)"', rels_xml)]
    return f"rId{max(ids) + 1 if ids else 1}"


def _empty_rels() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Relationships xmlns="{_RELS_NS}"></Relationships>'
    )


def apply_background_to_bytes(data: bytes, image_path: str | Path,
                              media_name: str = "background.png") -> bytes:
    """Même traitement que `apply_sheet_background`, mais en mémoire.

    C'est cette variante qu'utilise l'application : le classeur est produit
    puis servi directement au navigateur, sans passer par un fichier.

    À appliquer TOUJOURS EN DERNIER : LibreOffice supprime le fond lorsqu'il
    recalcule un classeur, donc toute étape de recalcul doit précéder cet
    appel.
    """
    image_path = Path(image_path)
    if not image_path.exists():
        return data

    media_target = f"xl/media/{media_name}"
    image_bytes = image_path.read_bytes()

    with zipfile.ZipFile(io.BytesIO(data), "r") as zin:
        names = set(zin.namelist())
        sheets = _sheet_targets(zin)
        payload = {n: zin.read(n) for n in zin.namelist()}

    ct = payload["[Content_Types].xml"].decode("utf-8")
    if 'Extension="png"' not in ct:
        ct = ct.replace("<Default", '<Default Extension="png" ContentType="image/png"/><Default', 1)
        payload["[Content_Types].xml"] = ct.encode("utf-8")

    payload[media_target] = image_bytes

    for sheet in sheets:
        rels_name = sheet.replace("xl/worksheets/", "xl/worksheets/_rels/") + ".rels"
        rels_xml = payload[rels_name].decode("utf-8") if rels_name in names else _empty_rels()
        rid = _next_rid(rels_xml)
        rel = f'<Relationship Id="{rid}" Type="{_REL_TYPE}" Target="../media/{media_name}"/>'
        payload[rels_name] = rels_xml.replace("</Relationships>", rel + "</Relationships>").encode("utf-8")

        sheet_xml = _ensure_r_namespace(payload[sheet].decode("utf-8"))
        if "<picture " not in sheet_xml:
            sheet_xml = sheet_xml.replace(
                "</worksheet>", _PICTURE_TAG.format(rid=rid) + "</worksheet>"
            )
        payload[sheet] = sheet_xml.encode("utf-8")

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for name, blob in payload.items():
            zout.writestr(name, blob)
    return out.getvalue()


def apply_sheet_background(xlsx_path: str | Path, image_path: str | Path,
                           media_name: str = "background.png") -> None:
    """Ajoute `image_path` en fond de TOUTES les feuilles de `xlsx_path`."""
    xlsx_path = Path(xlsx_path)
    data = xlsx_path.read_bytes()
    xlsx_path.write_bytes(apply_background_to_bytes(data, image_path, media_name))
