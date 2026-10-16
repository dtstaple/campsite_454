# Midterm metrics: Sprints 1–5 (TM05)

Read from Jira (Atlassian MCP, project TM05, board 2) on 2026-10-14. Nothing in Jira or the repo was changed.

**Sprint 5 is closed.** It closed 2026-10-14 03:51:40 UTC (2026-10-13 23:51 ET). Sprint 6 (id 73) is active and outside the scope of this report.

| Sprint | Jira id | Started (UTC) | Closed (UTC) |
|---|---|---|---|
| Sprint 1 | 3 | 2026-09-09 03:00 | 2026-09-16 03:01 |
| Sprint 2 | 37 | 2026-09-16 04:00 | 2026-09-23 02:24 |
| Sprint 3 | 38 | 2026-09-23 03:59 | 2026-09-30 03:03 |
| Sprint 4 | 71 | 2026-09-30 03:30 | 2026-10-07 01:31 |
| Sprint 5 | 72 | 2026-10-07 03:59 | 2026-10-14 03:51 |

## Slide block

```
Stories completed: 79
Stories rolled over: 2
Avg completed per sprint: 15.8
Avg rolled over per sprint: 0.4
Avg story points per sprint: Davis 42.0 · Bleron 5.6 ·
  Abdulrahman 6.4 · Sahaj 3.8
Why stories rolled over:
  - Frontend work blocked waiting on the API (Retro, Sprint 5: "Waited on the API before the work could be verified")
  - Dependent backend work started late (Retro, Sprint 5: "Started late in the sprint, which put pressure on dependent work")
  - Work not started or flagged early enough (Retro, Sprint 3: "Took on two stories and only started one, so the second had to be picked up by someone else late in the sprint")
```

- The counts include the five Sprint Report stories. Feature stories alone: 74 completed, 14.8 per sprint.
- See the "How rollovers were detected" section for why the rollover count is 2 rather than 0.

## Method

- **Stories only.** Issue type Story. Subtasks are excluded from the story and points counts and included in the hours.
- **Excluded stories:**
  - TM05-2 (the Scrum Master schedule): permanently in the backlog.
  - TM05-1: Done on 2026-09-07, before Sprint 1, with no sprint.
  - TM05-41: reached Done on 2026-10-02 with no sprint, two minutes after it was taken out of Sprint 4.
  - Every Sprint 6 story.
- **Completed** means status Done with a resolution date inside the window of a sprint the story belonged to at that time.
- **Story points** come from `customfield_10016` ("Story point estimate"). TM05-42 has 3 there, which confirms the field.
- **Points per member** are credited to the story's assignee.
- **Hours** are the sum of `timeSpent` from every worklog on stories and subtasks: 90 worklogs on 75 issues, none truncated. Each worklog is assigned to the sprint whose window contains its `started` time.

## Per-sprint table

| Sprint | Feature stories done | Report story done | Total done | Points (feature) | Points (all) | Rolled over out of the sprint | Descoped |
|---|---|---|---|---|---|---|---|
| Sprint 1 | 4 | 1 | 5 | 15 | 16 | 0 | 0 |
| Sprint 2 | 7 | 1 | 8 | 39 | 40 | 0 | 0 |
| Sprint 3 | 12 | 1 | 13 | 42 | 43 | 1 (TM05-41) | 0 |
| Sprint 4 | 22 | 1 | 23 | 91 | 92 | 0 | 1 confirmed, 1 unverifiable |
| Sprint 5 | 29 | 1 | 30 | 97 | 98 | 1 (TM05-72) | 0 |
| **Total** | **74** | **5** | **79** | **284** | **289** | **2** | **1 + 1** |
| **Avg / sprint (÷5)** | **14.8** | **1.0** | **15.8** | **56.8** | **57.8** | **0.4** | |

Sprint 4's descopes are TM05-46 (confirmed) and TM05-49 (unverifiable, because it has been deleted).

The Sprint Report stories are:

- TM05-3, Sprint 1, Davis Stapleton
- TM05-18, Sprint 2, Bleron Balidemaj
- TM05-36, Sprint 3, Abdulrahman Shaalan
- TM05-51, Sprint 4, Sahaj Soni
- TM05-92, Sprint 5, Bleron Balidemaj

All five are Done, each within its own sprint.

## Per-member table

### Story points completed

All stories, with feature stories only in parentheses where the two differ:

