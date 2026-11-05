---
name: Kasauti Capital Partners
colors:
  primary: "#9D988C"
  accent: "#EBC15F"
  ink: "#F1EADC"
  paper: "#141312"
fonts:
  heading: Source Serif Pro
  body: Source Sans Pro
style: touchstone
business_type: Global investment firm
audience: The firm's partners and analysts, reading an internal report
stickers: subtle
voice: Plain, careful and exact. Says what each figure is and who gave it. No hype, no forecasts and no advice.
---
Kasauti Capital Partners is a fictional global investment firm, made up for this demo along with everything in this folder, and every figure in it is made up too. It is not a real company. Kasauti is Hindi for touchstone, the dark stone a goldsmith rubs gold on to test it.

Everything the firm writes here is an internal summary of made-up numbers. It is never investment advice, and it never tells anyone to buy, sell or hold anything. Say so on the first slide of every deck: "Internal summary of made-up figures. Not advice." Give build_deck that line as its subtitle, so it is a smaller line under the title, and keep the title to its own words. Give the quarter in the title as build_deck's highlight, so it is lit in gold.

Use the paper colour, the black of the stone, for backgrounds and the ink colour, the colour of bone, for text. Keep the ash for what recedes, and use the gold once on a page, for the one thing that matters most. A deck gets all of this from build_deck, which draws the stone and rubs the strokes in ash and gold.

The logo is a river stone with one rub of gold. build_deck puts it at the top left of the first slide with the firm's name beside it, and small in the foot of every other slide, so do not place it on a slide yourself. Anywhere else, put it on the paper colour and leave clear space around it, at least a quarter of its width.

Write every amount in USD millions, in digits with commas between the thousands, and say USD millions where the amount is shown. Name the office and the quarter next to every figure. A figure nobody sent is written as "not received", with no number in its place, no stroke and no source: give it to build_deck as null.

Make each slide say one thing. Show what a slide is about with build_deck's big_number layout, with each office's figure in its labels and values, so the largest or the one you highlight is lit and the rest recede. Show growth with its chart layout, with the unit "%". Use a table to say who gave each figure.

Work every chart out with the data tools, never with your own sums. The history is the file `sources/quarterly_aum.csv` in this brand folder, with each office's assets under management at the end of each of its last five quarters. Give read_table and calculate its full path. For each office's growth over those quarters, call `calculate` with the operation growth, the column "Assets under management (USD millions)", group_by Office and order_by Quarter. An office may send a file as its answer in place of a typed figure. Open it by its name with read_table, and add up its rows with calculate.

Quote only a figure an office gave you or a figure `calculate` returned. Never quote a raw cell of `quarterly_aum.csv`: only `calculate` records where a figure came from, and a figure with no record is marked on the final card as having no source. Say which office gave each figure you quote from an answer.

Never correct or leave out an office's figure. If one looks far from the others, still show the figure the office gave, say so on the slide and name the office. The big_number and chart layouts do this in words by themselves, and so does a table on a slide with sources when its column holds at least three figures. A table on a slide with no sources does not, so there say it in the slide's title.
