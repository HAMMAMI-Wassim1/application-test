# app.py
import streamlit as st
import pandas as pd
import sqlite3
import subprocess
import os
import time
from datetime import datetime, timedelta
from statistics import mean
import matplotlib.pyplot as plt

# --- Directories ---
LOG_DIR = "logs"
GRAPH_DIR = "graphs"
DB_FILE = "test_results.db"
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(GRAPH_DIR, exist_ok=True)

# ---------------- DB ----------------
def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS test_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                test_name TEXT,
                execution_date TEXT,
                duration REAL,
                status TEXT
            );
            """
        )
        conn.commit()

def save_test_result(test_name, duration, status):
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO test_results (test_name, execution_date, duration, status)
            VALUES (?, ?, ?, ?)
            """,
            (test_name, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), float(duration), status),
        )
        conn.commit()

# ---------------- Logic ----------------
def get_recent_tests(limit=50, search=None):
    with sqlite3.connect(DB_FILE) as conn:
        query = "SELECT * FROM test_results"
        params = ()
        if search:
            query += " WHERE test_name LIKE ? OR status LIKE ?"
            params = (f"%{search}%", f"%{search}%")
        query += " ORDER BY datetime(execution_date) DESC LIMIT ?"
        params += (limit,)
        df = pd.read_sql_query(query, conn, params=params)
    return df

def get_kpis(days=7):
    since_dt = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    with sqlite3.connect(DB_FILE) as conn:
        rows = conn.execute("SELECT duration, status FROM test_results WHERE execution_date >= ?", (since_dt,)).fetchall()
    durations = [d for d, _ in rows if d is not None]
    avg = mean(durations) if durations else 0.0
    total = len(rows)
    successes = sum(1 for _d, s in rows if s == "Pass")
    rate = (successes / total * 100.0) if total else 0.0
    return total, rate, avg

def run_robot_tests(file_paths, browser="chrome"):
    results = []
    for file_path in file_paths:
        test_name = os.path.basename(file_path)
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        log_file = os.path.join(LOG_DIR, f"{os.path.splitext(test_name)[0]}_{timestamp}.html")
        try:
            cmd = ["robot", "--variable", f"BROWSER:{browser}", "--log", log_file, file_path]
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
            output_lines = []
            if proc.stdout:
                for line in proc.stdout:
                    output_lines.append(line)
            proc.wait()
            duration = sum(1 for _ in output_lines)  # crude approximation if needed
            status = "Pass" if proc.returncode == 0 else "Fail"
            save_test_result(test_name, duration, status)
            results.append((test_name, status, "\n".join(output_lines)))
        except Exception as e:
            save_test_result(test_name, 0.0, "Fail")
            results.append((test_name, "Fail", str(e)))
    return results

def delete_old_tests(days=10):
    threshold = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute("DELETE FROM test_results WHERE execution_date < ?", (threshold,))
        conn.commit()

# ---------------- Streamlit App ----------------
st.set_page_config(page_title="Test Automation Hub", layout="wide")
init_db()

st.title("Test Automation Hub - Web")

# --- Sidebar ---
st.sidebar.header("Actions")
uploaded_files = st.sidebar.file_uploader("Ajouter des fichiers Robot (.robot)", accept_multiple_files=True, type=["robot"])
browser = st.sidebar.selectbox("Navigateur", ["chrome", "firefox", "edge"])
if st.sidebar.button("Lancer les Tests"):
    if uploaded_files:
        file_paths = []
        for f in uploaded_files:
            path = os.path.join("temp_uploads", f.name)
            os.makedirs("temp_uploads", exist_ok=True)
            with open(path, "wb") as out:
                out.write(f.read())
            file_paths.append(path)
        with st.spinner("Exécution des tests..."):
            results = run_robot_tests(file_paths, browser)
        st.success("Tests terminés !")
        for name, status, logs in results:
            st.write(f"**{name}**: {status}")
            with st.expander("Voir les logs"):
                st.text(logs)
    else:
        st.warning("Veuillez sélectionner au moins un fichier.")

if st.sidebar.button("Supprimer tests > 10 jours"):
    delete_old_tests(10)
    st.success("Ancien tests supprimés.")

# --- KPIs ---
st.subheader("KPIs (7 derniers jours)")
total, rate, avg = get_kpis()
col1, col2, col3 = st.columns(3)
col1.metric("Total tests", total)
col2.metric("Taux de succès", f"{rate:.1f}%")
col3.metric("Durée moyenne", f"{avg:.2f}s")

# --- Recherche / Historique ---
st.subheader("Historique des Tests")
search_term = st.text_input("Rechercher (nom ou statut)")
df = get_recent_tests(search=search_term)
st.dataframe(df)

# --- Graphiques ---
st.subheader("Distribution des Durées")
if not df.empty:
    fig, ax = plt.subplots()
    ax.hist(df["duration"].dropna(), bins=10, edgecolor="black")
    ax.set_xlabel("Durée (s)")
    ax.set_ylabel("Nombre de tests")
    st.pyplot(fig)

st.subheader("Tendances des Tests (Pass/Fail par jour)")
with sqlite3.connect(DB_FILE) as conn:
    rows = conn.execute(
        """
        SELECT DATE(execution_date) AS d,
               SUM(CASE WHEN status='Pass' THEN 1 ELSE 0 END) AS successes,
               SUM(CASE WHEN status='Fail' THEN 1 ELSE 0 END) AS failures
        FROM test_results
        GROUP BY DATE(execution_date)
        ORDER BY DATE(execution_date)
        """
    ).fetchall()
if rows:
    dates = [r[0] for r in rows]
    successes = [r[1] for r in rows]
    failures = [r[2] for r in rows]
    fig, ax = plt.subplots(figsize=(9,4))
    ax.plot(dates, successes, marker="o", label="Pass")
    ax.plot(dates, failures, marker="o", label="Fail")
    ax.set_xlabel("Date")
    ax.set_ylabel("Nombre de tests")
    ax.set_title("Tendances des Tests")
    ax.legend()
    plt.xticks(rotation=45)
    st.pyplot(fig)

# --- Export ---
st.subheader("Exporter les résultats")
if not df.empty:
    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button("Télécharger CSV", csv, "tests_export.csv", "text/csv")
    excel_path = "export.xlsx"
    df.to_excel(excel_path, index=False, engine="openpyxl")
    with open(excel_path, "rb") as f:
        st.download_button("Télécharger Excel", f, "tests_export.xlsx")
