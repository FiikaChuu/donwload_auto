from dataclasses import dataclass
import re
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Cell:
    text: str = ""
    links: tuple[str, ...] = ()


@dataclass(frozen=True)
class Task:
    number: int
    sheet_row: int
    urls: tuple[str, ...]


def urls_in(text):
    return tuple(dict.fromkeys(re.findall(r'https?://[^\s<>"\)]+', text)))


def normalize(text):
    return re.sub(r"[^a-z0-9]", "", text.casefold())


def spreadsheet_id(value):
    value = value.strip()
    match = re.search(r"/spreadsheets/d/([A-Za-z0-9_-]+)", value)
    if match:
        host = urlsplit(value).hostname
        if host != "docs.google.com":
            raise ValueError("Gunakan tautan docs.google.com/spreadsheets atau ID spreadsheet.")
        return match.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{20,}", value):
        return value
    raise ValueError("Tautan / ID Google Sheets tidak valid.")


def column_index(value):
    value = value.strip().upper()
    if not re.fullmatch(r"[A-Z]{1,3}", value):
        raise ValueError("Kolom tautan harus berupa huruf, misalnya B,G.")
    result = 0
    for char in value:
        result = result * 26 + ord(char) - 64
    return result - 1


def select_tasks(rows, start, end, link_columns=""):
    if start < 0 or end < start:
        raise ValueError("Rentang nomor tidak valid; nomor akhir harus ≥ nomor awal.")
    header = None
    for index, row in enumerate(rows[:100]):
        names = [normalize(c.text) for c in row]
        number_cols = [i for i, n in enumerate(names) if n in {"no", "nomor", "number"}]
        pic_cols = [i for i, n in enumerate(names) if n == "pic"]
        if number_cols and pic_cols:
            header = index, number_cols[0], pic_cols[0], names
            break
    if header is None:
        raise ValueError("Header No. dan PIC tidak ditemukan dalam 100 baris pertama.")
    offset, no_col, pic_col, names = header
    if link_columns.strip():
        links_cols = [column_index(c) for c in link_columns.split(",")]
    else:
        links_cols = [i for i, n in enumerate(names) if n in {
            "reference", "referensi", "linkdrive", "drive", "link", "url", "tautan"
        }]
        if not links_cols:
            raise ValueError("Kolom tautan tidak ditemukan. Isi kolom tautan, misalnya B,G.")
    result = []
    for sheet_row, row in enumerate(rows[offset + 1:], offset + 2):
        def cell(i):
            return row[i] if i < len(row) else Cell()
        if cell(pic_col).text.strip().casefold() != "afzal":
            continue
        raw = cell(no_col).text.strip()
        if not re.fullmatch(r"\d+(?:\.0+)?", raw):
            continue
        number = int(raw.split(".")[0])
        if not start <= number <= end:
            continue
        urls = []
        for col in links_cols:
            c = cell(col)
            urls.extend(c.links)
            urls.extend(urls_in(c.text))
        urls = tuple(dict.fromkeys(u for u in urls if urlsplit(u).scheme in {"http", "https"}))
        result.append(Task(number, sheet_row, urls))
    return result
