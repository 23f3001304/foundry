---
# The agency's Account Director signs off inside, so the client sees nothing until it is done.
approver: '@switch-mattermost-{bridge}-account-director:localhost'
# Only the agency's own staff manage a client's work on the dashboard. A client never signs in.
dashboard:
  - login: '{switch_email}'
    acts_as: '@switch-mattermost-{bridge}-account-director:localhost'
---

Ambaryug Teas is a fictional heritage tea house, and everything in this folder is made up for the demo. So is Bhorvela Studio, the agency that works for it.
