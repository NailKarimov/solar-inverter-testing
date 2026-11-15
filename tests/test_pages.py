"""The visual page ``docs/solar-inverter.html`` opened in a real browser.

The page carries a JavaScript twin of the simulator. ``site/test/twin.test.mjs`` proves that the twin
answers like the Python original; these tests prove that the page built around it works.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

pytestmark = [pytest.mark.pages, pytest.mark.once]

PAGE = Path(__file__).resolve().parent.parent / "docs" / "solar-inverter.html"
VIEWS = ("tour", "live", "wire", "replay", "bugs")
# planted bug -> the live check that must turn red, and no other
BUG_TO_CHECK = {
    "M21": "island",
    "M22": "reconnect",
    "M23": "limit",
    "M26": "trip",
    "M30": "soft",
    "M03": "crc",
    "M04": "unit",
    "M18": "refuse",
}
RUN_AHEAD = (
    "() => { const d = App.views.live.debug;"
    " for (let i = 0; i < 200; i++) d.tick(); for (let i = 0; i < 3; i++) d.probe(); }"
)


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    sync_api = pytest.importorskip(
        "playwright.sync_api", reason="Playwright is not installed: pip install -e '.[pages]'"
    )
    if not PAGE.exists():
        pytest.skip("docs/solar-inverter.html is not built: python scripts/build_pages.py")
    with sync_api.sync_playwright() as playwright:
        chromium = playwright.chromium.launch()
        yield chromium
        chromium.close()


@pytest.fixture
def page(browser: Any) -> Iterator[Any]:
    context = browser.new_context(viewport={"width": 1280, "height": 900}, locale="en-US")
    tab = context.new_page()
    tab.errors = []
    tab.on("pageerror", lambda error: tab.errors.append(str(error)))
    yield tab
    context.close()


def open_view(page: Any, view: str) -> None:
    page.goto(f"{PAGE.as_uri()}#{view}")
    page.wait_for_selector(f"#view-{view}.on")


def red_checks(page: Any) -> list[str]:
    result: list[str] = page.eval_on_selector_all(".check.fail", "els => els.map(e => e.dataset.check)")
    return result


@pytest.mark.parametrize("view", VIEWS)
def test_every_view_opens_without_a_script_error(page: Any, view: str) -> None:
    """Each of the five views of the visual page opens by its own address and runs without a script error."""
    open_view(page, view)
    page.wait_for_timeout(300)
    assert page.errors == []
    assert page.locator(f"#view-{view} h2").inner_text().strip()
    assert page.locator(".view.on").count() == 1


@pytest.mark.parametrize(("bug", "check"), BUG_TO_CHECK.items())
def test_planted_bug_turns_its_own_check_red(page: Any, bug: str, check: str) -> None:
    """On the live page, switching on a planted bug turns exactly the matching check red."""
    open_view(page, "live")
    page.click(f"label[for=bug-{bug}]")
    page.evaluate(RUN_AHEAD)
    page.wait_for_timeout(400)
    assert red_checks(page) == [check]
    assert page.errors == []


def test_healthy_inverter_keeps_every_check_green_for_a_day(page: Any) -> None:
    """Without a planted bug a whole simulated day, with an outage, a limit and overheating, turns no check red."""
    open_view(page, "live")
    page.evaluate("() => { const d = App.views.live.debug; for (let i = 0; i < 30; i++) d.tick(); }")
    for button in ("#live-grid", "#live-grid", "#live-limit-on", "#live-heat", "#live-heat"):
        page.click(button)
        page.evaluate("() => { const d = App.views.live.debug; for (let i = 0; i < 400; i++) d.tick(); d.probe(); }")
    page.evaluate("() => { const d = App.views.live.debug; for (let i = 0; i < 86400; i++) d.tick(); }")
    page.wait_for_timeout(400)
    assert red_checks(page) == []
    passed = page.eval_on_selector_all(".check.pass", "els => els.map(e => e.dataset.check)")
    assert set(passed) == {"island", "reconnect", "limit", "rated", "trip", "soft", "crc", "unit", "refuse"}


def test_language_switch_translates_the_page(page: Any) -> None:
    """The RU button turns the headings and the test titles into Russian, and EN turns them back."""
    open_view(page, "replay")
    english = page.locator("#view-replay h2").inner_text()
    page.click("#lang-ru")
    russian = page.locator("#view-replay h2").inner_text()
    assert english != russian
    assert any("а" <= letter <= "я" for letter in russian.lower())
    assert "Когда сеть пропадает" in page.locator("details.suite[open] .test").first.inner_text()
    page.click("#lang-en")
    assert page.locator("#view-replay h2").inner_text() == english


def test_replay_shows_the_bytes_of_a_test(page: Any) -> None:
    """Opening a test on the replay view shows its steps and the frames it exchanged, each with a plain sentence."""
    open_view(page, "replay")
    page.locator("details.suite[open] .test button").first.click()
    detail = page.locator("details.suite[open] .test .detail").first
    assert detail.locator(".fr").count() >= 4
    assert "Command: write" in detail.inner_text()


def test_noise_button_breaks_the_checksum(page: Any) -> None:
    """On the wire view, flipping one bit makes the two checksums differ and the verdict says the inverter is silent."""
    open_view(page, "wire")
    assert page.locator("#wire-noisebox .verdict.bad").count() == 0
    page.click("#wire-noise")
    assert page.locator("#wire-noisebox .verdict.bad").count() == 1
    assert page.locator("#wire-noisebox .hit").count() == 1
    sent, computed = page.locator("#wire-noisebox td.num").all_inner_texts()
    assert sent != computed


def test_page_fits_a_phone_screen(browser: Any) -> None:
    """At a phone width of 390 px no view scrolls sideways."""
    context = browser.new_context(viewport={"width": 390, "height": 800})
    tab = context.new_page()
    for view in VIEWS:
        open_view(tab, view)
        assert tab.evaluate("document.documentElement.scrollWidth") <= 390, view
    context.close()
