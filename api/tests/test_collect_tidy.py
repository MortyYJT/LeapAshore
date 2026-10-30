"""Program names and non-program pages from discovery (review of PR #51)."""

from app.collect.discover import listing_links
from app.collect.tidy import not_a_program, program_name, tidy_file

LISTINGS = ["https://www.example.edu.au/study/postgraduate/"]


def test_a_link_drops_the_css_of_an_inline_icon():
    html = ('<a href="/c/it">Information Technology <svg><style>.cls-1{fill:#000;stroke-width:0px;}</style>'
            '<path/></svg></a>')
    assert listing_links(html, "https://www.example.edu.au/study/")[0]["text"] == "Information Technology"


def test_css_left_in_a_stored_name_is_removed():
    assert program_name("Master of Business Administration (AI) .cls-1{fill:#000;stroke-width:0px;}", None) == \
        "Master of Business Administration (AI)"


def test_a_card_description_after_the_name_gives_way_to_the_page_heading():
    text = "Audiology (MSc) Train to assess and treat hearing & balance disorders in a 3-year, hands-on clinical program."
    assert program_name(text, "Audiology (MSc)") == "Audiology (MSc)"


def test_a_heading_that_is_not_part_of_the_link_text_is_not_used():
    text = "Ciencias y Tecnologías Analíticas y Bioanalíticas (conjunto con UAM, UC3M, UAH, URJC y USP-CEU)"
    assert program_name(text, "Universidad Complutense de Madrid") == text
    assert program_name("MSc Data Science", "Data") == "MSc Data Science"  # short names stay as they are


def test_a_bare_course_code_takes_the_heading_that_starts_with_it():
    assert program_name("CA10", "CA10 - Bachelor of Arts") == "CA10 - Bachelor of Arts"
    assert program_name("CA10", "Welcome") == "CA10"


def test_pages_that_are_not_one_taught_masters_program():
    assert not_a_program("Course Not Found", "https://www.example.edu.au/c/x", LISTINGS)
    assert not_a_program("CA99 - Associate Degree of Information Technology", "https://x.au/a", LISTINGS)
    assert not_a_program("Bachelor of Business", "https://x.au/b", LISTINGS)
    assert not_a_program("Higher Degree Research", "https://x.au/hdr", LISTINGS)
    assert not_a_program("Postgraduate application closing dates", "https://x.au/d", LISTINGS)
    # The listing itself, or another page of it.
    assert not_a_program("Postgraduate", "https://www.example.edu.au/study/postgraduate/?page=2", LISTINGS)
    assert not_a_program("Postgraduate", "https://www.example.edu.au/study/postgraduate", LISTINGS)


def test_masters_programs_are_kept():
    for name in ("MSc Data Science", "Master of Teaching (Secondary)", "Máster en Acceso a la Abogacía",
                 "Graduate Diploma / Master of Nursing", "Audiology (MSc)", "Laurea Magistrale in Fisica"):
        assert not_a_program(name, "https://x.au/m", LISTINGS) is None, name


def test_tidy_file_renames_drops_and_finds_the_cricos_code(tmp_path):
    root = tmp_path
    (root / "k").mkdir()
    (root / "k" / ("a" * 64 + ".html")).write_text("<h1>CA10 - Bachelor of Arts</h1>")
    (root / "k" / ("b" * 64 + ".html")).write_text("<h1>Master of Data Science</h1>")
    data = {"school_key": "k", "listing_urls": LISTINGS, "programs": [
        {"name": "CA10", "url": "https://x.au/ca10", "snapshot_sha256": "a" * 64},
        {"name": "Master of Data Science Learn to work with data at scale and more", "url": "https://x.au/mds",
         "snapshot_sha256": "b" * 64},
        {"name": "Postgraduate", "url": "https://www.example.edu.au/study/postgraduate/?page=3", "snapshot_sha256": "c" * 64},
    ]}
    tidied, report = tidy_file(data, {"cricos_institution": "X"}, root=root,
                               cricos=lambda institution: {"master of data science": "012345A"})
    assert [p["name"] for p in tidied["programs"]] == ["Master of Data Science"]
    assert tidied["programs"][0]["cricos_code"] == "012345A"
    assert report == {"renamed": 2, "dropped": 2, "cricos_codes": 1}
