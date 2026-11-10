from conftest import job
from jobhunter.scoring import classify, score_job, split_requirements, years_required

ECM_JD = """Junior ECM / BPM Developer
Requirements:
- Experience with IBM BAW and FileNet
- Knowledge of BPMN and workflow automation
- Java and SQL basics
- Fresh graduate or 0-1 years of experience
- Bachelor degree in Computer Science
Nice to have:
- Kubernetes
"""


def test_ecm_junior_is_excellent(profile, settings):
    r = score_job(job(title="Junior ECM Developer", description=ECM_JD), profile, settings)
    assert r["band"] == "excellent", r["explanation"]
    assert r["variant"] == "ecm_bpm"
    assert "kubernetes" in r["explanation"]["missing_preferred"]  # nice-to-have missing must not reject
    assert "kubernetes" not in r["explanation"]["missing_required"]


def test_senior_title_is_capped_to_archive(profile, settings):
    r = score_job(job(title="Senior Java Developer", description="Java Spring Boot SQL REST APIs backend microservices"), profile, settings)
    assert r["score"] <= 54 and r["band"] == "archive"


def test_four_years_required_is_capped(profile, settings):
    r = score_job(job(title="Java Developer", description="Requirements:\n- 4+ years of experience with Java and Spring Boot"), profile, settings)
    assert r["score"] <= 54


def test_remote_us_only_is_restricted_not_excellent(profile, settings):
    r = score_job(job(title="Junior Backend Developer", location="Remote",
                      description="Requirements:\n- Java, Spring Boot, SQL, REST APIs\n- Must be authorized to work in the US\n- 0-1 years of experience"), profile, settings)
    assert r["eligibility"] == "restricted" and r["band"] == "archive"


def test_remote_unknown_eligibility_never_excellent(profile, settings):
    r = score_job(job(title="Junior Java Developer", location="Remote",
                      description="Requirements:\n- Java, Spring Boot, SQL, REST APIs, backend, microservices\n- Fresh graduates welcome"), profile, settings)
    assert r["eligibility"] == "unknown" and r["score"] <= 84


def test_stub_without_description_is_capped(profile, settings):
    r = score_job(job(title="Junior Java Developer", description=""), profile, settings)
    assert r["needs_description"] and r["score"] <= 69


def test_foreign_language_requirement_noted(profile, settings):
    r = score_job(job(title="Junior Developer", location="Remote", description="Fluent German required. Java, SQL."), profile, settings)
    assert any("German".lower() in n.lower() for n in r["explanation"]["notes"])


def test_missing_required_skill_lowers_score(profile, settings):
    have = score_job(job(title="Junior Java Developer", description="Requirements:\n- Java, Spring Boot, SQL\n- Fresh graduate"), profile, settings)
    lack = score_job(job(title="Junior Java Developer", description="Requirements:\n- Java, Kubernetes, AWS, Terraform\n- Fresh graduate"), profile, settings)
    assert lack["score"] < have["score"]
    assert {"kubernetes", "aws", "terraform"} <= set(lack["explanation"]["missing_required"])


def test_missing_headline_skill_blocks_excellent(profile, settings):
    r = score_job(job(title="Full Stack Developer", location="Giza, Egypt",
                      description="Requirements:\n- React, TypeScript, Node.js, MongoDB\n- 1-2 years of experience\n- Build responsive web UI and REST API backend"),
                  profile, settings)
    assert "react" in r["explanation"]["missing_required"]
    assert r["band"] != "excellent"


def test_react_is_not_claimed(profile):
    from jobhunter.skills import profile_skill_set
    mine = profile_skill_set(profile)
    assert "react" not in mine and "kubernetes" not in mine
    assert {"doxis", "ibm baw", "java", "node.js", "express"} <= mine


def test_classify_generic_title_uses_description(settings):
    from jobhunter.scoring import _cfg
    cat, variant = classify(job(title="Software Engineer", description="Build services with Node.js and Express"), _cfg())
    assert (cat, variant) == ("node", "node")


def test_requirement_split_and_years():
    req, pref = split_requirements("", "Requirements:\n- Java\nPreferred:\n- Docker\n- Redis")
    assert req == {"java"} and pref == {"docker", "redis"}
    assert years_required("2-3 years of experience in Java") == 2
    assert years_required("Founded 10 years ago") is None
