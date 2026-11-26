import sqlite3
from contextlib import closing
from pathlib import Path
from sys import float_info

from flask import Flask, jsonify, request

app = Flask(__name__)

DB_NAME = Path(__file__).with_name("online-store.db")
PRODUCT_FIELDS = ("name", "price", "category", "image")
ALLOWED_CATEGORIES = ("electronics", "education", "food")


def connect_db():
    connection = sqlite3.connect(DB_NAME)
    connection.row_factory = sqlite3.Row
    return connection


def init_db():
    with closing(connect_db()) as connection, connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS coupons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE NOT NULL,
                discount INTEGER NOT NULL
            )
        """)

        connection.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                price REAL NOT NULL,
                category TEXT NOT NULL,
                image TEXT NOT NULL
            )
        """)


def add_sample_data():
    coupons = [
        ("WELCOME10", 10),
        ("SAVE15", 15),
        ("SPOOKY25", 25),
        ("VIP50", 50),
        ("HOLIDAY20", 20),
    ]

    products = [
        ("Laptop", 899.99, "electronics", "laptop.jpg"),
        ("Headphones", 79.99, "electronics", "headphones.jpg"),
        ("Python Workbook", 24.99, "education", "workbook.jpg"),
        ("Granola Bars", 5.99, "food", "granola.jpg"),
        ("USB Cable", 9.99, "electronics", "usb-cable.jpg"),
    ]

    with closing(connect_db()) as connection, connection:
        connection.executemany("""
            INSERT OR IGNORE INTO coupons (code, discount)
            VALUES (?, ?)
        """, coupons)

        connection.executemany("""
            INSERT OR IGNORE INTO products (name, price, category, image)
            VALUES (?, ?, ?, ?)
        """, products)


def error_response(message, status_code):
    return jsonify(success=False, message=message), status_code


@app.get("/api/health")
def health_check():
    return jsonify(status="OK"), 200


@app.post("/api/coupons")
def create_coupon():
    coupon = request.get_json(silent=True)

    if not isinstance(coupon, dict):
        return error_response("A JSON object is required", 400)

    code = coupon.get("code")
    discount = coupon.get("discount")

    if not isinstance(code, str) or not code.strip():
        return error_response("A valid coupon code is required", 400)

    if type(discount) is not int or not 0 <= discount <= 100:
        return error_response("Discount must be an integer between 0 and 100", 400)

    code = code.strip()

    try:
        with closing(connect_db()) as connection, connection:
            result = connection.execute("""
                INSERT INTO coupons (code, discount)
                VALUES (?, ?)
            """, (code, discount))
            coupon_id = result.lastrowid
    except sqlite3.IntegrityError:
        return error_response("Coupon code already exists", 409)

    return jsonify(
        success=True,
        message="Coupon created successfully",
        data={"id": coupon_id, "code": code, "discount": discount},
    ), 201


@app.get("/api/coupons")
def get_coupons():
    with closing(connect_db()) as connection:
        coupons = connection.execute(
            "SELECT * FROM coupons ORDER BY id"
        ).fetchall()

    return jsonify(
        success=True,
        message="Coupons retrieved successfully",
        data=[dict(coupon) for coupon in coupons],
    ), 200


@app.get("/api/coupons/<int:coupon_id>")
def get_coupon_by_id(coupon_id):
    with closing(connect_db()) as connection:
        coupon = connection.execute(
            "SELECT * FROM coupons WHERE id = ?", (coupon_id,)
        ).fetchone()

    if coupon is None:
        return error_response("Coupon not found", 404)

    return jsonify(
        success=True,
        message="Coupon retrieved successfully",
        data=dict(coupon),
    ), 200


@app.delete("/api/coupons/<int:coupon_id>")
def delete_coupon_by_id(coupon_id):
    with closing(connect_db()) as connection, connection:
        connection.execute("DELETE FROM coupons WHERE id = ?", (coupon_id,))

    return jsonify(
        success=True,
        message="Coupon deleted successfully",
    ), 200


@app.get("/api/products")
def get_products():
    with closing(connect_db()) as connection:
        products = connection.execute(
            "SELECT * FROM products ORDER BY id"
        ).fetchall()

    return jsonify(
        success=True,
        message="Products retrieved successfully",
        data=[dict(product) for product in products],
    ), 200


@app.get("/api/products/<int:product_id>")
def get_product_by_id(product_id):
    with closing(connect_db()) as connection:
        product = connection.execute(
            "SELECT * FROM products WHERE id = ?", (product_id,)
        ).fetchone()

    if product is None:
        return error_response(f"Product {product_id} not found", 404)

    return jsonify(
        success=True,
        message="Product retrieved successfully",
        data=dict(product),
    ), 200


@app.put("/api/products/<int:product_id>")
def update_product(product_id):
    with closing(connect_db()) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        product = connection.execute(
            "SELECT * FROM products WHERE id = ?", (product_id,)
        ).fetchone()

        if product is None:
            return error_response(f"Product {product_id} not found", 404)

        changes = request.get_json(silent=True)

        if (
            not isinstance(changes, dict)
            or not changes
            or changes.keys() - set(PRODUCT_FIELDS)
        ):
            return error_response(
                "Send a JSON object with name, price, category, or image", 400
            )

        if "category" in changes and changes["category"] not in ALLOWED_CATEGORIES:
            return error_response(
                "Category must be electronics, education, or food", 400
            )

        for field in ("name", "image"):
            if field in changes:
                value = changes[field]
                if not isinstance(value, str) or not value.strip():
                    return error_response(
                        f"{field.capitalize()} must be a nonempty string", 400
                    )
                changes[field] = value.strip()

        if "price" in changes:
            price = changes["price"]
            if type(price) not in (int, float) or not 0 <= price <= float_info.max:
                return error_response("Price must be a finite, nonnegative number", 400)

        updated_product = dict(product)
        updated_product.update(changes)

        try:
            connection.execute("""
                UPDATE products
                SET name = ?, price = ?, category = ?, image = ?
                WHERE id = ?
            """, (
                updated_product["name"],
                updated_product["price"],
                updated_product["category"],
                updated_product["image"],
                product_id,
            ))
        except sqlite3.IntegrityError:
            return error_response("A product with that name already exists", 409)

        saved_product = connection.execute(
            "SELECT * FROM products WHERE id = ?", (product_id,)
        ).fetchone()

    return jsonify(
        success=True,
        message="Product updated successfully",
        data=dict(saved_product),
    ), 200


@app.delete("/api/products/<int:product_id>")
def delete_product(product_id):
    with closing(connect_db()) as connection, connection:
        result = connection.execute(
            "DELETE FROM products WHERE id = ?", (product_id,)
        )

        if result.rowcount == 0:
            return error_response(f"Product {product_id} not found", 404)

    return jsonify(
        success=True,
        message=f"Product {product_id} deleted successfully",
    ), 200


init_db()

if __name__ == "__main__":
    app.run(debug=True)