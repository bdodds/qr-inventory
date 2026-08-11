#!/usr/bin/env python3
import html
import json
import os
import secrets
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import psycopg2
import psycopg2.extras


BASE_DIR = Path(__file__).resolve().parent

DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = os.environ.get("DB_PORT", "5432")
DB_NAME = os.environ.get("DB_NAME", "inventory")
DB_USER = os.environ.get("DB_USER", "inventory")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "inventory")


def raw_connect():
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME, user=DB_USER, password=DB_PASSWORD
    )


class DBConnection:
    """Thin wrapper around a psycopg2 connection so call sites can keep using the
    sqlite3-style `db.execute(...).fetchone()/.fetchall()` pattern."""

    def __init__(self, connection):
        self._connection = connection

    def execute(self, query, params=None):
        cursor = self._connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute(query, params or ())
        return cursor

    def executescript(self, script):
        cursor = self._connection.cursor()
        cursor.execute(script)
        cursor.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is None:
                self._connection.commit()
            else:
                self._connection.rollback()
        finally:
            self._connection.close()
        return False


def connect_db():
    return DBConnection(raw_connect())


def wait_for_db(retries=30, delay=1.0):
    last_error = None
    for _ in range(retries):
        try:
            raw_connect().close()
            return
        except psycopg2.OperationalError as error:
            last_error = error
            time.sleep(delay)
    raise RuntimeError(f"Could not connect to the database after {retries} attempts") from last_error


