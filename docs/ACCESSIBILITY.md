# Accessibility of web UI v2

Web UI v2 (`/v2/…`) targets **BITV 2.0**, which requires **EN 301 549**, whose
web chapter 9 is **WCAG 2.1 level A + AA**. BITV-Test step numbers are the
EN 301 549 clause numbers (WCAG 1.4.3 → 9.1.4.3).

`tests/a11y/` checks as much of this as a machine can, in a real browser
(Playwright + Chromium, rules by [axe-core](https://github.com/dequelabs/axe-core)
4.13, vendored in `tests/a11y/vendor/`). Every page (`/v2/`, `/v2/history`,
`/v2/watches`, `/v2/tools`, `/v2/kb`) is checked **in every UI language**
(`zing/i18n/locales/*.json`: de, en, es, fr, it, pt, zh), in light and dark
theme, as loaded and with every disclosure opened (rendered report, advanced
options, monitor details) and every tab panel shown.

```bash
pip install -e '.[web,a11y]'
playwright install chromium            # or ZING_A11Y_CHROMIUM=/path/to/chrome
pytest -m a11y                         # add -n auto with pytest-xdist
```

Findings are also written to `a11y-report.json` (`ZING_A11Y_REPORT` moves it).
In CI the `accessibility (informational)` job runs the suite without failing
the pipeline and uploads that file. It becomes a required check once the suite
is green.

## Coverage by BITV / EN 301 549 test step

**auto**: decided by the tests. **partial**: the tests catch the common failures,
and a person still judges the rest. **manual**: needs a person.

| Step | WCAG 2.1 criterion | How | Test |
|---|---|---|---|
| 9.1.1.1 | Non-text content | partial: names of images, icons, buttons; whether alt text is *meaningful* is manual | axe `image-alt`, `svg-img-alt`, `button-name`, … |
| 9.1.2.x | Time-based media | n/a: the UI has no audio or video | — |
| 9.1.3.1 | Info and relationships | partial: ARIA validity, lists, tables, labels, landmarks, heading levels | axe; `test_heading_structure`; `test_consistent_navigation_and_landmarks` |
| 9.1.3.2 | Meaningful sequence | manual (Tab order is checked under 9.2.4.3) | — |
| 9.1.3.3 | Sensory characteristics | manual | — |
| 9.1.3.4 | Orientation | auto | `test_orientation_not_locked` |
| 9.1.3.5 | Identify input purpose | auto for `autocomplete` values | axe `autocomplete-valid` |
| 9.1.4.1 | Use of colour | partial: links in text | axe `link-in-text-block` |
| 9.1.4.2 | Audio control | n/a | — |
| 9.1.4.3 | Contrast (minimum) | auto, light + dark | axe `color-contrast` |
| 9.1.4.4 | Resize text | auto: 200 % zoom, nothing scrolls sideways or is cut off | `test_resize_text_200_percent`; axe `meta-viewport` |
| 9.1.4.5 | Images of text | manual (the UI uses none) | — |
| 9.1.4.10 | Reflow | auto at 320 CSS px, every language | `test_reflow_at_320_css_px` |
| 9.1.4.11 | Non-text contrast | partial: form control boundaries, focus indicators; charts manual | `test_form_control_boundaries_contrast`, `test_focus_indicator_contrast` |
| 9.1.4.12 | Text spacing | auto: WCAG spacing values injected, no content lost | `test_text_spacing_override` |
| 9.1.4.13 | Content on hover or focus | auto for `role=tooltip` | `test_tooltips_dismissible_hoverable_persistent` |
| 9.2.1.1 | Keyboard | auto: every control is a Tab stop; popups, dialogs and tabs work by keyboard | `test_every_control_reachable_by_tab_without_trap`, `test_popups_close_with_escape_and_return_focus`, `test_dialogs_close_with_escape`, `test_tabs_follow_arrow_key_pattern` |
| 9.2.1.2 | No keyboard trap | auto | `test_every_control_reachable_by_tab_without_trap` |
| 9.2.1.4 | Character key shortcuts | manual (the UI defines none) | — |
| 9.2.2.1 | Timing adjustable | manual | — |
| 9.2.2.2 | Pause, stop, hide | partial: nothing loops on an idle page; reduced motion respected | `test_no_endless_animation_at_rest`, `test_reduced_motion_is_respected` |
| 9.2.3.1 | Three flashes | manual | — |
| 9.2.4.1 | Bypass blocks | auto: skip link and landmarks | `test_consistent_navigation_and_landmarks`; axe `bypass`, `region` |
| 9.2.4.2 | Page titled | auto: present, unique and translated in every language | `test_page_titles`; axe `document-title` |
| 9.2.4.3 | Focus order | partial: nothing hidden takes focus, no positive tabindex; logical order is manual | `test_focused_element_is_on_screen`; axe `tabindex` |
| 9.2.4.4 | Link purpose | partial: links have a name | axe `link-name` |
| 9.2.4.5 | Multiple ways | manual (single-purpose app with a nav on every page) | — |
| 9.2.4.6 | Headings and labels | partial: present and non-empty; whether they are descriptive is manual | `test_heading_structure`; axe `empty-heading`, `label` |
| 9.2.4.7 | Focus visible | auto: each Tab stop looks different with focus, light + dark | `test_focus_is_visible` |
| 9.2.5.1–2, 9.2.5.4 | Pointer gestures, cancellation, motion | manual (the UI uses plain clicks only) | — |
| 9.2.5.3 | Label in name | auto | `test_label_in_name` |
| 9.3.1.1 | Language of page | auto, on load and after switching language | `test_page_language`; axe `html-has-lang`, `html-lang-valid` |
| 9.3.1.2 | Language of parts | auto: Chinese text on non-Chinese pages must be translated or marked | `test_language_of_parts`; axe `valid-lang` |
| 9.3.2.1 | On focus | auto: focus never navigates or opens windows | `test_every_control_reachable_by_tab_without_trap` |
| 9.3.2.2 | On input | manual | — |
| 9.3.2.3 | Consistent navigation | auto | `test_consistent_navigation_and_landmarks` |
| 9.3.2.4 | Consistent identification | partial: same nav names on every page | `test_consistent_navigation_and_landmarks` |
| 9.3.3.1 | Error identification | auto for required/invalid fields on submit, error text in the page language | `test_error_identification` |
| 9.3.3.2 | Labels or instructions | auto for presence | axe `label`, `select-name` |
| 9.3.3.3–4 | Error suggestion / prevention | manual | — |
| 9.4.1.1 | Parsing | obsolete in WCAG 2.2, covered by ARIA/ID checks | axe `duplicate-id-aria` |
| 9.4.1.2 | Name, role, value | auto | axe `aria-*`, `button-name`, `nested-interactive`, … |
| 9.4.1.3 | Status messages | partial: live regions are valid; whether each status is announced is manual | axe `aria-*` |

Beyond WCAG: axe best-practice rules (landmarks, heading order, …) and
**forced colours / Windows high contrast** (`test_forced_colors_mode`) are
checked too.

## Manual review still needed

Before claiming BITV conformance, have a person check the **manual** rows and
the human part of the **partial** rows, ideally with a screen reader (NVDA +
Firefox, VoiceOver + Safari):

- meaningful alt texts and labels
- logical reading and focus order
- understandable error messages
- announcements of status changes (an audit starting, finishing or failing)
- the chart alternatives (data tables and summaries)
