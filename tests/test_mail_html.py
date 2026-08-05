"""
Created on 2026-08-05

@author: wf
"""

from tests.base_thunderbird import BaseThunderbirdTest
from thunderbird.mail import Mail


class TestMailHtml(BaseThunderbirdTest):
    """
    Test the sanitizing of mail html markup (#46).
    """

    def test_strip_scripts(self):
        """
        Test that script elements are removed while the rest of the markup survives.
        """
        test_cases = [
            (
                "<div>before<script>alert('x')</script>after</div>",
                "<div>beforeafter</div>",
            ),
            (
                "<div>a<SCRIPT type='text/javascript'>\nvar x=1;\n</SCRIPT>b</div>",
                "<div>ab</div>",
            ),
            # unclosed script tag - nicegui rejects the substring either way
            ("<div>a<script src='x.js'>b</div>", "<div>ab</div>"),
            ("<div>a</script>b</div>", "<div>ab</div>"),
            # markup without scripts stays untouched
            ("<div id='htmlMsg'>hello</div>", "<div id='htmlMsg'>hello</div>"),
            (None, ""),
        ]
        for html_markup, expected in test_cases:
            sanitized = Mail.strip_scripts(html_markup)
            self.assertEqual(expected, sanitized)
            self.assertNotIn("script", sanitized.lower())