| Member | S1 | S2 | S3 | S4 | S5 | Total | Avg / sprint (÷5) |
|---|---|---|---|---|---|---|---|
| Davis Stapleton | 9 (8) | 26 | 21 | 74 | 80 | 210 (209) | **42.0** (41.8) |
| Bleron Balidemaj | 3 | 6 (5) | 8 | 3 | 8 (7) | 28 (26) | **5.6** (5.2) |
| Abdulrahman Shaalan | 2 | 5 | 9 (8) | 6 | 10 | 32 (31) | **6.4** (6.2) |
| Sahaj Soni | 2 | 3 | 5 | 9 (8) | 0 | 19 (18) | **3.8** (3.6) |
| **Team** | 16 | 40 | 43 | 92 | 98 | 289 (284) | 57.8 (56.8) |

Sahaj's 0 in Sprint 5 is because TM05-72 (2 pts), Sahaj's Sprint 5 story, did not reach Done.

### Worklog hours logged (stories and subtasks)

| Member | S1 | S2 | S3 | S4 | S5 | Total | Avg / sprint (÷5) |
|---|---|---|---|---|---|---|---|
| Davis Stapleton | 7.42 | 8.00 | 11.00 | 8.25 | 6.92 | 41.58 | **8.3** |
| Bleron Balidemaj | 3.00 | 3.00 | 4.00 | 2.00 | 4.00 | 16.00 | **3.2** |
| Abdulrahman Shaalan | 4.00 | 4.50 | 4.00 | 5.50 | 7.00 | 25.00 | **5.0** |
| Sahaj Soni | 4.00 | 2.00 | 3.50 | 3.50 | 2.00 | 15.00 | **3.0** |

The course target is about 4 h per person per sprint. Bleron and Sahaj average below it.

## Rollover list

### TM05-41 "Coding Standard"

- Assignee and size: Davis Stapleton, 2 pts.
- Sprints: Sprint 3 → Sprint 4.
- Sprint-field history:
  - Created 2026-09-24, in the middle of Sprint 3.
  - Removed from Sprint 3 at 2026-09-29 23:03:46 ET, 13 seconds before Sprint 3 closed (23:03:59 ET). It was not Done.
  - Added to Sprint 4 at 23:04:06 ET.
  - Removed from Sprint 4 at 2026-10-02 16:08 ET.
  - Done at 16:26 ET the same day, with no sprint.
- Rollover comment: **none.** The only comment is the delivery note from 2026-10-02:
  > "Coding conventions drafted and up for review in PR #31: https://github.com/dtstaple/campsite_454/pull/31 … Next steps: each team member fills in their row of the Team agreement table (Section 9), and the PDF gets attached to this story."
- Outcome: the work was delivered during Sprint 4, but the story is not credited to any sprint.

### TM05-72 "Make map marker colours match campsite scores"

- Assignee and size: Sahaj Soni, 2 pts.
- Sprints: Sprint 5 → Sprint 6.
- Sprint-field history:
  - Added to Sprint 5 on 2026-10-06 21:32 ET.
  - Removed from Sprint 5 at 2026-10-13 23:46:50 ET, about 5 minutes before Sprint 5 closed (23:51:40 ET). It was In Progress.
  - Added to Sprint 6 at 23:51:55 ET.
  - It is still In Progress.
- Rollover comment: **none.** The only comment on the story is from Sahaj Soni on 2026-10-13 14:55:
  > "Draft PR: https://github.com/dtstaple/campsite_454/pull/82"
- The blocker is recorded on a related story instead. Sahaj Soni on TM05-86, 2026-10-13 23:38:
  > "TM05-72 (PR #82) is built against score (0–100, or null) and score_status on the /api/campsites/ features… routes.py scores along-trail sites with score_campsite(site, config), but the detail endpoint uses stored_only=True. For an unenriched site, the trail list can show a number while the detail endpoint says pending. Could the map features use the same call as the detail endpoint, so the map, list and panel all agree?"

### Top reasons, matched to Retrospective entries

1. **Frontend work blocked waiting on the API.** This applies to TM05-72, which needs the score fields from TM05-86.
   - Sprint 5 Retrospective (TM05-96), Sahaj Soni:
     > "Waited on the API before the work could be verified"
   - The same pattern a sprint earlier, Sprint 4 Retrospective (TM05-55), Sahaj Soni:
     > "Score display was blocked waiting on the API rather than progressing in parallel"
2. **The dependent backend work started late.** This also applies to TM05-72, whose backend half is TM05-86.
   - Sprint 5 Retrospective (TM05-96), Abdulrahman Shaalan:
     > "Started late in the sprint, which put pressure on dependent work"
