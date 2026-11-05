# The dashboard's design system

Everything visible comes from `static/style.css`, the macros in `templates/_ui.html`, the shapes in `shapes.py` and the charts in `charts.py`. `tests/test_dashboard_design.py` fails when the rules below are broken.

## Rules

- **Colour is the system, and each colour has a job.** Five gradient families, written down below. Neutrals carry everything else, so a colour on a page always means something.
- **One saturated moment a page.** The overview has its hero shape, and a job's page has its banner when something happened. The rest of the page stays quiet so that one thing lands. A job that is just running has no banner, because nothing happened.
- **A clear order on every page.** Title, then tabs, then state pills, then the big thing, then the charts, then the detail. Hairlines before boxes: a table has no card round it, and a section is a row with a chevron.
- **Colour is only written in the tokens block.** A rule names a token, and a component reads `--fam-grad`, `--fam-dot`, `--fam-text`, `--fam-wash` and `--fam-line` from whichever family it sits in. It never names a colour.
- **The 4px rule.** Every padding, margin, gap, height, radius and offset is a token. Only 1px borders and the 2px focus ring are off the grid, and a border is taken out of the padding beside it, so what you measure from a shape's edge is on the scale.
- **Everything leads somewhere.** A figure, a "needs you" row, a stage and a job row each link to the list or the place where it can be acted on, and each answers the mouse and the press.
- **Every empty or result page offers the next step.**
- **No scripts and no inline styles.** The Content-Security-Policy stays as it is in `app.py`. Fonts, pictures and icons come from `/static`, and shapes and charts are drawn on the server.
- **Words carry the meaning.** A mark, a shape, a sprite or a chart never says something the text beside it doesn't. Shapes and sprites are hidden from screen readers, and a chart says what it shows in words.
- **Light by default.** Light is what gets designed and judged, whatever the system says. `:root` sets the whole look. Hierarchy comes from value: a white panel on a warm off-white page, and greys that step down. The bright lime is for shapes and gradients only, because it can't carry words on white, so the one accent, `--primary`, is the same hue taken deep enough to pass AA, and it is the primary button, the current tab and the focus ring. Red stays small: a dot or a soft chip, plus the one loud shape when something is stuck.
- **Dark is soft.** `:root[data-theme="dark"]`, set when the `foundry-theme` cookie says dark, changes the neutrals, the accent, the bar, the soft fills and the marks. There is no black and no white in it: the ground is lifted to `--paper` #1a1b16 and words start at an off-white `--ink`, about 13 to 1. Each step down is clearly lower and all of them hold AA. There is no switch on the page yet, because setting a choice needs a form and an address of its own.

## The families

Each runs from a bright hue to a deeper one and is shown as a gradient, a dot, a soft fill with matching words, or a chart line. Hues are our own and are picked to sit around the logo's lime.

| Family | Tokens | What it means |
|---|---|---|
| Lime | `--lime-*` | Good and finished: delivered, the primary action, the Work group, and the logo's own colour |
| Ember | `--ember-*` | Needs someone: a stuck job or a card waiting on this login. Nothing else may use it |
| Azure | `--azure-*` | Foundry at work: being made, cards opening, files, and the Setup group |
| Orchid | `--orchid-*` | Being checked: the reviewer and sign-off |
| Sun | `--sun-*` | With the people: the brief and the inputs being collected, a connection someone has to look at, Responses and the Action log in the side bar |

`queries.py` ties each stage to its family in `STEP_FAMILIES`, and `family_of` says stuck is ember and done is lime whatever the stage. `.fam-lime` and the rest set a family on an element, and the state classes `.working`, `.waiting`, `.done`, `.idle` and `.stuck` bring one for a status mark that has none. Every family also has a forge glow for a banner, `--forge-lime` and the rest: near black on the left, and heat from behind the button on the right, in five stops of its own (`--lime-forge-1` to `-5`). Lime cools through green and sun through amber, so neither turns olive or muddy on the way down. Words are white and the button is white in every family, and the words stop at 62% of the banner, so a long line wraps before white stops passing on what is behind it. On a phone the button is full width, so the heat comes up from under it, and its height is fixed so a long message can't reach it.

Ember is not used for a fall in a number. A delta that moved is green, one that didn't is quiet, and ember only appears on a chart when the job has stopped.

## Shapes

