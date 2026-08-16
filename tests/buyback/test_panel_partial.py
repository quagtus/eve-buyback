from django.template import Context, Template


def render(template_string, **context):
    return Template(template_string).render(Context(context))


def test_panel_renders_frame_and_fill_as_nested_elements():
    """The hairline only exists if BOTH clip layers are present."""
    html = render(
        '{% include "buyback/_panel.html" with title="Assets" body="x" %}'
    )

    assert "eve-frame" in html
    assert "eve-fill" in html
    assert html.index("eve-frame") < html.index("eve-fill"), "frame must wrap fill"


def test_panel_shows_an_uppercase_header_when_titled():
    html = render('{% include "buyback/_panel.html" with title="Assets" %}')

    assert "Assets" in html
    assert "uppercase" in html


def test_panel_omits_the_header_strip_when_untitled():
    html = render('{% include "buyback/_panel.html" %}')

    assert "eve-frame" in html
    assert "uppercase" not in html
