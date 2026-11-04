---
update_rule: A note from a team saying what has happened or will happen in its work, such as stories closed, defects found or fixed, a QA or UAT result, or what comes next.
report_room: studio
approver: '@switch-mattermost-{bridge}-delivery-manager:localhost'
# A demo is played at any hour with due times minutes away. A reminder held for the morning would never go out.
working_hours: [00:00, 23:59]
measures:
  - stories closed this sprint
  - defects open
  - UAT test cases passed
dashboard:
  - login: admin@switch.local
    acts_as: '@switch-mattermost-{bridge}-delivery-manager:localhost'
glossary: |
  QA: quality assurance, the people who test a build before the client sees it
  UAT: user acceptance testing, where the client's own testers try a release
  sprint: one two-week block of planned work
  story: one small piece of planned work
  retest: QA checking a fixed defect again
report_format: |
  One short paragraph for each team. Start with the team's name. Say what finished, what is blocked and what comes next, with dates and numbers, as far as the notes say. Plain English, no greeting.
---

Morpankh Systems is a fictional IT services firm, and everything in this folder is made up for the demo.
