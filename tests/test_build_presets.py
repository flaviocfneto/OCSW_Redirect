"""Tests for the preset builder's name and area rules (tools/build_presets.py). No network."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import build_presets as b  # noqa: E402


@pytest.mark.parametrize("title,name", [
    ("DC26T22B AI for Productivity Improvers", "AI for Productivity"),
    ("AI for Productivity: Beginners", "AI for Productivity"),
    ("DC26T43I 3D 3D Modelling with Blender Improvers", "3D Modelling with Blender"),
    ("DC26T43G 3D Modelling with Blender Beginners", "3D Modelling with Blender"),
    ("PH26T11P (C) Life Skills - Living on a Budget / Money Saving Ideas", "Living on a Budget / Money Saving Ideas"),
    ("PH26T22K Life Skills - Living on a Budget / Money Saving Ideas", "Living on a Budget / Money Saving Ideas"),
    ("FL26W11D - Christmas Craft - Family Learning", "Christmas Craft"),
    ("FL26W22N Christmas Craft", "Christmas Craft"),
    ("FL26W31P Sustainable Christmas craft w/Embroidery", "Sustainable Christmas craft w/Embroidery"),
    ("PH26F43C Wellbeing- Budget Festive Gifts", "Budget Festive Gifts"),
    ("NCFE Level 2 Certificate in the Principles of Cyber Security", "Principles of Cyber Security"),
    ("DC26A52D L2 Certificate in Principles of Cyber Security", "Principles of Cyber Security"),
    ("DC26A41E Level 1 Award in Business Skills AAT", "Business Skills AAT"),
    ("English Functional Skills (Saltash)", "English Functional Skills"),
    ("Family Learning", "Family Learning"),
])
def test_course_name(title, name):
    assert b.course_name(title) == name


def test_bare_title_keeps_the_level():
    assert b.bare_title("DC26T43I 3D 3D Modelling with Blender Improvers") == "3D Modelling with Blender Improvers"
    assert b.bare_title("PH26T11P (C) Life Skills - Living on a Budget") == "Life Skills - Living on a Budget"


@pytest.mark.parametrize("slugs,area", [
    (["e-learningqualifications", "counselling"], "Counselling"),          # subject beats the general list
    (["healthandsocialcare", "e-learningqualifications"], "Health and social care"),
    (["e-learningqualifications"], "Online qualifications"),
    (["copy-of-health-social-care", "gcses"], "English and maths"),        # "Courses in Cornwall" is not a subject
    (["creativecourses", "wellbeing"], "Wellbeing and life skills"),       # fewer courses: more specific
    (["wellbeing", "languages"], "Wellbeing and life skills"),             # a tie keeps the first page
    (["general-4"], "Cookery"),
    (["meet-the-team"], None),
])
def test_page_area(slugs, area):
    linked = {"e-learningqualifications": 42, "counselling": 3, "healthandsocialcare": 4, "gcses": 2,
              "creativecourses": 5, "wellbeing": 3, "languages": 3, "general-4": 7,
              "copy-of-health-social-care": 2, "meet-the-team": 1}
    assert b.page_area(slugs, linked) == area


@pytest.mark.parametrize("title,area", [
    ("DC26A41E Level 1 Award in Business Skills AAT", "Accountancy and bookkeeping"),
    ("Skills Bootcamp Teaching Support and Learning in Schools", "Skills bootcamps"),
    ("HC26T11A Intro to Working in Schools", "Childcare and education"),
    ("Maths Functional Skills", "English and maths"),
    ("DC26T43G 3D Modelling with Blender Beginners", "Digital and creative"),
    ("PH26T22M Cook it Up - Batch Cooking", "Community courses"),
    ("Shekinah", "Other courses"),
])
def test_area_for_a_course_the_website_does_not_link(title, area):
    assert b.code_area(title) == area
