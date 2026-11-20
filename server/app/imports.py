"""Импорт закупочных цен (docs/spec.md, раздел 7).

Поток: разбор файла → сопоставление колонок → проверка (preview) → применение одной транзакцией → отмена.
Файл не сохраняется: в базе хранятся только разобранные строки и сопоставление.
"""

from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from openpyxl import load_workbook

from .config import settings
from .errors import ApiError
from .money import parse_tenge_to_minor

FIELDS = ["sku", "purchase", "delivery_to_warehouse", "packaging", "other", "effective_from"]
REQUIRED = ["sku", "purchase"]
HEADER_HINTS = {
    "sku": ["артикул", "sku", "арт."],
    "purchase": ["закупка", "закупочная", "закупка, ₸", "закупочная цена"],
    "delivery_to_warehouse": ["доставка до склада", "доставка до"],
    "packaging": ["упаковка"],
    "other": ["прочее", "прочие"],
    "effective_from": ["действует с", "дата начала"],
}
SCI_RE = re.compile(r"^\s*[-+]?\d+([.,]\d+)?E[-+]?\d+\s*$", re.IGNORECASE)
EXCEL_ARTICLE_MSG = "Артикул испорчен Excel: задайте колонке текстовый формат."
FORMULA_MSG = "Пересохраните файл в Excel."


@dataclass
class RawRow:
    number: int  # номер строки в файле (с 1)
    cells: list  # значения как есть (str | int | float | datetime | None)
    formula_empty: list[bool] = field(default_factory=list)


@dataclass
class ParsedFile:
    columns: list[str]
    rows: list[RawRow]


def _check_size(content: bytes) -> None:
    if len(content) > settings.import_max_bytes:
        raise ApiError(413, "import_too_large")


def parse_file(filename: str, content: bytes) -> ParsedFile:
    _check_size(content)
    name = filename.lower()
    if name.endswith((".xls", ".xlsm")):
        raise ApiError(400, "import_bad_file", "Этот формат не поддерживается. Сохраните файл как XLSX или CSV.")
    if name.endswith(".xlsx") or content[:2] == b"PK":
        return _parse_xlsx(content)
    if name.endswith(".csv"):
        return _parse_csv(content)
    raise ApiError(400, "import_bad_file", "Выберите файл XLSX или CSV.")


_READ_CHUNK = 64 * 1024


def _check_unzipped(content: bytes) -> None:
    """AUD-06: считаем байты, которые реально распаковались, а не размеры из заголовков архива (их можно подделать)."""
    limit = settings.import_max_unzipped_bytes
    total = 0
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            for info in zf.infolist():
                with zf.open(info) as member:
                    while True:
                        chunk = member.read(_READ_CHUNK)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > limit:
                            raise ApiError(413, "import_too_large", "Таблица слишком большая после распаковки.")
    except ApiError:
        raise
    except (zipfile.BadZipFile, OSError, RuntimeError, ValueError) as exc:
        raise ApiError(400, "import_bad_file") from exc


def _parse_xlsx(content: bytes) -> ParsedFile:
    _check_unzipped(content)
    try:
        values_wb = load_workbook(io.BytesIO(content), data_only=True, read_only=True)
        formulas_wb = load_workbook(io.BytesIO(content), data_only=False, read_only=True)
    except Exception as exc:  # noqa: BLE001
        raise ApiError(400, "import_bad_file") from exc
    # строки читаются потоком; лимит проверяется по мере чтения, а не после загрузки всей таблицы (AUD-06)
    it_v = values_wb.worksheets[0].iter_rows(values_only=True)
    it_f = formulas_wb.worksheets[0].iter_rows(values_only=True)
    header = next(it_v, None)
    next(it_f, None)
    if header is None:
        raise ApiError(400, "import_bad_file", "Файл пустой.")
    columns = [str(c).strip() if c is not None else "" for c in header]
    out: list[RawRow] = []
    for idx, row in enumerate(it_v, start=2):
        frow = next(it_f, ())
        if row is None or all(c in (None, "") for c in row):
            continue
        empties = []
        for ci, val in enumerate(row):
            f = frow[ci] if ci < len(frow) else None
            is_formula = isinstance(f, str) and f.startswith("=")
            empties.append(is_formula and val is None)
        out.append(RawRow(number=idx, cells=list(row), formula_empty=empties))
        if len(out) > settings.import_max_rows:
            raise ApiError(400, "import_bad_file", "В файле больше 5 000 строк.")
    return ParsedFile(columns=columns, rows=out)


