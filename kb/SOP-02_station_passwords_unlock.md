# SOP-02: Thin Client Station Passwords and Unlock Requests

**Applies to:** All 42 thin client stations (PC-01 to PC-42), students, teachers and the Lab Administrator.
**Common phrases:** station password, what is the password, forgot password, reset password, unlock PC, unlock request, PC still locked, ano password ng PC, pahingi ng password, nakalimutan ang password, pa-unlock ng PC, naka-lock pa rin

## Who knows the station passwords
1. Every station has one station account. Its password is known **only to teachers and the Lab Administrator**.
2. **Students are never given a station password** - not by teachers, not by LabAssist.
3. LabAssist never shows, sends or stores any password in the chat.
4. Asking other people for station passwords, or trying to guess them, violates the lab rules (SOP-13).

## Requesting an unlock (students and teachers)
1. First follow SOP-01 (wait 15 minutes, ask the teacher to log the station in).
2. If the station is still locked, tell LabAssist the **unit number**, e.g. "PC-12 is still locked after 15 minutes".
3. LabAssist files an **unlock request** ticket (category Station Access, status Pending approval) and notifies the Lab Administrator.
4. The Lab Administrator approves the request and unlocks the station from the Admin Dashboard.
5. The teacher then logs the station in. Ask LabAssist for the ticket status (e.g. "status of TKT-0004") to follow up.

## Teachers
1. Teachers may unlock stations through LabAssist ("unlock PC-12").
2. Teachers log stations in for students; never type the password where students can see it.
3. Report a station password that may have been seen by students so the Lab Administrator can change it.

## Password resets (Lab Administrator only)
1. Only the Lab Administrator resets station passwords, from the Admin Dashboard.
2. The new password is shown once on the dashboard and stored only as a secure hash.
3. The administrator gives the new password to the teachers directly, never through the chat.

## Escalate when
1. A station is still locked after the unlock request is approved.
2. A station password may have been leaked to students.
3. Someone repeatedly tries to log in to stations without a teacher.
