"""Loading datasets and keeping them in memory, one DuckDB connection per dataset."""

from __future__ import annotations

import io
import json
import re
import threading
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from ..config import SAMPLES_DIR, get_settings
from .profiler import PERIOD_COL, Profile, health_check, profile_dataframe

ALLOWED_EXTENSIONS = {".csv", ".xlsx"}
SAMPLE_ID = re.compile(r"^[a-z0-9_]{1,64}$")


class DatasetError(ValueError):
    """Raised for invalid uploads or unknown datasets. The message is safe to show to users."""


@dataclass
class Dataset:
    id: str
    name: str
    df: pd.DataFrame
    profile: Profile
    health: dict[str, Any]
    con: duckdb.DuckDBPyConnection
    lock: threading.Lock = field(default_factory=threading.Lock)

    def query(self, sql: str, params: list[Any] | None = None) -> pd.DataFrame:
        """Run a query built by the tool layer. Only tool code calls this, never model output."""
        with self.lock:
            return self.con.execute(sql, params or []).df()

    def summary(self) -> dict[str, Any]:
        p = self.profile
        return {
            "id": self.id,
            "name": self.name,
            "profile": p.to_dict(),
            "health": self.health,
            "preview": _records(self.df.drop(columns=[PERIOD_COL]).head(8)),
        }


def _records(df: pd.DataFrame) -> list[dict[str, Any]]:
    """DataFrame to JSON-safe records (NaN becomes None)."""
    return json.loads(df.to_json(orient="records", date_format="iso"))


def _clean_columns(df: pd.DataFrame) -> pd.DataFrame:
    seen: dict[str, int] = {}
    names = []
    for i, c in enumerate(df.columns):
        name = re.sub(r"\s+", " ", str(c)).strip()[:64].lstrip("_") or f"column_{i + 1}"
        if name.lower().startswith("unnamed:"):
            name = f"column_{i + 1}"
        key = name.lower()
        if key in seen:
            seen[key] += 1
            name = f"{name}_{seen[key]}"
        else:
            seen[key] = 0
        names.append(name)
    df.columns = names
    return df


def parse_upload(filename: str, content: bytes) -> pd.DataFrame:
    settings = get_settings()
    ext = Path(filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise DatasetError("Only .csv and .xlsx files are supported.")
    if len(content) > settings.max_upload_mb * 1024 * 1024:
        raise DatasetError(f"File is larger than {settings.max_upload_mb:g} MB.")
    if not content.strip():
        raise DatasetError("The file is empty.")
    try:
        if ext == ".csv":
            df = None
            for enc in ("utf-8-sig", "utf-8", "latin-1"):
                try:
                    df = pd.read_csv(io.BytesIO(content), encoding=enc, skipinitialspace=True)
                    break
                except UnicodeDecodeError:
                    continue
            if df is None:
                raise DatasetError("Could not read the CSV text encoding.")
        else:
            df = pd.read_excel(io.BytesIO(content), engine="openpyxl")
    except DatasetError:
        raise
    except Exception as exc:  # pandas raises many parser-specific errors
        raise DatasetError(f"Could not read the file: {type(exc).__name__}.") from exc
    if df.empty or len(df.columns) == 0:
        raise DatasetError("The file has no data rows.")
    if len(df) > settings.max_rows:
        raise DatasetError(f"The file has more than {settings.max_rows:,} rows.")
    if len(df.columns) > settings.max_columns:
        raise DatasetError(f"The file has more than {settings.max_columns} columns.")
    df = _clean_columns(df.dropna(how="all"))
    return df


class DatasetStore:
    def __init__(self) -> None:
        self._items: OrderedDict[str, Dataset] = OrderedDict()
        self._lock = threading.Lock()

    def _build(self, name: str, df: pd.DataFrame, meta: dict | None, default_source: str) -> Dataset:
        df, profile = profile_dataframe(df, meta, default_source=default_source)
        health = health_check(df, profile)
        con = duckdb.connect(database=":memory:")
        con.register("data", df)
        ds = Dataset(id=uuid.uuid4().hex[:12], name=name, df=df, profile=profile, health=health, con=con)
        with self._lock:
            self._items[ds.id] = ds
            while len(self._items) > get_settings().max_datasets:
                _, old = self._items.popitem(last=False)
                old.con.close()
        return ds

    def get(self, dataset_id: str) -> Dataset:
        with self._lock:
            ds = self._items.get(dataset_id)
        if ds is None:
            raise DatasetError("Dataset not found. Load it again.")
        return ds

    def load_sample(self, sample_id: str) -> Dataset:
        if not SAMPLE_ID.match(sample_id or ""):
            raise DatasetError("Unknown sample dataset.")
        csv_path = SAMPLES_DIR / f"{sample_id}.csv"
        meta_path = SAMPLES_DIR / f"{sample_id}.dict.json"
        if not csv_path.exists():
            raise DatasetError("Unknown sample dataset.")
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else None
        df = pd.read_csv(csv_path)
        return self._build(csv_path.name, df, meta, default_source="synthetic")

    def load_upload(self, filename: str, content: bytes) -> Dataset:
        df = parse_upload(filename, content)
        safe_name = re.sub(r"[^\w.\- ]", "_", Path(filename).name)[:80]
        return self._build(safe_name, df, {"title": Path(safe_name).stem.replace("_", " ").title()}, default_source="user-entered")


def list_samples() -> list[dict[str, Any]]:
    out = []
    for meta_path in sorted(SAMPLES_DIR.glob("*.dict.json")):
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        out.append({k: meta.get(k) for k in ("id", "title", "title_hi", "issue", "source", "description")})
    order = ["electricity", "water", "waste", "air", "mobility", "resources"]
    out.sort(key=lambda m: order.index(m["issue"]) if m["issue"] in order else 99)
    return out


store = DatasetStore()
