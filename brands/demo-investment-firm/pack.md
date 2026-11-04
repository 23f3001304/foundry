---
update_rule: A note from a regional office saying what has happened or will happen in its business, such as a mandate won or lost, a filing made, a staffing change, a client review or a market event it is watching.
report_room: analysts
approver: '@switch-mattermost-{bridge}-analyst-lead:localhost'
# A demo is played at any hour with due times minutes away. A reminder held for the morning would never go out.
working_hours: [00:00, 23:59]
measures:
  - assets under management in USD millions, as a whole number
  - fee revenue in USD millions, as a whole number
dashboard:
  - login: '{switch_email}'
    acts_as: '@switch-mattermost-{bridge}-analyst-lead:localhost'
glossary: |
  AUM: assets under management, the market value of the money the firm looks after for its clients
  USD millions: United States dollars counted in millions, so 1,000 means one billion dollars
  FY27: the firm's financial year from April 2026 to March 2027
  Q2 FY27: July to September 2026, the second quarter of FY27
  mandate: an agreement to manage a client's money
  net inflow: money clients added to the firm's funds, less the money they took out
  office: one of the firm's five regional offices, Office A to Office E
report_format: |
  One short paragraph for each office. Start with the office's name. Say what happened, what it is waiting on and what comes next, with dates and numbers, as far as the notes say. Plain English, no greeting, and never a suggestion to buy, sell or hold anything.
---

Kasauti Capital Partners is a fictional investment firm, and everything in this folder is made up for the demo, including every figure. Its reports are internal summaries of made-up numbers, never advice.
