# Demo script (about 10 minutes)

Start with `docker compose up --build`. All demo passwords are `relay-demo-pass`. Keep Mailpit (http://localhost:8025) open in a second tab so the audience sees each email arrive.

1. **The problem (30 s).** Shared instruments are booked over WhatsApp, which leads to double-bookings and unclear rules.

2. **Student books their own lab's instrument.** Sign in as `priya.joshi@relay.test` (Quantum Materials Lab, PHY).
   - Resources → filter **I can book** → *Cryostat B (Dilution Fridge)*, which is `lab_only`.
   - Drag across a slot in the week view. The dialog snaps to the 1-hour steps and shows the rules.
   - Try booking outside opening hours. You get a specific error with no round trip to the server.
   - Book it. The booking appears in teal as "your booking".

3. **Double-booking is impossible.** In a private window, sign in as another PHY student and try the same slot. You get a 409 with the next three free slots offered as buttons. Join the waitlist.
   Go back to Priya and cancel. The other student's **Bell** shows a waitlist offer, and **My bookings** has "Confirm booking".

4. **Outsider asks for access.** Sign in as a CSA student (any member of *Machine Learning Lab* in the YAML).
   - Open *Confocal Microscope* (Soft Matter Lab, `institute_approval`). Instead of "Book" there's **Request access**.
   - Send a request with a justification.

5. **The professor decides.** Sign in as the Soft Matter Lab professor (see YAML).
   - **Inbox** shows the request with the requester's department and verification status.
   - Approve it, shortening the end date. Mailpit shows the approval email.
   - Back as the CSA student, without signing in again, the page now shows **Book** (AC-R1).

6. **Revoke.** As the professor: Inbox → Active grants → Revoke. The student's future bookings on that instrument are cancelled and they're notified (AC-R5).

7. **Recurring lab meeting.** As `pooja.rao@relay.test`, open *Lab Meeting Room PH-101* → Book → **Repeat this meeting**, every Wednesday, 12 times, invite a student. The invite email in Mailpit carries an `.ics` attachment.

8. **Maintenance and settings.** Still as the professor: resource → **Settings** → block four hours for maintenance over an existing booking. You'll see who will be affected before confirming.

9. **Reports.** **Reports**, last 30 days: booked hours, utilization, cancellations and the daily chart. Download the CSVs.

10. **Department verification.** Sign in as `aditya.verma@relay.test` (PHY admin) → **Admin** → confirm `new.student@relay.test`. That student can now book `department`-policy PHY instruments.