3. **Work not started or flagged early enough.** This is the closest Sprint 3 match for TM05-41, which was added to Sprint 3 mid-sprint on 09-24.
   - Sprint 3 Retrospective (TM05-40), Abdulrahman Shaalan:
     > "Took on two stories and only started one, so the second had to be picked up by someone else late in the sprint"
   - This entry is about Abdulrahman's own stories, not TM05-41. **No retrospective names TM05-41 or gives its reason**, so this match is thematic, not a direct attribution.

Related, for the descope below:

- Sprint 4 Retrospective (TM05-55), Abdulrahman Shaalan:
  > "The original story scope was larger than the time remaining once work started"
- Sprints 4 and 5, Davis Stapleton, on workload concentration:
  > "Took on too much of the sprint alone"

  > "Still carried most of the sprint's points"

## Descoped list (removed before close; not rollovers)

| Key | Title | Assignee | Pts | Sprint-field history | Outcome |
|---|---|---|---|---|---|
| TM05-46 | Let users weight the factors themselves | Abdulrahman Shaalan | 3 | Added to Sprint 4 on 09-29. Removed on 2026-10-05 22:31 ET, a day before Sprint 4 closed. Re-added to Sprint 5 on 10-06. | Done in Sprint 5 (10-13). Counted as a Sprint 5 completion. |
| TM05-49 | (unknown) | (unknown) | — | **Cannot be verified.** Jira returns 404 ("Issue does not exist or you do not have permission"). | Deleted. Listed only because the brief names it. |

## How rollovers were detected

1. All 92 TM05 stories were pulled with their current sprint field (`customfield_10020`).
2. For each story, the changelog of the Sprint field was read: every add and remove, with timestamps and author. Every sprint change was made by Davis Stapleton.
3. Any story that appears in more than one sprint is a candidate. There were four: TM05-2, TM05-41, TM05-46 and TM05-72.
4. Each candidate was classified by when it left the sprint, compared with that sprint's close time (`completeDate`):
   - **TM05-2** is excluded. It is the backlog-only Scrum Master schedule, and was briefly added to and removed from Sprints 4 and 5.
   - **TM05-46: descoped.** It was removed a day before Sprint 4 closed, as a mid-sprint scope change.
   - **TM05-41 and TM05-72: rolled over.** Each was not Done, removed in the closing minutes of its sprint, and added to the next sprint in the same sitting. That is the manual form of a carry-over at close.
5. Sprint 6 assignments are outside the scope, except as the destination of TM05-72.

## Flagged ambiguities

- **The rollover count depends on the rule.** Read literally ("in a sprint when it closed"), the count is **0**. Neither TM05-41 nor TM05-72 was still in its sprint at the moment of close: one left 13 seconds before, the other about 5 minutes before. Both were moved by hand rather than through Jira's complete-sprint dialog. This report counts them as rollovers (**2**, avg 0.4) because they were unfinished and moved straight into the next sprint as part of closing. If the strict rule is wanted, report 0 / 0.0 and list both as late descopes.
- **No rollover comments exist.** CLAUDE.md requires a rollover comment (current state, blocker, next step), but no comment anywhere in TM05 records a rollover, descope or carry-over. Neither TM05-41 nor TM05-72 has one.
- **The Sprint 5 Review contradicts Jira.**
  - The Sprint 5 Review (TM05-95) lists "Matching marker colours (TM05-72)" as accomplished and says "Rolled over to Sprint 6: None".
  - In Jira, TM05-72 is In Progress in Sprint 6.
  - Every Sprint Review (TM05-6, 21, 39, 54, 95) says "Rolled over: None", including Sprint 3's, despite TM05-41.
- **TM05-41 is Done but not in any sprint.** Its 2 points are not credited to any sprint or member here. Credited to Sprint 4, where the work happened, Davis would have 76 in Sprint 4 and average 42.4.
- **TM05-49 is deleted** (404), so its sprint history cannot be checked.
- **Hours depend on the attribution basis.**
  - The tables use each worklog's own start date. Attributing worklogs to their issue's sprint instead moves Sahaj's 2 h on TM05-72 to Sprint 6, which gives Sahaj 0 h in Sprint 5 and an average of 2.6.
  - Davis's 0.17 h on TM05-1 is pre-sprint.
  - A 1.5 h TM05-12 worklog dated 2026-09-16 sits on the Sprint 1/2 boundary. It is counted in Sprint 1 here. Counted in Sprint 2 instead, Davis would have 5.92 h in Sprint 1 and 9.5 h in Sprint 2. The average is unchanged.
- **Data hygiene noticed while reading:**
  - TM05-46's merge comment has a placeholder PR link ("PR #__").
  - The Sprint 2 Retrospective (TM05-22) has no attendance line.
  - The Sprint 4 Review (TM05-54) shows raw wiki markup (`h3.`/`h4.`) and has no Feedback section.