def initialize_db():
    wait_for_db()
    with connect_db() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS categories (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS containers (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                qr_token TEXT NOT NULL UNIQUE,
                category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
                description TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS items (
                id SERIAL PRIMARY KEY,
                container_id INTEGER NOT NULL REFERENCES containers(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 1 CHECK (quantity >= 0),
                notes TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_items_container_id ON items(container_id);
            CREATE INDEX IF NOT EXISTS idx_items_name ON items(name);
            """
        )


def new_qr_token(db):
    while True:
        token = secrets.token_urlsafe(8)
        exists = db.execute("SELECT 1 FROM containers WHERE qr_token = %s", (token,)).fetchone()
        if exists is None:
            return token


def row_to_dict(row):
    return dict(row) if row is not None else None


def qr_svg(text):
    matrix = make_qr_matrix(text)
    border = 4
    scale = 8
    size = len(matrix)
    image_size = (size + border * 2) * scale
    rects = []

    for y, row in enumerate(matrix):
        for x, dark in enumerate(row):
            if dark:
                rects.append(
                    f'<rect x="{(x + border) * scale}" y="{(y + border) * scale}" '
                    f'width="{scale}" height="{scale}"/>'
                )

    escaped_text = html.escape(text, quote=True)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {image_size} {image_size}" '
        'shape-rendering="crispEdges" role="img">'
        f"<title>{escaped_text}</title>"
        '<rect width="100%" height="100%" fill="#fff"/>'
        f'<g fill="#000">{"".join(rects)}</g>'
        "</svg>"
    )


def make_qr_matrix(text):
    version = 5
    size = version * 4 + 17
    data_codewords = 108
    ecc_codewords = 26
    payload = text.encode("utf-8")
    if len(payload) > 106:
        raise ValueError("QR URL is too long")

    data = qr_data_codewords(payload, data_codewords)
    ecc = reed_solomon_remainder(data, ecc_codewords)
    bits = []
    for codeword in data + ecc:
        bits.extend(((codeword >> bit) & 1) == 1 for bit in range(7, -1, -1))

    modules = [[False] * size for _ in range(size)]
    function_modules = [[False] * size for _ in range(size)]

    def set_function(x, y, dark):
        if 0 <= x < size and 0 <= y < size:
            modules[y][x] = dark
            function_modules[y][x] = True

    def draw_finder(x, y):
        for dy in range(-1, 8):
            for dx in range(-1, 8):
                xx = x + dx
                yy = y + dy
                dark = (
                    0 <= dx <= 6
                    and 0 <= dy <= 6
                    and (dx in (0, 6) or dy in (0, 6) or (2 <= dx <= 4 and 2 <= dy <= 4))
                )
                set_function(xx, yy, dark)

    def draw_alignment(cx, cy):
        for dy in range(-2, 3):
            for dx in range(-2, 3):
                set_function(cx + dx, cy + dy, max(abs(dx), abs(dy)) != 1)

    draw_finder(0, 0)
    draw_finder(size - 7, 0)
    draw_finder(0, size - 7)

    for i in range(8, size - 8):
        dark = i % 2 == 0
        set_function(6, i, dark)
        set_function(i, 6, dark)

    draw_alignment(30, 30)
    set_function(8, 4 * version + 9, True)
    draw_format_bits(modules, function_modules, 0)

    bit_index = 0
    upward = True
    x = size - 1
    while x > 0:
        if x == 6:
            x -= 1
        for i in range(size):
            y = size - 1 - i if upward else i
            for dx in range(2):
                xx = x - dx
                if not function_modules[y][xx]:
                    modules[y][xx] = bit_index < len(bits) and bits[bit_index]
                    bit_index += 1
        upward = not upward
        x -= 2

    for y in range(size):
        for x in range(size):
            if not function_modules[y][x] and (x + y) % 2 == 0:
                modules[y][x] = not modules[y][x]

    draw_format_bits(modules, function_modules, 0)
    return modules


def qr_data_codewords(payload, capacity):
    bits = []

    def append(value, length):
        bits.extend(((value >> bit) & 1) == 1 for bit in range(length - 1, -1, -1))

    append(0b0100, 4)
    append(len(payload), 8)
    for byte in payload:
        append(byte, 8)

    capacity_bits = capacity * 8
    append(0, min(4, capacity_bits - len(bits)))
    while len(bits) % 8 != 0:
        bits.append(False)

    data = []
    for i in range(0, len(bits), 8):
        value = 0
        for bit in bits[i : i + 8]:
            value = (value << 1) | int(bit)
        data.append(value)

    pad = 0xEC
    while len(data) < capacity:
        data.append(pad)
        pad = 0x11 if pad == 0xEC else 0xEC
    return data


def draw_format_bits(modules, function_modules, mask):
    size = len(modules)
    data = (1 << 3) | mask
    remainder = data
    for _ in range(10):
        remainder = (remainder << 1) ^ (((remainder >> 9) & 1) * 0x537)
    bits = ((data << 10) | remainder) ^ 0x5412

    def bit(i):
        return ((bits >> i) & 1) == 1

    def set_module(x, y, dark):
        modules[y][x] = dark
        function_modules[y][x] = True

    for i in range(6):
        set_module(8, i, bit(i))
    set_module(8, 7, bit(6))
    set_module(8, 8, bit(7))
    set_module(7, 8, bit(8))
    for i in range(9, 15):
        set_module(14 - i, 8, bit(i))

    for i in range(8):
        set_module(size - 1 - i, 8, bit(i))
    for i in range(8, 15):
        set_module(8, size - 15 + i, bit(i))
    set_module(8, size - 8, True)


def reed_solomon_remainder(data, degree):
    divisor = reed_solomon_divisor(degree)
    result = [0] * degree
    for byte in data:
        factor = byte ^ result.pop(0)
        result.append(0)
        for i, coefficient in enumerate(divisor):
            result[i] ^= gf_multiply(coefficient, factor)
    return result


def reed_solomon_divisor(degree):
    result = [0] * (degree - 1) + [1]
    root = 1
    for _ in range(degree):
        for i in range(degree):
            result[i] = gf_multiply(result[i], root)
            if i + 1 < degree:
                result[i] ^= result[i + 1]
        root = gf_multiply(root, 2)
    return result


def gf_multiply(x, y):
    result = 0
    while y:
        if y & 1:
            result ^= x
        x <<= 1
        if x & 0x100:
            x ^= 0x11D
        y >>= 1
    return result & 0xFF


class InventoryHandler(SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(BASE_DIR / "static"), **kwargs)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/inventory":
            self.send_json(self.get_inventory())
            return
        if path.startswith("/api/containers/") and path.endswith("/qr.svg"):
            container_id = self.extract_id(path, 2)
            self.send_container_qr(container_id)
            return
        if path == "/api/search":
            query = urlparse(self.path).query
            term = ""
            for part in query.split("&"):
                if part.startswith("q="):
                    term = part[2:].replace("+", " ")
            self.send_json(self.search_inventory(term))
            return
        if path == "/print-all":
            query = parse_qs(urlparse(self.path).query)
            ids_param = query.get("ids", [""])[0]
            ids = None
            if ids_param:
                ids = []
                for piece in ids_param.split(","):
                    piece = piece.strip()
                    if piece.isdigit():
                        ids.append(int(piece))
            self.send_print_all_labels(ids)
            return
        if path.startswith("/print/"):
            token = path.strip("/").split("/", 1)[1]
            self.send_print_label(token)
            return
        if path.startswith("/container/"):
            self.path = "/index.html"
            return super().do_GET()
        if path == "/":
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path
        data = self.read_json()

        if path == "/api/categories":
            self.send_json(self.create_category(data), status=201)
            return

        if path == "/api/containers":
            self.send_json(self.create_container(data), status=201)
            return

        if path.startswith("/api/containers/") and path.endswith("/items"):
            container_id = self.extract_id(path, 2)
            self.send_json(self.create_item(container_id, data), status=201)
            return

        self.send_error_json(404, "Route not found")

    def do_PUT(self):
        path = urlparse(self.path).path
        data = self.read_json()

        if path.startswith("/api/categories/"):
            category_id = self.extract_id(path, 2)
            self.send_json(self.update_category(category_id, data))
            return

        if path.startswith("/api/containers/"):
            container_id = self.extract_id(path, 2)
            self.send_json(self.update_container(container_id, data))
            return

        if path.startswith("/api/items/"):
            item_id = self.extract_id(path, 2)
            self.send_json(self.update_item(item_id, data))
            return

        self.send_error_json(404, "Route not found")

    def do_DELETE(self):
        path = urlparse(self.path).path

        if path.startswith("/api/categories/"):
            category_id = self.extract_id(path, 2)
            self.delete_category(category_id)
            self.send_json({"ok": True})
            return

        if path.startswith("/api/containers/"):
            container_id = self.extract_id(path, 2)
            self.delete_container(container_id)
            self.send_json({"ok": True})
            return

        if path.startswith("/api/items/"):
            item_id = self.extract_id(path, 2)
            self.delete_item(item_id)
            self.send_json({"ok": True})
            return

        self.send_error_json(404, "Route not found")

    def get_inventory(self):
        with connect_db() as db:
            categories = [
                row_to_dict(row)
                for row in db.execute("SELECT * FROM categories ORDER BY lower(name)")
            ]
            containers = [
                row_to_dict(row)
                for row in db.execute(
                    """
                    SELECT c.*,
                           cat.name AS category_name,
                           COUNT(i.id) AS item_count,
                           COALESCE(SUM(i.quantity), 0) AS total_quantity
                    FROM containers c
                    LEFT JOIN categories cat ON cat.id = c.category_id
                    LEFT JOIN items i ON i.container_id = c.id
                    GROUP BY c.id, cat.name
                    ORDER BY lower(c.name)
                    """
                )
            ]
            items = [
                row_to_dict(row)
                for row in db.execute(
                    """
                    SELECT i.*, c.name AS container_name
                    FROM items i
                    JOIN containers c ON c.id = i.container_id
                    ORDER BY lower(i.name)
                    """
                )
            ]
        return {"categories": categories, "containers": containers, "items": items}

    def search_inventory(self, term):
        like = f"%{term.strip()}%"
        if not term.strip():
            return {"containers": [], "items": []}

        with connect_db() as db:
            containers = [
                row_to_dict(row)
                for row in db.execute(
                    """
                    SELECT c.*,
                           cat.name AS category_name,
                           COUNT(i.id) AS item_count,
                           COALESCE(SUM(i.quantity), 0) AS total_quantity
                    FROM containers c
                    LEFT JOIN categories cat ON cat.id = c.category_id
                    LEFT JOIN items i ON i.container_id = c.id
                    WHERE c.name ILIKE %s OR c.description ILIKE %s OR cat.name ILIKE %s
                    GROUP BY c.id, cat.name
                    ORDER BY lower(c.name)
                    """,
                    (like, like, like),
                )
            ]
            items = [
                row_to_dict(row)
                for row in db.execute(
                    """
                    SELECT i.*, c.name AS container_name
                    FROM items i
                    JOIN containers c ON c.id = i.container_id
                    WHERE i.name ILIKE %s OR i.notes ILIKE %s OR c.name ILIKE %s
                    ORDER BY lower(i.name)
                    """,
                    (like, like, like),
                )
            ]
        return {"containers": containers, "items": items}

    def create_container(self, data):
        name = self.required_text(data, "name")
        description = self.optional_text(data, "description")

        try:
            with connect_db() as db:
                category_id = self.category_id(data, db)
                cursor = db.execute(
                    """
                    INSERT INTO containers (name, description, qr_token, category_id)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id
                    """,
                    (name, description, new_qr_token(db), category_id),
                )
                container_id = cursor.fetchone()["id"]
                row = db.execute(
                    """
                    SELECT c.*, cat.name AS category_name, 0 AS item_count, 0 AS total_quantity
                    FROM containers c
                    LEFT JOIN categories cat ON cat.id = c.category_id
                    WHERE c.id = %s
                    """,
                    (container_id,),
                ).fetchone()
        except psycopg2.IntegrityError:
            self.send_error_json(409, "A container with that name already exists")
            raise StopIteration

        return row_to_dict(row)

    def create_category(self, data):
        name = self.required_text(data, "name")
        try:
            with connect_db() as db:
                cursor = db.execute(
                    "INSERT INTO categories (name) VALUES (%s) RETURNING id", (name,)
                )
                category_id = cursor.fetchone()["id"]
                row = db.execute("SELECT * FROM categories WHERE id = %s", (category_id,)).fetchone()
        except psycopg2.IntegrityError:
            self.send_error_json(409, "A category with that name already exists")
            raise StopIteration

        return row_to_dict(row)

    def update_category(self, category_id, data):
        name = self.required_text(data, "name")
        try:
            with connect_db() as db:
                cursor = db.execute(
                    """
                    UPDATE categories
                    SET name = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    """,
                    (name, category_id),
                )
                if cursor.rowcount == 0:
                    self.send_error_json(404, "Category not found")
                    raise StopIteration
                row = db.execute("SELECT * FROM categories WHERE id = %s", (category_id,)).fetchone()
        except psycopg2.IntegrityError:
            self.send_error_json(409, "A category with that name already exists")
            raise StopIteration

        return row_to_dict(row)

    def delete_category(self, category_id):
        with connect_db() as db:
            exists = db.execute("SELECT id FROM categories WHERE id = %s", (category_id,)).fetchone()
            if exists is None:
                self.send_error_json(404, "Category not found")
                raise StopIteration
            db.execute(
                "UPDATE containers SET category_id = NULL, updated_at = CURRENT_TIMESTAMP WHERE category_id = %s",
                (category_id,),
            )
            db.execute("DELETE FROM categories WHERE id = %s", (category_id,))

    def send_container_qr(self, container_id):
        with connect_db() as db:
            container = db.execute(
                "SELECT id, qr_token FROM containers WHERE id = %s",
                (container_id,),
            ).fetchone()

        if container is None:
            self.send_error_json(404, "Container not found")
            return

        try:
            body = qr_svg(self.container_url(container["qr_token"])).encode("utf-8")
        except ValueError as error:
            self.send_error_json(400, str(error))
            return

        self.send_response(200)
        self.send_header("Content-Type", "image/svg+xml")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_print_label(self, token):
        with connect_db() as db:
            container = db.execute(
                """
                SELECT c.*,
                       cat.name AS category_name,
                       COUNT(i.id) AS item_count,
                       COALESCE(SUM(i.quantity), 0) AS total_quantity
                FROM containers c
                LEFT JOIN categories cat ON cat.id = c.category_id
                LEFT JOIN items i ON i.container_id = c.id
                WHERE c.qr_token = %s
                GROUP BY c.id, cat.name
                """,
                (token,),
            ).fetchone()

        if container is None:
            self.send_error_json(404, "Container not found")
            return

        url = self.container_url(container["qr_token"])
        body = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{html.escape(container["name"])} QR label</title>
    <style>
      body {{
        margin: 0;
        font-family: Arial, sans-serif;
        color: #111;
        background: #f4f4f5;
      }}
      main {{
        width: min(4in, calc(100vw - 24px));
        margin: 24px auto;
        background: #fff;
        border: 1px solid #ddd;
        padding: 0.22in;
        text-align: center;
      }}
      img {{
        width: 2.6in;
        height: 2.6in;
      }}
      h1 {{
        margin: 0.1in 0 0.04in;
        font-size: 18pt;
      }}
      .category {{
        display: inline-block;
        margin: 0 0 0.05in;
        border: 1px solid #c4b5fd;
        border-radius: 999px;
        padding: 0.04in 0.12in;
        color: #5b21b6;
        font-size: 11pt;
        font-weight: 700;
      }}
      p {{
        margin: 0.02in 0;
        font-size: 10pt;
        overflow-wrap: anywhere;
      }}
      button {{
        display: block;
        margin: 18px auto;
        padding: 10px 14px;
        font: inherit;
      }}
      @media print {{
        body {{
          background: #fff;
        }}
        main {{
          margin: 0;
          border: 0;
        }}
        button {{
          display: none;
        }}
      }}
    </style>
  </head>
  <body>
    <main>
      <img alt="QR code" src="/api/containers/{container["id"]}/qr.svg" />
      <h1>{html.escape(container["name"])}</h1>
      {self.category_label_html(container["category_name"])}
      <p>{container["item_count"]} item types, {container["total_quantity"]} units</p>
      <p>{html.escape(url)}</p>
    </main>
    <button type="button" onclick="window.print()">Print</button>
  </body>
</html>""".encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_print_all_labels(self, ids=None):
        with connect_db() as db:
            if ids is not None:
                if not ids:
                    containers = []
                else:
                    placeholders = ",".join(["%s"] * len(ids))
                    containers = db.execute(
                        f"""
                        SELECT c.*,
                               cat.name AS category_name,
                               COUNT(i.id) AS item_count,
                               COALESCE(SUM(i.quantity), 0) AS total_quantity
                        FROM containers c
                        LEFT JOIN categories cat ON cat.id = c.category_id
                        LEFT JOIN items i ON i.container_id = c.id
                        WHERE c.id IN ({placeholders})
                        GROUP BY c.id, cat.name
                        ORDER BY lower(c.name)
                        """,
                        ids,
                    ).fetchall()
            else:
                containers = db.execute(
                    """
                    SELECT c.*,
                           cat.name AS category_name,
                           COUNT(i.id) AS item_count,
                           COALESCE(SUM(i.quantity), 0) AS total_quantity
                    FROM containers c
                    LEFT JOIN categories cat ON cat.id = c.category_id
                    LEFT JOIN items i ON i.container_id = c.id
                    GROUP BY c.id, cat.name
                    ORDER BY lower(c.name)
                    """
                ).fetchall()

        pages = []
        for page_start in range(0, len(containers), 4):
            labels = []
            for container in containers[page_start : page_start + 4]:
                url = self.container_url(container["qr_token"])
                labels.append(
                    f"""
        <article class="label">
          <img alt="QR code for {html.escape(container["name"], quote=True)}" src="/api/containers/{container["id"]}/qr.svg" />
          <h2>{html.escape(container["name"])}</h2>
          {self.category_label_html(container["category_name"])}
          <p>{container["item_count"]} item types, {container["total_quantity"]} units</p>
          <p class="url">{html.escape(url)}</p>
        </article>"""
                )
            pages.append(f'      <section class="page">{"".join(labels)}</section>')

        if not pages:
            empty_message = (
                "No containers selected." if ids is not None else "Add containers before printing QR labels."
            )
            pages.append(
                f"""
      <section class="page empty-page">
        <article class="empty-label">
          <h2>No containers to print</h2>
          <p>{html.escape(empty_message)}</p>
        </article>
      </section>"""
            )

        page_title = "Selected container QR labels" if ids is not None else "All container QR labels"

        body = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{html.escape(page_title)}</title>
    <style>
      @page {{
        size: letter;
        margin: 0.35in;
      }}
      * {{
        box-sizing: border-box;
      }}
      body {{
        margin: 0;
        font-family: Arial, sans-serif;
        color: #111;
        background: #f4f4f5;
      }}
      .actions {{
        display: flex;
        justify-content: center;
        gap: 10px;
        padding: 18px;
      }}
      button {{
        border: 1px solid #bbb;
        border-radius: 8px;
        background: #fff;
        padding: 10px 14px;
        font: inherit;
        font-weight: 700;
      }}
      .page {{
        width: 8.5in;
        min-height: 11in;
        margin: 0 auto 24px;
        padding: 0.35in;
        display: grid;
        grid-template-columns: repeat(2, 1fr);
        grid-template-rows: repeat(2, 1fr);
        gap: 0.18in;
        background: #fff;
        break-after: page;
        page-break-after: always;
      }}
      .page:last-child {{
        break-after: auto;
        page-break-after: auto;
      }}
      .label {{
        border: 1px solid #d4d4d8;
        display: grid;
        grid-template-rows: auto auto auto 1fr;
        justify-items: center;
        align-content: center;
        min-height: 4.88in;
        padding: 0.18in;
        text-align: center;
      }}
      img {{
        width: 2.45in;
        height: 2.45in;
      }}
      h2 {{
        width: 100%;
        margin: 0.12in 0 0.04in;
        font-size: 18pt;
        line-height: 1.1;
        overflow-wrap: anywhere;
      }}
      p {{
        margin: 0.02in 0;
        font-size: 10pt;
      }}
      .category {{
        display: inline-block;
        margin: 0 0 0.04in;
        border: 1px solid #c4b5fd;
        border-radius: 999px;
        padding: 0.04in 0.12in;
        color: #5b21b6;
        font-size: 10pt;
        font-weight: 700;
      }}
      .url {{
        width: 100%;
        color: #333;
        font-size: 8pt;
        overflow-wrap: anywhere;
      }}
      .empty-page {{
        display: grid;
        place-items: center;
      }}
      .empty-label {{
        text-align: center;
      }}
      @media print {{
        body {{
          background: #fff;
        }}
        .actions {{
          display: none;
        }}
        .page {{
          width: auto;
          min-height: auto;
          height: calc(11in - 0.7in);
          margin: 0;
          padding: 0;
          gap: 0.18in;
        }}
      }}
    </style>
  </head>
  <body>
    <div class="actions">
      <button type="button" onclick="window.print()">Print labels</button>
    </div>
{"".join(pages)}
  </body>
</html>""".encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def container_url(self, token):
        host = self.headers.get("Host") or "127.0.0.1:8000"
        return f"http://{host}/container/{token}"

    def category_label_html(self, category_name):
        if not category_name:
            return ""
        return f'<p class="category">{html.escape(category_name)}</p>'

    def update_container(self, container_id, data):
        name = self.required_text(data, "name")
        description = self.optional_text(data, "description")

        try:
            with connect_db() as db:
                category_id = self.category_id(data, db)
                cursor = db.execute(
                    """
                    UPDATE containers
                    SET name = %s, description = %s, category_id = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    """,
                    (name, description, category_id, container_id),
                )
                if cursor.rowcount == 0:
                    self.send_error_json(404, "Container not found")
                    raise StopIteration
                row = db.execute(
                    """
                    SELECT c.*, cat.name AS category_name
                    FROM containers c
                    LEFT JOIN categories cat ON cat.id = c.category_id
                    WHERE c.id = %s
                    """,
                    (container_id,),
                ).fetchone()
        except psycopg2.IntegrityError:
            self.send_error_json(409, "A container with that name already exists")
            raise StopIteration

        return row_to_dict(row)

    def delete_container(self, container_id):
        with connect_db() as db:
            cursor = db.execute("DELETE FROM containers WHERE id = %s", (container_id,))
            if cursor.rowcount == 0:
                self.send_error_json(404, "Container not found")
                raise StopIteration

    def create_item(self, container_id, data):
        name = self.required_text(data, "name")
        quantity = self.quantity(data)
        notes = self.optional_text(data, "notes")

        with connect_db() as db:
            container = db.execute("SELECT id FROM containers WHERE id = %s", (container_id,)).fetchone()
            if container is None:
                self.send_error_json(404, "Container not found")
                raise StopIteration
            cursor = db.execute(
                """
                INSERT INTO items (container_id, name, quantity, notes)
                VALUES (%s, %s, %s, %s)
                RETURNING id
                """,
                (container_id, name, quantity, notes),
            )
            item_id = cursor.fetchone()["id"]
            row = db.execute(
                """
                SELECT i.*, c.name AS container_name
                FROM items i
                JOIN containers c ON c.id = i.container_id
                WHERE i.id = %s
                """,
                (item_id,),
            ).fetchone()
        return row_to_dict(row)

    def update_item(self, item_id, data):
        name = self.required_text(data, "name")
        quantity = self.quantity(data)
        notes = self.optional_text(data, "notes")

        with connect_db() as db:
            cursor = db.execute(
                """
                UPDATE items
                SET name = %s, quantity = %s, notes = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (name, quantity, notes, item_id),
            )
            if cursor.rowcount == 0:
                self.send_error_json(404, "Item not found")
                raise StopIteration
            row = db.execute(
                """
                SELECT i.*, c.name AS container_name
                FROM items i
                JOIN containers c ON c.id = i.container_id
                WHERE i.id = %s
                """,
                (item_id,),
            ).fetchone()
        return row_to_dict(row)

    def delete_item(self, item_id):
        with connect_db() as db:
            cursor = db.execute("DELETE FROM items WHERE id = %s", (item_id,))
            if cursor.rowcount == 0:
                self.send_error_json(404, "Item not found")
                raise StopIteration

    def read_json(self):
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            return {}
        try:
            return json.loads(self.rfile.read(content_length).decode("utf-8"))
        except json.JSONDecodeError:
            self.send_error_json(400, "Request body must be valid JSON")
            raise StopIteration

    def required_text(self, data, key):
        value = str(data.get(key, "")).strip()
        if not value:
            self.send_error_json(400, f"{key} is required")
            raise StopIteration
        return value

    def optional_text(self, data, key):
        return str(data.get(key, "")).strip()

    def quantity(self, data):
        try:
            value = int(data.get("quantity", 1))
        except (TypeError, ValueError):
            self.send_error_json(400, "quantity must be a number")
            raise StopIteration
        if value < 0:
            self.send_error_json(400, "quantity cannot be negative")
            raise StopIteration
        return value

    def category_id(self, data, db):
        raw_value = data.get("category_id")
        if raw_value in (None, ""):
            return None
        try:
            value = int(raw_value)
        except (TypeError, ValueError):
            self.send_error_json(400, "category_id must be a number")
            raise StopIteration
        exists = db.execute("SELECT id FROM categories WHERE id = %s", (value,)).fetchone()
        if exists is None:
            self.send_error_json(400, "Category not found")
            raise StopIteration
        return value

    def extract_id(self, path, index):
        parts = path.strip("/").split("/")
        try:
            return int(parts[index])
        except (IndexError, ValueError):
            self.send_error_json(400, "Invalid resource id")
            raise StopIteration

    def send_json(self, payload, status=200):
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_error_json(self, status, message):
        self.send_json({"error": message}, status=status)

    def handle_one_request(self):
        try:
            super().handle_one_request()
        except StopIteration:
            pass


def main():
    initialize_db()
    host = "0.0.0.0"
    port = 8000
    server = ThreadingHTTPServer((host, port), InventoryHandler)
    print(f"Inventory app listening on {host}:{port}")
    print(f"Open it locally at http://127.0.0.1:{port}")
    print(f"Database: postgresql://{DB_USER}@{DB_HOST}:{DB_PORT}/{DB_NAME}")
    server.serve_forever()


if __name__ == "__main__":
    main()
