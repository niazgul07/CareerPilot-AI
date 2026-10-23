"""Resume/job analysis helpers. Groq is optional; deterministic matching works without it."""
import json
import os
import re
from typing import Any

from dotenv import load_dotenv
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

load_dotenv()

MODEL_NAME = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

# Practical starter vocabulary; extend this list as the project grows.
SKILL_ALIASES = {
    "python": ["python", "python programming"],
    "java": ["java", "java programming"],
    "javascript": ["javascript", "js"],
    "typescript": ["typescript"],
    "fastapi": ["fastapi"],
    "flask": ["flask"],
    "django": ["django"],
    "rest api": ["rest api", "restful api", "api development"],
    "sql": ["sql", "postgresql", "mysql", "sqlite", "database management"],
    "git": ["git", "github", "gitlab"],
    "docker": ["docker", "containerization"],
    "machine learning": ["machine learning", "ml"],
    "pandas": ["pandas"],
    "numpy": ["numpy"],
    "scikit-learn": ["scikit-learn", "sklearn"],
    "cloud computing": ["cloud computing", "aws", "azure", "google cloud"],
    "html/css": ["html", "css"],
    "react": ["react", "react.js", "reactjs"],
    "communication": ["communication", "communicate effectively"],
    "problem-solving": ["problem-solving", "problem solving", "troubleshooting"],
    "testing": ["unit testing", "pytest", "testing"],
    "linux": ["linux", "ubuntu"],
    "data analysis": ["data analysis", "data analytics"],
}


def _groq_client():
    """Create the client only when needed, so missing keys don't crash app startup."""
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is not configured. Add it to your .env file to use AI features.")
    try:
        from groq import Groq
    except ImportError as exc:
        raise RuntimeError("Groq package is missing. Run: python -m pip install -r requirements.txt") from exc
    return Groq(api_key=api_key)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def extract_skills(text: str) -> list[str]:
    normalized = _normalize(text)
    found = []
    for skill, aliases in SKILL_ALIASES.items():
        for alias in aliases:
            # Word boundaries reduce accidental substring matches.
            pattern = r"(?<![a-z0-9+#])" + re.escape(alias.lower()) + r"(?![a-z0-9+#])"
            if re.search(pattern, normalized):
                found.append(skill)
                break
    return found


def calculate_match_score(resume_text: str, job_description: str) -> float:
    """Return text similarity percentage, not hiring probability or skill coverage."""
    resume_text = (resume_text or "").strip()
    job_description = (job_description or "").strip()
    if not resume_text or not job_description:
        raise ValueError("Resume text and job description are both required.")
    try:
        vectors = TfidfVectorizer(stop_words="english").fit_transform([resume_text, job_description])
        score = cosine_similarity(vectors[0], vectors[1])[0][0]
        return round(float(score) * 100, 2)
    except ValueError:
        # E.g. text contains only stop words or punctuation.
        return 0.0


def build_local_analysis(resume_text: str, job_description: str) -> dict[str, Any]:
    resume_skills = extract_skills(resume_text)
    job_skills = extract_skills(job_description)
    matched = [skill for skill in job_skills if skill in resume_skills]
    missing = [skill for skill in job_skills if skill not in resume_skills]
    skill_coverage = round(100 * len(matched) / len(job_skills), 2) if job_skills else 0.0
    return {
        "matching_skills": matched,
        "missing_skills": missing,
        "resume_skills": resume_skills,
        "job_skills": job_skills,
        "skill_coverage": skill_coverage,
        "recommendations": "Review",
        "explanation": "Local skill matching is based on a starter keyword list. Add a configured AI key for a richer explanation.",
        "ai_powered": False,
    }


def _extract_json(content: str) -> dict[str, Any]:
    content = (content or "").strip()
    content = re.sub(r"^```(?:json)?\s*", "", content, flags=re.IGNORECASE)
    content = re.sub(r"\s*```$", "", content)
    try:
        value = json.loads(content)
    except json.JSONDecodeError:
        start, end = content.find("{"), content.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("The AI returned an unexpected format. Please try again.")
        value = json.loads(content[start:end + 1])
    if not isinstance(value, dict):
        raise ValueError("The AI response was not a JSON object.")
    return value


def analyze_with_ai(resume_text: str, job_description: str) -> dict[str, Any]:
    """Return structured AI feedback. Raises a readable error if AI is unavailable."""
    client = _groq_client()
    prompt = f"""Compare the resume with the job description. Return valid JSON only with:
{{
  "match_percentage": number,
  "matching_skills": ["skills explicitly supported by resume"],
  "missing_skills": ["relevant skills not evidenced in resume"],
  "recommendations": "Review",
  "explanation": "2-3 concise sentences",
  "strengths": ["evidence-based strengths"],
  "improvements": ["specific honest improvement suggestions"]
}}
Use recommendations value Review, Strong alignment, or Needs development. This is not a hiring decision.
Do not invent qualifications or experience. Keep feedback grounded in the provided text.

RESUME:\n{resume_text[:7000]}

JOB DESCRIPTION:\n{job_description[:4000]}"""
    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=1400,
        temperature=0.1,
    )
    data = _extract_json(response.choices[0].message.content)
    local = build_local_analysis(resume_text, job_description)
    for key in ("matching_skills", "missing_skills", "strengths", "improvements"):
        if not isinstance(data.get(key), list):
            data[key] = local.get(key, [])
        data[key] = [str(item) for item in data[key]][:20]
    try:
        data["match_percentage"] = max(0, min(100, float(data.get("match_percentage", 0))))
    except (ValueError, TypeError):
        data["match_percentage"] = local["skill_coverage"]
    data["recommendations"] = str(data.get("recommendations", "Review"))
    data["explanation"] = str(data.get("explanation", "No explanation was returned."))
    data["ai_powered"] = True
    data["resume_skills"] = local["resume_skills"]
    data["job_skills"] = local["job_skills"]
    data["skill_coverage"] = local["skill_coverage"]
    return data


def generate_resume_suggestions(resume_text: str, job_description: str) -> dict[str, Any]:
    """Generate an evidence-based resume improvement plan using Groq."""
    client = _groq_client()
    prompt = f"""Act as a resume coach. Return valid JSON only:
{{
 "strengths": ["evidence-based strength"],
 "improvements": ["specific actionable improvement"],
 "keyword_suggestions": ["relevant job keyword to consider if truthful"],
 "project_suggestions": ["realistic project idea to build, not claim as completed"],
 "summary_suggestion": "a suggested professional summary grounded only in resume evidence"
}}
Never invent skills, employment, degrees, metrics, or achievements. Distinguish existing experience from ideas to learn/build.

RESUME:\n{resume_text[:7000]}

JOB DESCRIPTION:\n{job_description[:4000]}"""
    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=1400,
        temperature=0.2,
    )
    data = _extract_json(response.choices[0].message.content)
    for key in ("strengths", "improvements", "keyword_suggestions", "project_suggestions"):
        if not isinstance(data.get(key), list):
            data[key] = []
        data[key] = [str(item) for item in data[key]][:12]
    data["summary_suggestion"] = str(data.get("summary_suggestion", ""))
    return data
