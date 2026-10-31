from io import BytesIO
import json
import os
from pathlib import Path

import requests
from openpyxl import load_workbook

from .models import Cell, spreadsheet_id, urls_in

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly",
          "https://www.googleapis.com/auth/drive.readonly"]


def authorize(client_file):
    """OAuth Desktop; tokens live outside the repository, never in logs."""
    from google.auth.transport.requests import Request, AuthorizedSession
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    import hashlib
    client = Path(client_file)
    identity = hashlib.sha256(client.read_bytes()).hexdigest()[:16]
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".config")) / "AfzalDownloader"
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    token = base / f"token-{identity}.json"
    credentials = None
    if token.exists():
        credentials = Credentials.from_authorized_user_file(str(token), SCOPES)
    if credentials and credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
    if not credentials or not credentials.valid:
        flow = InstalledAppFlow.from_client_secrets_file(str(client), SCOPES)
        credentials = flow.run_local_server(port=0, timeout_seconds=180,
                                           authorization_prompt_message="Login Google dibuka di browser.")
    fd = os.open(token, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(credentials.to_json())
    return AuthorizedSession(credentials)


class SheetSource:
    def __init__(self, url, client_file=""):
        self.id = spreadsheet_id(url)
        self.private = bool(client_file)
        self.session = authorize(client_file) if client_file else requests.Session()
        self.workbook = None
        self.cached = None
        self.tabs = []

    def load(self):
        if self.private:
            response = self.session.get(
                f"https://sheets.googleapis.com/v4/spreadsheets/{self.id}",
                params={"fields": "sheets.properties.title"}, timeout=60)
            response.raise_for_status()
            self.tabs = [s["properties"]["title"] for s in response.json()["sheets"]]
        else:
            response = self.session.get(
                f"https://docs.google.com/spreadsheets/d/{self.id}/export",
                params={"format": "xlsx"}, timeout=90)
            response.raise_for_status()
            if not response.content.startswith(b"PK"):
                raise ValueError("Sheets tidak dapat dibaca publik. Aktifkan akses Viewer melalui tautan atau gunakan Login Google (OAuth).")
            self.workbook = load_workbook(BytesIO(response.content), data_only=False)
            self.cached = load_workbook(BytesIO(response.content), data_only=True)
            self.tabs = self.workbook.sheetnames
        return self.tabs

    def rows(self, title):
        if not self.private:
            result = []
            for row in self.workbook[title].iter_rows():
                cells = []
                for c in row:
                    value = self.cached[title][c.coordinate].value if self.cached else None
                    if value is None:
                        value = c.value
                    text = "" if value is None else str(value)
                    links = list(urls_in(str(c.value or "")))
                    if c.hyperlink and c.hyperlink.target:
                        links.insert(0, c.hyperlink.target)
                    cells.append(Cell(text, tuple(dict.fromkeys(links))))
                result.append(cells)
            return result
        escaped = title.replace("'", "''")
        response = self.session.get(
            f"https://sheets.googleapis.com/v4/spreadsheets/{self.id}",
            params={"ranges": f"'{escaped}'", "includeGridData": "true",
                    "fields": "sheets.data(startRow,startColumn,rowData.values(formattedValue,hyperlink,userEnteredValue,textFormatRuns))"},
            timeout=90)
        response.raise_for_status()
        result = []
        for sheet in response.json().get("sheets", []):
            for grid in sheet.get("data", []):
                start = grid.get("startRow", 0)
                for n, row in enumerate(grid.get("rowData", []), start):
                    while len(result) <= n:
                        result.append([])
                    cells = [Cell()] * grid.get("startColumn", 0)
                    for c in row.get("values", []):
                        text = c.get("formattedValue", "")
                        links = list(urls_in(text))
                        links.extend(urls_in(c.get("userEnteredValue", {}).get("formulaValue", "")))
                        if c.get("hyperlink"):
                            links.append(c["hyperlink"])
                        for run in c.get("textFormatRuns", []):
                            uri = run.get("format", {}).get("link", {}).get("uri")
                            if uri:
                                links.append(uri)
                        cells.append(Cell(text, tuple(dict.fromkeys(links))))
                    result[n] = cells
        return result

    def close(self):
        self.session.close()
        if self.workbook:
            self.workbook.close()
        if self.cached:
            self.cached.close()
