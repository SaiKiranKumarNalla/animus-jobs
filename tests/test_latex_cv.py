import pytest

from jobagent import latex_cv

CV = {"name": "Ada L_vel", "headline": "R&D 100% engineer", "contact": ["Paris", {"text": "site", "url": "https://x.org/a#b"}],
      "summary": "Cost $5 ~ {braces} ^", "sections": [{"title": "Experience", "entries": [
          {"heading": "Engineer", "org": "Acme", "place": "Paris", "dates": "2020–2024", "bullets": ["Built C# tools", ""]}]}],
      "skills": [{"group": "Code", "items": ["Python", "C++"]}]}


def test_render_escapes_special_chars():
    tex = latex_cv.render(CV)
    for s in (r"L\_vel", r"R\&D 100\% engineer", r"\$5", r"\textasciitilde{}", r"\{braces\}", r"C\# tools"):
        assert s in tex
    assert r"\href{https://x.org/a\#b}{site}" in tex and tex.count(r"\item") == 1


@pytest.mark.skipif(not latex_cv.compiler(), reason="no LaTeX installed")
def test_compiles_to_pdf(tmp_path):
    tex = tmp_path / "cv.tex"; tex.write_text(latex_cv.render(CV))
    assert latex_cv.compile_pdf(tex).read_bytes()[:4] == b"%PDF"