def _parse_csv(content: bytes) -> ParsedFile:
    text = None
    for enc in ("utf-8-sig", "cp1251"):
        try:
            text = content.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise ApiError(400, "import_bad_file", "Не удалось определить кодировку файла.")
    sample = text[:2048]
    delimiter = ";" if sample.count(";") > sample.count(",") else ","
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    header = next(reader, None)
    if header is None:
        raise ApiError(400, "import_bad_file", "Файл пустой.")
    columns = [c.strip() for c in header]
    out = []
    for idx, row in enumerate(reader, start=2):
        if not any(c.strip() for c in row):
            continue
        out.append(RawRow(number=idx, cells=row, formula_empty=[False] * len(row)))
        if len(out) > settings.import_max_rows:
            raise ApiError(400, "import_bad_file", "В файле больше 5 000 строк.")
    return ParsedFile(columns=columns, rows=out)


def auto_mapping(columns: list[str]) -> dict[str, str | None]:
    mapping: dict[str, str | None] = {f: None for f in FIELDS}
    lowered = [c.lower() for c in columns]
    for fld, hints in HEADER_HINTS.items():
        for hint in hints:
            for i, col in enumerate(lowered):
                if hint in col and columns[i] not in mapping.values():
                    mapping[fld] = columns[i]
                    break
            if mapping[fld]:
                break
    return mapping


def missing_required(mapping: dict[str, str | None]) -> list[str]:
    return [f for f in REQUIRED if not mapping.get(f)]


def parse_money_cell(value, required: bool) -> tuple[int | None, str | None]:
    if value is None or (isinstance(value, str) and value.strip() == ""):
        return (None, "Не заполнено обязательное значение" if required else None)
    if isinstance(value, bool):
        return None, "Некорректное число"
    if isinstance(value, (int, float, Decimal)):
        if isinstance(value, float) and value < 0:
            return None, "Отрицательные значения не допускаются"
        s = str(value) if not isinstance(value, float) else repr(value)
        if "e" in s.lower() and isinstance(value, float):
            try:
                s = format(Decimal(s), "f")
            except InvalidOperation:
                return None, "Некорректное число"
    else:
        s = str(value)
        s = re.sub(r"[\s  ]", "", s)
        s = s.replace("₸", "").replace("тг", "").replace("ТГ", "")
        s = s.replace(",", ".")
        if s.count(".") > 1:
            return None, "Некорректное число"
    try:
        dec = Decimal(s)
    except InvalidOperation:
        return None, "Некорректное число"
    if dec < 0:
        return None, "Отрицательные значения не допускаются"
    try:
        return parse_tenge_to_minor(str(dec)), None
    except ValueError:
        return None, "Больше двух знаков после запятой"


def parse_sku_cell(value) -> tuple[str | None, str | None]:
    if value is None or (isinstance(value, str) and value.strip() == ""):
        return None, "Не заполнен артикул"
    if isinstance(value, bool):
        return None, EXCEL_ARTICLE_MSG
    if isinstance(value, float):
        if value.is_integer() and abs(value) < 1e15:
            return str(int(value)), None
        return None, EXCEL_ARTICLE_MSG
    if isinstance(value, int):
        return str(value), None
    s = str(value).strip()
    if SCI_RE.match(s):
        return None, EXCEL_ARTICLE_MSG
    if re.fullmatch(r"\d+\.0", s):  # числовая ячейка без «.0»
        s = s[:-2]
    return s, None


def parse_date_cell(value) -> tuple[date | None, str | None]:
    if value is None or (isinstance(value, str) and value.strip() == ""):
        return None, None
    if isinstance(value, datetime):
        return value.date(), None
    if isinstance(value, date):
        return value, None
    s = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date(), None
        except ValueError:
            continue
    return None, "Не удалось прочитать дату «Действует с»"


def csv_safe(value: str) -> str:
    if value and value[0] in ("=", "+", "-", "@", "\t", "\r", "\n"):
        return "'" + value
    return value


@dataclass
class ValidRow:
    number: int
    sku: str
    purchase_minor: int
    delivery_to_warehouse_minor: int
    packaging_minor: int
    other_minor: int
    effective_from: str | None  # ISO date


