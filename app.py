"""CareerPilot AI Resume Screener - dashboard edition.
All scores are transparent heuristic decision-support signals, not hiring probabilities.
"""
import csv
import io
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from analyzer import (
    analyze_with_ai,
    build_local_analysis,
    calculate_match_score,
    generate_resume_suggestions,
)
from resume_parser import clean_text, extract_text_from_pdf

load_dotenv()
st.set_page_config(
    page_title="CareerPilot AI | Resume Intelligence",
    page_icon="🧭",
    layout="wide",
    initial_sidebar_state="expanded",
)

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "careerpilot_history.db"

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Manrope:wght@500;600;700;800&display=swap');
:root { color-scheme: light; }
html, body, [class*="css"] { font-family: 'DM Sans', sans-serif; }
.block-container { max-width: 1450px; padding-top: 1.25rem; padding-bottom: 3rem; }
[data-testid="stSidebar"] { background: linear-gradient(180deg,#101a2c 0%,#111827 100%); }
[data-testid="stSidebar"] * { color: #edf3ff !important; }
.hero { padding: 1.55rem 1.8rem; border-radius: 20px; background: linear-gradient(115deg,#111d35 0%,#283d74 58%,#4c3d98 100%); color: white; margin-bottom: 1.2rem; box-shadow: 0 12px 30px rgba(37,55,103,.13); }
.hero h1 { font-family: 'Manrope',sans-serif; color: white; font-size: 2.05rem; font-weight: 800; margin: 0; }
.hero p { color: #dce7ff; margin: .4rem 0 0; font-size: 1rem; }
.eyebrow { color:#a8c5ff; font-size:.78rem; text-transform:uppercase; letter-spacing:.12em; font-weight:700; margin-bottom:.35rem; }
.panel { border:1px solid #e4eaf4; border-radius:16px; background:#fff; padding:1rem 1.1rem; }
.metric-label { color:#61718d; font-size:.82rem; font-weight:600; }
.metric-value { color:#152443; font-family:'Manrope',sans-serif; font-size:1.8rem; font-weight:800; margin:.15rem 0; }
.metric-note { color:#64748b; font-size:.78rem; }
.pill { display:inline-block; padding:.25rem .6rem; border-radius:999px; background:#e9f9f0; color:#087443; font-size:.78rem; font-weight:700; }
div[data-testid="stMetric"] { background:#fff; color:#152443; border:1px solid #e4eaf4; padding:1rem; border-radius:15px; box-shadow:0 3px 12px rgba(30,50,90,.025); }
div[data-testid="stMetric"] label, div[data-testid="stMetric"] [data-testid="stMetricLabel"], div[data-testid="stMetric"] [data-testid="stMetricValue"], div[data-testid="stMetric"] [data-testid="stMetricDelta"] { color:#152443 !important; -webkit-text-fill-color:#152443 !important; }
</style>
<div class="hero"><div class="eyebrow">Career intelligence workspace</div><h1>🧭 CareerPilot AI</h1><p>Resume screening, explainable skill matching, candidate insights, and practical career growth plans.</p></div>
""", unsafe_allow_html=True)


def db_connect():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db_connect() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS screenings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            analyzed_at TEXT NOT NULL,
            filename TEXT NOT NULL,
            job_title TEXT NOT NULL,
            text_similarity REAL NOT NULL,
            skill_coverage REAL NOT NULL,
            screening_score REAL NOT NULL,
            matched_skills TEXT NOT NULL,
            missing_skills TEXT NOT NULL,
            resume_skills TEXT NOT NULL,
            job_skills TEXT NOT NULL,
            explanation TEXT NOT NULL,
            recommendations TEXT NOT NULL,
            resume_text TEXT NOT NULL,
            job_description TEXT NOT NULL,
            ai_powered INTEGER NOT NULL DEFAULT 0
        )""")


def get_history(limit=500):
    with db_connect() as conn:
        rows = conn.execute("SELECT * FROM screenings ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(row) for row in rows]


def save_screening(record):
    with db_connect() as conn:
        conn.execute("""INSERT INTO screenings
        (analyzed_at,filename,job_title,text_similarity,skill_coverage,screening_score,matched_skills,missing_skills,resume_skills,job_skills,explanation,recommendations,resume_text,job_description,ai_powered)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
            record["analyzed_at"], record["filename"], record["job_title"], record["text_similarity"], record["skill_coverage"], record["screening_score"],
            json.dumps(record["matching_skills"]), json.dumps(record["missing_skills"]), json.dumps(record["resume_skills"]), json.dumps(record["job_skills"]),
            record["explanation"], record["recommendations"], record["resume_text"], record["job_description"], int(record["ai_powered"])
        ))
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def parse_json_list(value):
    try:
        parsed = json.loads(value or "[]")
        return parsed if isinstance(parsed, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def screening_score(skill_coverage, text_similarity):
    """Transparent heuristic score: 70% skill coverage + 30% text similarity."""
    return round(max(0, min(100, 0.70 * float(skill_coverage) + 0.30 * float(text_similarity))), 1)


def result_from_row(row):
    return {
        "id": row["id"], "analyzed_at": row["analyzed_at"], "filename": row["filename"], "job_title": row["job_title"],
        "text_similarity": row["text_similarity"], "skill_coverage": row["skill_coverage"], "screening_score": row["screening_score"],
        "matching_skills": parse_json_list(row["matched_skills"]), "missing_skills": parse_json_list(row["missing_skills"]),
        "resume_skills": parse_json_list(row["resume_skills"]), "job_skills": parse_json_list(row["job_skills"]),
        "explanation": row["explanation"], "recommendations": row["recommendations"], "resume_text": row["resume_text"],
        "job_description": row["job_description"], "ai_powered": bool(row["ai_powered"]),
    }


def percent_color(value):
    if value >= 75:
        return "🟢"
    if value >= 50:
        return "🟡"
    return "🟠"


def make_interview_questions(record):
    skills = record.get("matching_skills", [])
    gaps = record.get("missing_skills", [])
    title = record.get("job_title") or "this role"
    questions = [
        f"Walk me through one project from your resume that is most relevant to {title}.",
        "Describe a technical problem you faced, how you debugged it, and what you learned.",
        "How do you test your code and make sure a change has not broken existing functionality?",
    ]
    for skill in skills[:4]:
        questions.append(f"Tell me about a real project where you used {skill}. What was your contribution and result?")
    for skill in gaps[:3]:
        questions.append(f"What do you currently know about {skill}, and how would you approach learning or using it?")
    return questions[:10]


def make_roadmap(record):
    gaps = record.get("missing_skills", [])
    if not gaps:
        return [
            ("Polish", "Review the job description and make sure every listed skill is backed by a real example."),
            ("Prove", "Add project links, a clear README, and measurable outcomes where you can verify them."),
            ("Practice", "Prepare short STAR-style stories for your strongest relevant projects."),
        ]
    roadmap = []
    for index, skill in enumerate(gaps[:5], start=1):
        roadmap.append((f"Week {index}: {skill}", f"Learn the fundamentals of {skill}, complete one small practical exercise, and document what you built. Only add it to your resume after you have real experience with it."))
    roadmap.append(("Final step: evidence", "Update your resume with honest project evidence, links, and clear descriptions of your own contribution."))
    return roadmap


# FIX: use a callback to change radio state before Streamlit re-runs the script.
def go_to_screening():
    st.session_state["navigation"] = "New Screening"


init_db()
history = get_history()
with st.sidebar:
    st.markdown("## ✦ CareerPilot AI")
    st.caption("Your career, smarter")
    if "navigation" not in st.session_state:
        st.session_state["navigation"] = "Dashboard"
    page = st.radio(
        "Navigation",
        ["Dashboard", "New Screening", "Past Reports", "Resume Coach", "Interview Prep", "Learning Roadmap", "About & Scoring"],
        key="navigation",
        label_visibility="collapsed",
    )
    st.divider()
    st.markdown("**Hackathon highlights**")
    st.markdown("- Multi-resume screening\n- Explainable percentage score\n- Persistent screening history\n- Skill-gap roadmap\n- Downloadable reports")
    st.divider()
    if os.getenv("GROQ_API_KEY", "").strip():
        st.success("Groq AI key detected")
    else:
        st.info("Local analysis ready · Add GROQ_API_KEY for AI feedback")
    st.caption("Scores support review; they do not make hiring decisions.")

# Dashboard
if page == "Dashboard":
    st.subheader("👋 Welcome to your screening dashboard")
    st.caption("Track analyses, compare skill alignment, and find the next improvement to make.")
    total = len(history)
    avg_score = round(sum(float(x["screening_score"]) for x in history) / total, 1) if total else 0
    avg_coverage = round(sum(float(x["skill_coverage"]) for x in history) / total, 1) if total else 0
    roles = len(set(x["job_title"] for x in history))
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Resumes screened", total, help="Saved analyses on this computer")
    m2.metric("Average screening score", f"{avg_score:.1f}%", help="70% skill coverage + 30% text similarity")
    m3.metric("Average skill coverage", f"{avg_coverage:.1f}%")
    m4.metric("Job profiles", roles)
    st.divider()
    left, right = st.columns([1.35, 1], gap="large")
    with left:
        st.markdown("### 📈 Recent screening activity")
        if history:
            chart_data = [{"Candidate / file": x["filename"][:22], "Screening score (%)": float(x["screening_score"])} for x in history[:8]][::-1]
            st.bar_chart(pd.DataFrame(chart_data), x="Candidate / file", y="Screening score (%)", height=280)
        else:
            st.info("No screening history yet. Open **New Screening** to analyse your first resume.")
            st.markdown("**Your first workflow**\n1. Upload one or more text-based PDF resumes.\n2. Paste the job description.\n3. Run screening and review the score breakdown.")
    with right:
        st.markdown("### 🧭 Quick actions")
        st.write("**New screening** — compare one or several resumes against a role.")
        st.button("➕ Start a screening", type="primary", use_container_width=True, on_click=go_to_screening)
        st.write("**Candidate review** — inspect missing skills, AI feedback, and export reports.")
        if history:
            best = max(history, key=lambda x: float(x["screening_score"]))
            st.success(f"Top heuristic score: {best['filename']} · {best['screening_score']:.1f}%")
        st.caption("The score is a prioritization aid, not a prediction of job performance.")
    if history:
        st.markdown("### 🗂️ Latest saved reports")
        st.dataframe([{"Date": x["analyzed_at"], "Resume": x["filename"], "Job": x["job_title"], "Screening score": f"{x['screening_score']:.1f}%", "Skill coverage": f"{x['skill_coverage']:.1f}%"} for x in history[:5]], use_container_width=True, hide_index=True)

elif page == "New Screening":
    st.subheader("📄 Screen resumes against a role")
    st.caption("Upload one resume or a batch of PDFs. The transparent score helps organise review; it must not be used as the sole hiring criterion.")
    with st.form("screening_form", clear_on_submit=False):
        job_title = st.text_input("Target job title", placeholder="e.g., Junior Python Developer")
        job_description = st.text_area("Job description", height=190, placeholder="Paste responsibilities, required skills, and preferred qualifications...")
        uploaded_files = st.file_uploader("Upload resume PDFs", type=["pdf"], accept_multiple_files=True, help="Multiple files let you compare several resumes against the same job description.")
        use_ai = st.checkbox("Use Groq AI for richer assessment (requires GROQ_API_KEY)", value=bool(os.getenv("GROQ_API_KEY", "").strip()))
        submitted = st.form_submit_button("🔍 Screen resume(s)", type="primary", use_container_width=True)
    if submitted:
        if not uploaded_files:
            st.error("Please upload at least one PDF resume.")
        elif len((job_description or "").strip()) < 30:
            st.error("Please paste a complete job description (at least 30 characters).")
        else:
            run_results = []
            progress = st.progress(0, text="Starting screening...")
            errors = []
            for index, file in enumerate(uploaded_files):
                try:
                    file.seek(0)
                    resume_text = clean_text(extract_text_from_pdf(file))
                    if len(resume_text) < 40:
                        raise ValueError("Very little text was extracted; scanned PDFs need OCR.")
                    text_score = calculate_match_score(resume_text, job_description)
                    local = build_local_analysis(resume_text, job_description)
                    analysis = local
                    ai_powered = False
                    if use_ai:
                        try:
                            analysis = analyze_with_ai(resume_text, job_description)
                            ai_powered = True
                        except Exception as exc:
                            errors.append(f"{file.name}: AI feedback unavailable ({exc}); local analysis was saved.")
                    coverage = float(local["skill_coverage"])
                    score = screening_score(coverage, text_score)
                    record = {
                        "analyzed_at": datetime.now().strftime("%Y-%m-%d %H:%M"), "filename": file.name,
                        "job_title": job_title.strip() or "Untitled role", "text_similarity": text_score,
                        "skill_coverage": coverage, "screening_score": score,
                        "matching_skills": local["matching_skills"], "missing_skills": local["missing_skills"],
                        "resume_skills": local["resume_skills"], "job_skills": local["job_skills"],
                        "explanation": analysis.get("explanation", "Keyword-based skill comparison completed."),
                        "recommendations": analysis.get("recommendations", "Review"), "resume_text": resume_text,
                        "job_description": job_description.strip(), "ai_powered": ai_powered,
                    }
                    record["id"] = save_screening(record)
                    run_results.append(record)
                except Exception as exc:
                    errors.append(f"{file.name}: {exc}")
                progress.progress((index + 1) / len(uploaded_files), text=f"Processed {index + 1} of {len(uploaded_files)} resume(s)")
            st.session_state["latest_results"] = run_results
            st.session_state["latest_job_title"] = job_title.strip() or "Untitled role"
            st.session_state["latest_job_description"] = job_description.strip()
            if run_results:
                st.success(f"Screening complete: {len(run_results)} resume(s) saved to Past Reports.")
            for err in errors:
                st.warning(err)
    results = st.session_state.get("latest_results", [])
    if results:
        st.divider()
        st.markdown("### 🏁 Screening results")
        st.caption("Screening score = 70% detected skill coverage + 30% text similarity. This is a transparent heuristic, not a hiring probability.")
        sorted_results = sorted(results, key=lambda r: r["screening_score"], reverse=True)
        st.dataframe([{"Rank": i + 1, "Resume": r["filename"], "Screening score": f"{r['screening_score']:.1f}%", "Skill coverage": f"{r['skill_coverage']:.1f}%", "Text similarity": f"{r['text_similarity']:.1f}%", "Matched skills": len(r["matching_skills"]), "Skills to review": len(r["missing_skills"])} for i, r in enumerate(sorted_results)], use_container_width=True, hide_index=True)
        st.markdown("### Candidate-by-candidate breakdown")
        for record in sorted_results:
            with st.expander(f"{percent_color(record['screening_score'])} {record['filename']} · {record['screening_score']:.1f}% heuristic score"):
                a, b, c = st.columns(3)
                a.metric("Screening score", f"{record['screening_score']:.1f}%")
                b.metric("Skill coverage", f"{record['skill_coverage']:.1f}%")
                c.metric("Text similarity", f"{record['text_similarity']:.1f}%")
                x, y = st.columns(2)
                with x:
                    st.markdown("**Matching skills**")
                    st.write(", ".join(record["matching_skills"]) or "No skills matched from the built-in vocabulary.")
                with y:
                    st.markdown("**Skills to review**")
                    st.write(", ".join(record["missing_skills"]) or "No detected gaps; check the complete job requirements.")
                st.info(record["explanation"])
        csv_buffer = io.StringIO()
        writer = csv.DictWriter(csv_buffer, fieldnames=["rank", "filename", "job_title", "screening_score", "skill_coverage", "text_similarity", "matching_skills", "missing_skills", "analyzed_at"])
        writer.writeheader()
        for rank, record in enumerate(sorted_results, 1):
            writer.writerow({"rank": rank, "filename": record["filename"], "job_title": record["job_title"], "screening_score": record["screening_score"], "skill_coverage": record["skill_coverage"], "text_similarity": record["text_similarity"], "matching_skills": "; ".join(record["matching_skills"]), "missing_skills": "; ".join(record["missing_skills"]), "analyzed_at": record["analyzed_at"]})
        st.download_button("⬇️ Download screening comparison (CSV)", csv_buffer.getvalue(), file_name="careerpilot_screening_comparison.csv", mime="text/csv")

elif page == "Past Reports":
    st.subheader("🗂️ Past screening reports")
    st.caption("Reports are stored locally in a SQLite database on this computer.")
    all_history = get_history()
    if not all_history:
        st.info("No saved reports yet. Run a screening first.")
    else:
        search = st.text_input("Search by resume filename or job title", placeholder="Type a filename or role...")
        filtered = [x for x in all_history if search.lower() in (x["filename"] + " " + x["job_title"]).lower()]
        st.dataframe([{"ID": x["id"], "Date": x["analyzed_at"], "Resume": x["filename"], "Job": x["job_title"], "Screening score": f"{x['screening_score']:.1f}%", "Skill coverage": f"{x['skill_coverage']:.1f}%", "AI used": "Yes" if x["ai_powered"] else "No"} for x in filtered], use_container_width=True, hide_index=True)
        if filtered:
            selected_id = st.selectbox("Open report", options=[x["id"] for x in filtered], format_func=lambda val: next(f"#{x['id']} · {x['filename']} · {x['job_title']}" for x in filtered if x["id"] == val))
            selected = result_from_row(next(x for x in filtered if x["id"] == selected_id))
            c1, c2, c3 = st.columns(3)
            c1.metric("Screening score", f"{selected['screening_score']:.1f}%")
            c2.metric("Skill coverage", f"{selected['skill_coverage']:.1f}%")
            c3.metric("Text similarity", f"{selected['text_similarity']:.1f}%")
            st.markdown("**Matching skills**")
            st.write(", ".join(selected["matching_skills"]) or "None detected")
            st.markdown("**Skills to review**")
            st.write(", ".join(selected["missing_skills"]) or "None detected")
            st.markdown("**Assessment**")
            st.write(selected["explanation"])
            report = {k: v for k, v in selected.items() if k not in ("resume_text", "job_description")}
            st.download_button("Download selected report (JSON)", json.dumps(report, indent=2), file_name=f"screening_report_{selected_id}.json", mime="application/json")
        if st.button("Clear all local screening history", help="This permanently deletes saved history from this local project database."):
            st.session_state["confirm_clear_history"] = True
        if st.session_state.get("confirm_clear_history"):
            st.warning("This cannot be undone. Do you really want to delete all saved reports?")
            confirm_col, cancel_col = st.columns(2)
            if confirm_col.button("Yes, delete history", type="primary"):
                with db_connect() as conn:
                    conn.execute("DELETE FROM screenings")
                st.session_state.pop("confirm_clear_history", None)
                st.success("History cleared.")
                st.rerun()
            if cancel_col.button("Cancel"):
                st.session_state.pop("confirm_clear_history", None)
                st.rerun()

elif page == "Resume Coach":
    st.subheader("✨ Resume improvement coach")
    st.caption("Generate practical, evidence-based suggestions for your latest screened resume.")
    recent = get_history()
    if not recent:
        st.info("Run a screening first, then come back here for targeted suggestions.")
    else:
        selected_id = st.selectbox("Choose a screening", options=[x["id"] for x in recent], format_func=lambda val: next(f"{x['filename']} → {x['job_title']} ({x['analyzed_at']})" for x in recent if x["id"] == val))
        selected = result_from_row(next(x for x in recent if x["id"] == selected_id))
        st.write(f"Selected resume: **{selected['filename']}** for **{selected['job_title']}**")
        if st.button("Generate improvement plan", type="primary"):
            try:
                with st.spinner("Asking the AI coach for evidence-based suggestions..."):
                    st.session_state["coach_result"] = generate_resume_suggestions(selected["resume_text"], selected["job_description"])
                    st.session_state["coach_for_id"] = selected_id
                    st.session_state.pop("coach_error", None)
            except Exception as exc:
                st.session_state["coach_error"] = str(exc)
        if st.session_state.get("coach_error"):
            st.warning(st.session_state["coach_error"])
        suggestions = st.session_state.get("coach_result") if st.session_state.get("coach_for_id") == selected_id else None
        if suggestions:
            left, right = st.columns(2)
            with left:
                st.markdown("### 💪 Strengths")
                for item in suggestions.get("strengths", []):
                    st.success(item)
                st.markdown("### 🎯 Improvements")
                for item in suggestions.get("improvements", []):
                    st.warning(item)
            with right:
                st.markdown("### 🔑 Keywords to consider")
                st.write(", ".join(suggestions.get("keyword_suggestions", [])) or "No keyword suggestions returned.")
                st.markdown("### 🚀 Project ideas")
                for item in suggestions.get("project_suggestions", []):
                    st.write("• " + item)
            st.markdown("### 📝 Suggested professional summary")
            st.info(suggestions.get("summary_suggestion", "No summary suggestion returned."))
            st.caption("Only use claims that truthfully reflect your experience. Suggested projects are ideas, not completed work.")
            st.download_button("Download coach plan (JSON)", json.dumps(suggestions, indent=2), file_name="resume_improvement_plan.json", mime="application/json")

elif page == "Interview Prep":
    st.subheader("🎤 Interview preparation studio")
    st.caption("Practice questions are based on the selected role and detected skill matches/gaps.")
    recent = get_history()
    if not recent:
        st.info("Run a screening first to create role-specific interview questions.")
    else:
        selected_id = st.selectbox("Choose a screening", options=[x["id"] for x in recent], format_func=lambda val: next(f"{x['filename']} → {x['job_title']}" for x in recent if x["id"] == val))
        selected = result_from_row(next(x for x in recent if x["id"] == selected_id))
        questions = make_interview_questions(selected)
        st.markdown("### Your practice questions")
        for i, question in enumerate(questions, 1):
            with st.expander(f"Question {i}"):
                st.write(question)
                st.text_area("Draft your answer", key=f"answer_{selected_id}_{i}", height=90, placeholder="Use a real example: situation, task, action, result...")
        st.download_button("Download interview questions", "\n".join(f"{i}. {q}" for i, q in enumerate(questions, 1)), file_name="interview_practice_questions.txt", mime="text/plain")
        st.caption("Questions are practice prompts, not an assessment of candidate worth or a prediction of interview outcomes.")

elif page == "Learning Roadmap":
    st.subheader("🗺️ Personalized learning roadmap")
    st.caption("Turn detected gaps into practical learning steps; a missing keyword does not prove a person lacks that skill.")
    recent = get_history()
    if not recent:
        st.info("Run a screening first to generate a roadmap based on detected skill gaps.")
    else:
        selected_id = st.selectbox("Choose a screening", options=[x["id"] for x in recent], format_func=lambda val: next(f"{x['filename']} → {x['job_title']}" for x in recent if x["id"] == val))
        selected = result_from_row(next(x for x in recent if x["id"] == selected_id))
        st.markdown(f"### Roadmap for {selected['job_title']}")
        if selected["missing_skills"]:
            st.markdown("**Detected skills to review**: " + ", ".join(selected["missing_skills"]))
        else:
            st.success("No gaps were detected by the current keyword list. Review the full job description for requirements the tool may not recognise.")
        roadmap = make_roadmap(selected)
        for title, detail in roadmap:
            with st.container(border=True):
                st.markdown(f"**{title}**")
                st.write(detail)
        st.download_button("Download learning roadmap", "\n\n".join(f"{title}\n{detail}" for title, detail in roadmap), file_name="career_learning_roadmap.txt", mime="text/plain")

else:  # About & Scoring
    st.subheader("ℹ️ About CareerPilot AI")
    st.write("CareerPilot AI is a resume-to-job-description comparison tool built to help users understand wording overlap, detected skill matches, and practical next steps.")
    st.markdown("### How the screening score is calculated")
    st.markdown("**Screening score = 70% detected skill coverage + 30% text similarity**")
    st.progress(0.70, text="70% weight · detected skill coverage")
    st.progress(0.30, text="30% weight · TF-IDF text similarity")
    st.markdown("- **Skill coverage:** the share of skills detected in the job description that also appear in the resume, using the current built-in vocabulary.\n- **Text similarity:** a TF-IDF cosine similarity between the resume text and job description.\n- **AI assessment:** optional language-model feedback when a valid Groq key is configured. AI text can be wrong and must be checked.")
    st.warning("Important: these percentages are heuristic signals, not a probability of getting hired, not a measure of a person's worth, and not suitable as the sole basis for employment decisions. Keyword detection can miss synonyms and context; human review is essential.")
    st.markdown("### Privacy and data storage")
    st.write("Screening history is stored in a local SQLite file named `careerpilot_history.db` in the project folder. Do not screen resumes without appropriate permission, and do not commit the database or API key to a public repository.")

st.divider()
st.caption("CareerPilot AI · Explainable screening support, not automated hiring decisions.")