Drawn in `shapes.py` as our own paths, in one family each. `shapes.defs()` puts every gradient on a page once and hidden, and a part names one with `fill="url(#id)"`, so no colour goes in the markup.

| Shape | Function | Where |
|---|---|---|
| Cut-out | `shapes.cut_out(family)` | The overview's hero: long curves and one sharp cusp hugging the bottom of a rounded panel, with the figures in a bar over it. Ember when something is stuck or waiting on this login, otherwise lime |
| Grid tile | `shapes.grid_tile(family)` | Sign-in, empty states and Generated work's header: a family's gradient with thin dark lines, and a dark card overlapping it and running off the edge |
| Icon tile | `tile(icon, family)` | Beside a section's title, a small square in its family's gradient |

## Tokens

| Group | Values |
|---|---|
| Space | `--space-` 4, 8, 12, 16, 20, 24, 32, 40, 48, 64 |
| Type | `--text-` / `--line-` 12/16, 13/16 (the side bar's rows), 14/20, 16/24, 20/28, 24/32, 32/40 |
| Radius | `--radius-` 4 (chip, and a row in a small menu), 8 (control), 16 (panel, banner, card, the hero's bar), 24 (hero and sign-in) |
| Control height | `--control-` 24 (a button in a table), 28 (a row in the side bar), 32, 36, 40 |
| Icons and sprites | `--size-` 16, 24, 32, 48, 64, 96 |
| Layout | `--gutter`, `--gap`, `--section`, `--sidebar`, `--side-folded`, `--logo-nudge`, `--viewer-head`, `--viewer-slide`, `--rail`, `--content`, `--measure`, `--form`, `--sign-in`, `--sign-in-art`, `--hero`, `--hero-shape`, `--col-*`, `--step`, `--tabbar` |
| Motion | `--dur-fast` 120ms, `--dur-base` 200ms, `--dur-slow` 320ms, `--dur-reveal` 640ms, `--frame` 120ms, `--frame-slow` 320ms, `--ease-out` |
| Neutrals | `--paper --panel --sunken --hover --current --rule --rule-strong --field --ink --ink-soft --ink-faint --ink-quiet`, leaning very slightly toward the logo's olive |
| Accent and focus | `--primary --primary-hover --primary-ink --focus` |
| The hero's bar and words on colour | `--bar --bar-hover --bar-rule --bar-ink --bar-soft --on-bright --on-deep --grid-line --none-1 --none-2` |
| Gradients | `--grad-lime --grad-ember --grad-azure --grad-orchid --grad-sun --grad-none`, and `--forge-lime --forge-ember --forge-azure --forge-orchid --forge-sun` with `--forge-shape`. A gradient is only written here |

## Spacing

One step for one kind of relationship. Things that belong together sit closer than things that don't, and every gap of a kind on a page is the same.

| Step | Between |
|---|---|
| 4 | A label and its value, and a value and its note |
| 8 | A title and its tabs. A cell's head and what is under it. A chip and the next chip. A shape and the shape nested in it |
| 12 | A figure and its chart, a chart and its legend, a section's head and what it heads |
| 16 | The padding of a cell, a banner and a row: the inner edge |
| `--gap`, 16 and 12 on a phone | Panel to panel, and each thing in a page's stack: head, tabs, pills, banner, panel, folds |
| `--section`, 40 and 32 on a phone | Section to section |

**The two left edges.** Titles and section heads sit on the page's outer edge. Everything inside a panel, a banner or a list row sits on the inner edge, 16 in from it, so banner words, a panel's strip, a chart cell, a fold's chevron and a row's first word all line up, and a row's last chevron ends at the same place in every list. What is inside a fold is already on that edge, so a table there takes no more. The hero is the one exception: it is the page's biggest shape, so its words sit 32 in, on a phone 24, and the figures in its bar line up with them.

**A shape nested in a rounded shape.** Equal insets on the sides it is near, and its radius is the outer radius minus that inset, so the corners run parallel:

| Outer | Inset | Inner |
|---|---|---|
| `.hero` 24 | 8 | `.hero-bar` 16 |
| `.hero-bar` 16 | 8 | `.figure` 8 |
| `.banner` 16, on a phone | 8 | `.banner-go` 8 |
| `.more-panel` 16 | 8 | `.nav-item` 8 |
| `.switcher-menu` 8 | 4 | `.switcher-item` 4 |

The hero's "See the jobs" takes the other honest form: a clean end cell of the bar, split by a hairline and running to its edges, so it takes the bar's own outer corners. Beside the words of a banner on a wider screen the button sits well inside the corner, so there is nothing to run parallel to: it is an ordinary control of radius 8, with 32 above, right and below for as long as the words fit two lines. Longer words make the banner taller, and the right stays 32.

**Rows.** A list row is 40 tall with one line and 56 with a second, hairline included, in a table or not. A table's head row is 32. A fold's row is 48.

## Components

Each has one definition, with its states: rest, hover, focus (one shared ring), active and disabled where it can be.

| Component | Class | Notes |
|---|---|---|
| Page title | `page_title()`, `.title` | A breadcrumb in the h1: the way back is muted and keeps its size, and where you are is not muted. A long name wraps under the way back, and all of it shows |
| Long words | `overflow-wrap: anywhere` | Nothing a person reads is cut, because it could hold a figure or an id they are deciding on. A word with no spaces in it, such as a file's name, wraps. The only things that end in an ellipsis are the side menu's own labels |
| Job tabs | `job_tabs()`, `.tabs` | Underlined. Job, Timeline, Files, and Chain once something is flagged |
| State pills | `.state-pills`, `.state-pill` | Under the title: a coloured dot, and the current one outlined |
| Hero | `.hero` | The overview's one loud thing, with `.hero-bar` and `.figure` inside it |
| Banner | `.banner` | The job page's one loud thing, one at a time. A forge glow in the job's family, with white words and one white button. It says what happened, and the button goes to where it can be dealt with. What it says isn't said again below it |
| Chart panel | `.chart-panel`, `.chart-cell` | One bordered panel cut by hairlines into cells, each with a title and a delta. A cell with nothing to draw says so and has no delta, and a job with nothing to chart has no cells |
| Delta | `.delta` | A soft chip beside a chart's title. `.delta-good`, `.delta-flat`, `.delta-stuck` |
| Legend | `legend()`, `.legend` | Diamonds in the line's own colour, with mono values |
| Icon tile | `tile()`, `.tile` | One family's gradient beside a section title |
| Figure | `.figure` | Label with its arrow beside it, and the number under them, on the hero's bar. The whole figure is the link |
| Pill | `.pill` | A short fact or a count. `.pill-needs` needs you |
| Chip | `.chip-link` | A filter, kept in the address, with a dot in the stage's family |
| Button | `button` `.button` | `.primary`, `.danger` (inverted, not red), `.quiet`, `.button-wide` |
| Nav item | `.nav-item` `.tab` | Side bar and bottom bar. Where you are is a soft filled row |
| Switcher | `switcher()`, `.switcher` | Which business, built with details |
| Table | `table.list` | No card round it, hairlines only, small grey heads, and a row turns into a short block on a phone. Jobs, Connections, Data, flagged things, timelines and files are all this |
| Link row | `.link-row` | A table row that is one link, with a chevron at its end |
| Card row | `.response-row` | A card as one row of name, kind and status, in the same columns as a table. What it says and asks opens under it, already open when it is waiting for an answer |
| Section | `.fold` | A row with a chevron and a tile, built with details |
| Rail | `.rail`, `.facts` | Label and value pairs beside a job, then its stages |
| Stepper | `.stepper` `.stepper-named` | The stage it is at wears its state's shape. In the rail each stage says its status |
| Progress bar | `charts.meter` | Fills on load |
| Status mark | `.stage` with `.done .working .waiting .idle .stuck .trouble` | A soft fill and matching words, and a dot, diamond, ring, dash, square or triangle. Drawn with borders alone. `.trouble` is a connection that isn't working, which is not a stuck job |
| Alert | `.alert` `.alert-done` | Marked with `!` and a border |
| Avatar | `avatar()`, `.avatar` | Initials in a quiet circle. No colour, because no person is ever ranked or marked |
| Viewer | `viewer.html`, `.viewer-head`, `.viewer-stage` | A page of its own for a work file, with no side bar. The name, its job and Download, with Close at the top right going back where the person came from. A picture is fitted whole on a calm ground and never blown up. A deck shows the pictures of its slides that the maker's tools already made, from `foundry-looks/<deck>/` beside it, when their stamp says they are of exactly this version and each one is really in that folder. The dashboard never makes any. Anything else says it opens after downloading |
| Empty state | `empty_state()` | A grid tile, a character at rest, what is true and the next step |
| Sprite | `sprite()` | See below |

## Navigation

The side bar has the mark and a fold control, then the business, then Overview and Responses, then the labelled groups Work (Jobs, Generated work, Action log) and Setup (Connections, Data), then the person and sign out. There is no top bar.

It recedes and belongs to the page. It sits on `--paper` with no panel colour and no line. It starts with one brand block: the mark in the icon column, ink 20 tall, then the word Foundry with the business under it, smaller and quieter, in the text column. With several businesses that second line is the switcher, and its menu opens under the whole block. The mark, the block and the fold share one centre line, which is the page title's, so the bar and the page start level. The pages start 24 under the block. It has three levels below that. A label (`.nav-label`) is 12px in `--ink-quiet`, with no icon, and can't be pressed. A page (`.nav-item`) is 13px regular in `--ink-faint`, with a small muted icon and its name on one shared edge, and every page has both. The mark's ink, the labels, the icons' ink and the person's avatar share one left edge at 20, and the text edge is 44. `--logo-nudge` moves the mark so its ink, not its box, sits on that edge. The page you're on is the only bright thing, in `--ink` on a quiet `--hover` fill, with its icon in the accent. Spacing shows the structure: rows touch inside a group, and groups are 24 apart. 

A count (`.nav-count`) is a plain small number in `--ink-faint`, never a pill. A stuck count adds one small ember dot beside it and nothing else, because that's the real news. Both `--ink-faint` and `--ink-quiet` hold AA on the page. The fold lasts until the next page, because keeping it would need a script or a cookie.

From 1024px down the logo and the business stay along the top, and a bar along the bottom has Overview, Jobs, Responses, Generated work and More. Badges count across every business the login has: cards waiting on it, and stuck jobs. A jobs list narrowed to one business says how many more are stuck in the others. A login with several businesses sees one overview at a time, and the first one until it chooses.

The logo is `static/logo.svg` and the full word is `static/wordmark.svg`, so changing either is one file. The side bar uses the logo with the word Foundry in the normal type, and only the sign-in page uses the full word.

## Charts

Every number comes from `queries.py`, scoped to what the login may see. No chart ranks or compares people.

- **A job's three charts** are running counts from its own log at twelve even points of its life. The band is the real gap between two lines, for example asked for and in. It is not a confidence band.
- **The overview's charts** are per day over the last 14 days, and the fill under a line is only a fade.
- **Jobs through the stages** is one flat bar, each stage as long as its share of the open jobs and in its own family's colour with no blending, a hairline where one meets the next, and each stage's count listed under it.
- **Lines** are saturated, in the family of what they count, with a soft fill, a dashed line at zero and a diamond at the end. Bars and meters use a family's bright hue.

## Characters

Sheets are in `static/sprites`, built by `tools/make_sprites.py` from `assets/team` and `stickers/base`. Frame one of a sheet is the still, so a page at rest or with motion turned off shows the still. Moves are whole sprite pixels on hard steps.

One character per context: on the overview's hero, at the stage a job is at in its rail, in an empty state and at sign-in. A figure, a table row and a chart carry none.

| State | Character | Reaction |
|---|---|---|
| Brief | Apprentice | Still |
| Collecting, or a card waiting | Smith with a question | The question mark bobs twice. Nothing taps, because nobody is being hurried |
| Being made | Designer | Still |
| Review | Reviewer | Still |
| Sign-off | Smith | Still |
| Approved, being delivered | Smith on the way | Still |
| Delivered | Smith with confetti | A hop, twice |
| Stuck | Smith with a stop sign | Shakes twice |
| Empty page | Any of the team | Blinks and breathes, three times, then rests |
| Sign-in | Smith | Waves twice |
| A button's result came back done, or a file was saved | Smith with a tick | Nods |
| Under the mouse, on the hero, a stage or an empty state | Whoever is there | A small hop |

A reaction belongs to a job or a page, never to a person, and a character never stands beside someone's name. Keep to a few things moving at once, nothing moving over data, and no loop that doesn't end.

## Motion

A chart's line reveals from the left, bars and meters grow, numbers rise a little, the hero's shape swells once, and a row or a button answers in `--dur-fast`. With motion turned off, nothing moves and every character stands at its still.
