import os
import json
import importlib.util
import sqlite3
import traceback
import ast
import subprocess

# -----------------------------
# Utility: Dynamic module import
# -----------------------------
def dynamic_import(path, module_name="candidate_module"):
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# -----------------------------
# Utility: Load README.json
# -----------------------------
def load_metadata(project_dir):
    readme_path = os.path.join(project_dir, "README.json")
    if not os.path.exists(readme_path):
        raise Exception("❌ Missing README.json – naming conventions unknown.")

    with open(readme_path, "r") as f:
        return json.load(f)


# -----------------------------
# Utility: Score helper
# -----------------------------
class Score:
    def __init__(self):
        self.total = 0
        self.earned = 0
        self.details = []

    def add(self, points, condition, success_msg, fail_msg):
        self.total += points
        if condition:
            self.earned += points
            self.details.append("✔ " + success_msg)
        else:
            self.details.append("❌ " + fail_msg)


# -----------------------------
# Core Evaluator
# -----------------------------
def evaluate_project(project_dir):
    report = {}
    score = Score()

    try:
        meta = load_metadata(project_dir)
    except Exception as e:
        return {"error": str(e)}

    # Extract metadata
    crud_file = meta.get("crud_module")
    crud_class_name = meta.get("crud_class")
    db_adapter_file = meta.get("db_adapter")
    sample_data = meta.get("sample_data", {}).get("create", {})

    if not crud_file or not crud_class_name:
        return {"error": "README.json must contain CRUD module + class name."}

    crud_path = os.path.join(project_dir, crud_file)
    db_path = os.path.join(project_dir, db_adapter_file)

    # -------------------------
    # Test 1: File existence
    # -------------------------
    score.add(
        10,
        os.path.exists(crud_path),
        "CRUD module found",
        "CRUD module missing",
    )

    score.add(
        10,
        os.path.exists(db_path),
        "DB adapter file found",
        "DB adapter file missing",
    )

    if not os.path.exists(crud_path):
        return finalize(score, report)

    # -------------------------
    # Test 2: Import class
    # -------------------------
    try:
        mod = dynamic_import(crud_path, "crud_module")
        CRUDClass = getattr(mod, crud_class_name)
        crud_obj = CRUDClass()
        imported = True
    except Exception as e:
        imported = False
        score.details.append("❌ Could not import CRUD class: " + str(e))

    score.add(
        20,
        imported,
        "CRUD class imported successfully",
        "Failed to load CRUD class",
    )

    if not imported:
        return finalize(score, report)

    # -------------------------
    # Test 3: Method existence
    # -------------------------
    required = ["create", "read", "update", "delete"]

    for m in required:
        score.add(
            5,
            hasattr(crud_obj, m),
            f"Method {m}() found",
            f"Method {m}() missing"
        )

    # Stop if critical methods missing
    if not all(hasattr(crud_obj, m) for m in required):
        return finalize(score, report)

    # -------------------------
    # Test 4: SQLite Patch Simulation
    # -------------------------
    # This replaces candidate's DB logic so tests won't modify real DB
    db_mod = dynamic_import(db_path, "db_module")

    def fake_connection():
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        return conn

    try:
        setattr(db_mod, meta.get("db_connect_fn", "get_connection"), fake_connection)
        patched_db = True
    except Exception as e:
        patched_db = False
        score.details.append("❌ Cannot patch DB connection: " + str(e))

    score.add(
        10,
        patched_db,
        "Database connection successfully sandboxed",
        "Unable to sandbox database calls"
    )

    if not patched_db:
        return finalize(score, report)

    # -------------------------
    # Test 5: CRUD functional test
    # -------------------------
    try:
        conn = fake_connection()
        cur = conn.cursor()

        # Basic schema (ID + all user fields)
        table_name = list(meta.get("tables").values())[0]
        fields = ", ".join(f"{k} TEXT" for k in sample_data.keys())
        cur.execute(f"CREATE TABLE {table_name} (id INTEGER PRIMARY KEY, {fields})")
        conn.commit()

        # Inject fake DB into candidate
        setattr(crud_obj, "conn_override", fake_connection)

        # RUN TESTS
        crud_obj.create(sample_data)
        read_item = crud_obj.read(sample_data["id"])
        updated = crud_obj.update(sample_data["id"], {"name": "Updated"})
        deleted = crud_obj.delete(sample_data["id"])

        passed = all([read_item, updated, deleted])

    except Exception as e:
        passed = False
        score.details.append("❌ CRUD runtime error: " + traceback.format_exc())

    score.add(
        30,
        passed,
        "CRUD operations successfully executed",
        "CRUD functional test failed"
    )

    # -------------------------
    # Test 6: SQL Injection Safety
    # -------------------------
    try:
        conn = fake_connection()
        cur = conn.cursor()
        cur.execute(f"CREATE TABLE {table_name} (id INTEGER PRIMARY KEY, name TEXT)")
        conn.commit()

        crud_obj.create({"id": 999, "name": "Robert'); DROP TABLE users; --"})

        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,)
        )
        still_exists = cur.fetchone() is not None

    except Exception:
        still_exists = False

    score.add(
        20,
        still_exists,
        "SQL injection protection appears safe",
        "SQL injection vulnerability detected"
    )

    # -------------------------
    # Test 7: Code Quality
    # -------------------------
    try:
        result = subprocess.run(["pycodestyle", crud_path], capture_output=True, text=True)
        is_clean = (result.returncode == 0)
    except FileNotFoundError:
        is_clean = True  # allow if pycodestyle not installed

    score.add(
        10,
        is_clean,
        "Code is PEP8 clean",
        "Code style violations found"
    )

    return finalize(score, report)


# -----------------------------
# Final Formatter
# -----------------------------
def finalize(score, report):
    report["score"] = round(score.earned, 2)
    report["max_score"] = score.total
    report["details"] = score.details
    return report