@dataclass
class RowError:
    number: int
    sku: str | None
    field: str
    message: str


def validate_rows(parsed: ParsedFile, mapping: dict[str, str | None], duplicates: str = "skip",
                  known_skus: set[str] | None = None) -> tuple[list[ValidRow], list[RowError], int]:
    col_index = {c: i for i, c in enumerate(parsed.columns)}

    def cell(row: RawRow, fld: str):
        col = mapping.get(fld)
        if not col or col not in col_index:
            return None, False
        idx = col_index[col]
        val = row.cells[idx] if idx < len(row.cells) else None
        empty_formula = row.formula_empty[idx] if idx < len(row.formula_empty) else False
        return val, empty_formula

    errors: list[RowError] = []
    candidates: list[ValidRow] = []
    seen: dict[str, list[int]] = {}
    for row in parsed.rows:
        val, formula_empty = cell(row, "sku")
        if formula_empty:
            errors.append(RowError(row.number, None, "sku", FORMULA_MSG))
            continue
        sku, err = parse_sku_cell(val)
        if err:
            errors.append(RowError(row.number, None, "sku", err))
            continue
        bad = False
        amounts: dict[str, int] = {}
        for fld, required in (("purchase", True), ("delivery_to_warehouse", False), ("packaging", False),
                              ("other", False)):
            v, formula_empty = cell(row, fld)
            if formula_empty:
                errors.append(RowError(row.number, sku, fld, FORMULA_MSG))
                bad = True
                break
            minor, err = parse_money_cell(v, required)
            if err:
                errors.append(RowError(row.number, sku, fld, err))
                bad = True
                break
            amounts[fld] = minor or 0
        if bad:
            continue
        eff_val, _ = cell(row, "effective_from")
        eff, eff_err = parse_date_cell(eff_val)
        if eff_err:
            errors.append(RowError(row.number, sku, "effective_from", eff_err))
            continue
        seen.setdefault(sku, []).append(row.number)
        candidates.append(ValidRow(
            number=row.number, sku=sku, purchase_minor=amounts["purchase"],
            delivery_to_warehouse_minor=amounts["delivery_to_warehouse"],
            packaging_minor=amounts["packaging"], other_minor=amounts["other"],
            effective_from=eff.isoformat() if eff else None,
        ))

    dup_skus = {s for s, nums in seen.items() if len(nums) > 1}
    valid: list[ValidRow] = []
    last_by_sku: dict[str, ValidRow] = {}
    for c in candidates:
        if c.sku in dup_skus:
            if duplicates == "last":
                last_by_sku[c.sku] = c
            else:
                errors.append(RowError(c.number, c.sku, "sku", "Дубль артикула: строка не загружена"))
            continue
        valid.append(c)
    for sku, c in last_by_sku.items():
        valid.append(c)

    if known_skus is not None:
        kept: list[ValidRow] = []
        for c in valid:
            if c.sku in known_skus:
                kept.append(c)
            else:
                hint = ""
                alt = c.sku.lstrip("0")
                if alt != c.sku and alt in known_skus:
                    hint = f" Возможно, имелся в виду {alt}."
                errors.append(RowError(c.number, c.sku, "sku", "Товар с таким артикулом не найден." + hint))
        valid = kept

    valid.sort(key=lambda r: r.number)
    return valid, errors, len(parsed.rows)


def errors_csv(errors: list[RowError]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Строка", "Артикул", "Колонка", "Ошибка"])
    for e in errors:
        w.writerow([e.number, csv_safe(e.sku or ""), e.field, csv_safe(e.message)])
    return buf.getvalue()


def dump_payload(parsed: ParsedFile) -> str:
    return json.dumps({
        "columns": parsed.columns,
        "rows": [{"n": r.number, "c": [_jsonable(c) for c in r.cells], "f": r.formula_empty} for r in parsed.rows],
    }, ensure_ascii=False)


def load_payload(text: str) -> ParsedFile:
    data = json.loads(text)
    rows = [RawRow(number=r["n"], cells=r["c"], formula_empty=r.get("f", [])) for r in data["rows"]]
    return ParsedFile(columns=data["columns"], rows=rows)


def _jsonable(v):
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, float):
        return repr(v)
    return v
