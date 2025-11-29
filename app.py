import os
import tempfile
import zipfile
from flask import Flask, render_template, request
from eval import evaluate_project

app = Flask(__name__)
app.secret_key = "secret123"     # needed for flash messages


@app.route("/")
def index():
    return render_template("upload.html")


@app.route("/evaluate", methods=["POST"])
def evaluate():
    # Check file
    uploaded = request.files.get("zipfile")
    if not uploaded:
        return render_template("upload.html", error="Please upload a zip file.")

    # Create temporary directory
    temp_dir = tempfile.mkdtemp(prefix="student_")
    zip_path = os.path.join(temp_dir, "project.zip")
    uploaded.save(zip_path)

    # Extract ZIP
    extract_path = os.path.join(temp_dir, "project")
    os.makedirs(extract_path, exist_ok=True)

    try:
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(extract_path)
    except Exception as e:
        return render_template("upload.html", error=f"Error extracting ZIP: {e}")

    # Run evaluator
    try:
        result = evaluate_project(extract_path)
    except Exception as e:
        return render_template("result.html", error=f"Evaluator crashed: {e}")

    # Display results
    print("DEBUG RESULT:", result)
    return render_template("result.html", report=result)



if __name__ == "__main__":
    app.run(debug=True)
