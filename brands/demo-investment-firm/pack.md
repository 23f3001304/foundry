---
# The scene takes no daily notes, so there is no update_rule. With one, a figure an office sends could be sorted as a note.
report_room: studio
approver: '@switch-mattermost-{bridge}-analyst-lead:localhost'
# A demo is played at any hour with due times minutes away. A reminder held for the morning would never go out.
working_hours: [00:00, 23:59]
# Digits only, so what the reader takes out of an answer is a bare figure, and the check for one far from its peers can read it.
measures:
  - assets under management, as a whole number of USD millions, digits only
  - fee revenue, as a whole number of USD millions, digits only
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
---

Kasauti Capital Partners is a fictional investment firm, and everything in this folder is made up for the demo, including every figure. Its reports are internal summaries of made-up numbers, never advice.
