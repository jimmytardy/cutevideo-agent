from __future__ import annotations

import logging

import aiohttp

logger = logging.getLogger(__name__)

API_URL = "https://gallica.bnf.fr/SRU"
THUMBNAIL_URL = "https://gallica.bnf.fr/ark:/12148/{ark}/f1.highres"


async def search(keywords: list[str], period: str = "") -> list[dict]:
    """Recherche sur Gallica BnF — archives nationales françaises."""
    query_terms = " and ".join(f'"{kw}"' for kw in keywords[:2] if kw)
    if not query_terms:
        return []

    params = {
        "operation": "searchRetrieve",
        "version": "1.2",
        "query": f"(gallica any \"{' '.join(keywords[:2])}\") and dc.type any \"image\"",
        "maximumRecords": "10",
        "startRecord": "1",
    }

    results: list[dict] = []
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                API_URL, params=params, timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status != 200:
                    return []
                text = await resp.text()

        import xml.etree.ElementTree as ET
        root = ET.fromstring(text)
        ns = {
            "srw": "http://www.loc.gov/zing/srw/",
            "dc": "http://purl.org/dc/elements/1.1/",
            "oai_dc": "http://www.openarchives.org/OAI/2.0/oai_dc/",
        }

        for record in root.findall(".//srw:record", ns):
            data = record.find(".//oai_dc:dc", ns)
            if data is None:
                continue

            identifier = ""
            for id_el in data.findall("dc:identifier", ns):
                if id_el.text and "gallica.bnf.fr/ark" in id_el.text:
                    identifier = id_el.text
                    break

            if not identifier:
                continue

            ark = identifier.split("ark:/12148/")[-1].split("/")[0] if "ark:/12148/" in identifier else ""
            image_url = f"https://gallica.bnf.fr/ark:/12148/{ark}/f1.highres" if ark else identifier

            title_el = data.find("dc:title", ns)
            title = title_el.text if title_el is not None else "Gallica BnF"
            creator_el = data.find("dc:creator", ns)
            creator = creator_el.text if creator_el is not None else ""

            results.append({
                "source": "gallica",
                "url": image_url,
                "license": "domaine public",
                "attribution": f"Gallica BnF — {creator}" if creator else f"Gallica BnF — {title}",
                "title": title,
            })
    except Exception as e:
        logger.warning("Gallica search error: %s", e)

    return results
