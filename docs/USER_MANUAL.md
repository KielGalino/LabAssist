# LabAssist - User Manual

LabAssist is the first-level helpdesk of the CSIS ICT Laboratory. Open it at
`http://localhost:8501` (or the address your teacher gives you).

## Students

**You do not need an account or a password.** Stations are logged in by your teacher.

1. In the left panel choose **Student**. There is nothing to type: no sign-in, no account and
   no password.
2. Describe the problem in English, Filipino or Taglish. Include the **unit number** written on the
   monitor (e.g. `PC-12`).
3. LabAssist answers with the steps from the official lab procedure and shows the source
   (e.g. `Source: SOP-03`). Try the steps first.
4. If the steps did not work, say so ("I already tried, PC-12 is still locked"). LabAssist files a
   ticket or an unlock request and gives you a ticket number (e.g. `TKT-0004`).
5. Your requests appear above the chat with their status. You can also ask
   "What is the status of TKT-0004?".

You can also use the small **Lab Helpdesk** button on any page where the lab has embedded it
(it opens the same assistant in a panel: choose Student or Teacher, then chat).
A sample lab portal page with the button is at `http://localhost:8000/portal`.

Things to know:
- Answers appear while they are being written (streaming); ticket cards appear when it finishes.
- LabAssist never gives out passwords. If a station asks for one, your teacher logs it in.
- In an emergency (sparks, smoke, burning smell): step away, tell your teacher, then report it.
  LabAssist files a critical ticket immediately.
- Do not type personal information (email, phone number). If you do, it is masked automatically.
- You can send up to 12 messages per minute.

## Teachers

1. Choose **Teacher** in the left panel (no sign-in).
2. You can ask LabAssist anything a student can. "Please unlock PC-12" files an unlock request
   right away (no troubleshooting steps) and marks it **high priority**; the Lab Administrator
   unlocks the station from the Admin Dashboard.
3. Software requests and lab reservations: describe what you need; LabAssist files the ticket
   (software requests need 3 school days, reservations 2 school days).
4. Never type a station password where students can see it. Report a possible leak so the
   Lab Administrator can reset it.

## Lab Administrator

**Admin Dashboard** (admin PIN required):
- **Pending Requests**: each request shows the requester, unit and issue, with four buttons:
  - *Unlock station* - the station becomes active and the ticket is resolved.
  - *Reset password* - a new station password is shown **once** on the dashboard (copy it and give
    it to the teachers); only its hash is stored.
  - *Mark resolved* / *Reject*.
- **Stations**: all 42 units grouped by MultiPoint server (green active, red locked,
  yellow needs repair), with a manual status control.
- **Analytics** and **LLM observability**: requests by category and by intent, resolutions, daily
  trends (requests, response time, deflection rate), p95 response time, tokens used, offline
  fallbacks, mean time to resolution.
- **Jira** (optional): when configured in `.env`, urgent tickets are also created in Jira and the
  Jira key appears in the ticket table (`external_ref`).
- **Chat widget**: give other sites the line
  `<script src="http://<server>:8000/static/embed.js"></script>` (requires `run_api.bat`).
- **All tickets** (filter by status, priority and category: each filter is a dropdown with
  checkboxes and an *All* option) and the **Audit log** (every action, sign-in failure and
  blocked request).

**Knowledge Base** (admin PIN required): view SOPs, upload a new SOP (`.md`, scanned for
injected instructions), delete an SOP, rebuild the search index, and test retrieval scores.

Security tip: change `ADMIN_PIN` in `.env` before real use. It is the only PIN in LabAssist.
