# AHEAD AI Agent — V0 Gaps, V1 Roadmap, and Open Questions

**For:** Internal planning / conversation with George's team  
**Written:** June 2026  
**V0 status:** Prototype fully functional end-to-end (DHIS2 sandbox, WhatsApp alerts, write-back confirmed)

---

## What V0 Does

V0 replaces the email + Excel DQ loop with a real-time notification system:

- **Detects** data quality issues within 30 seconds of form submission (outlier, DTP inconsistency) or daily (missing reports)
- **Notifies** the facility worker via WhatsApp with numbered response options matching the AHEAD Excel dropdowns
- **Parses** the response using Claude (handles natural language, not just exact numeric input)
- **Confirms** before writing: asks YES/NO before any automatic DHIS2 correction
- **Writes back** corrected values to DHIS2 automatically (6-month average, set to zero, specific value, DTP set-both)
- **Escalates** unresolved issues up the cascade (facility → woreda → zone → region → national digest)
- **Logs** everything in a live dashboard at localhost:5001/issues

V0 is a working proof-of-concept, not a production system. It runs on a local DHIS2 sandbox with synthetic Ethiopia data and a Twilio WhatsApp sandbox number.

---

## Gap Analysis: V0 vs AHEAD Guide

### DQ Detection Gaps

| Gap | Description | Impact |
|---|---|---|
| **3 of 5 outlier methods missing** | V0 implements SD (method 1) and absolute diff (method 5). MAD (method 2), Median AD (method 3), and Lowess regression (method 4) are not implemented. | V0 misses borderline outliers that 4/5 methods would catch. Only extreme cases like BCG=970 are reliably flagged. |
| **No multi-method confidence triage** | AHEAD guide: 4+ methods = strong flag (act now), 1–3 = possible flag (batch review). V0 treats all flags equally. | No prioritisation — facility gets the same alert regardless of statistical confidence. |
| **Missing data: registration only** | V0 checks whether a facility clicked "Complete" on their form. It does not check for blank cells within a submitted form. | A facility that submits with some vaccines left empty won't be flagged. |
| **No region-name consistency check** | Section 2.1 of the AHEAD guide: flag admin1–admin2 pairs with fewer records than expected (indicates naming inconsistency across years). | Not implemented at all. This requires cross-year record counting and string matching — a batch process, not a real-time check. |
| **Only `<1yr` age band checked** | V0 uses `CATEGORY_OPTION_COMBOS['under_1']` throughout. The `>1yr` column is ignored. | Catch-up doses and outreach sessions in the `≥1yr` column are never checked for outliers or DTP consistency. |

### Notification and Response Gaps

| Gap | Description | Impact |
|---|---|---|
| **Single contact per facility** | V0 maps one phone number to each org unit level. In reality, a facility may have multiple data entry staff. | If the registered contact is unavailable, the alert is not delivered to anyone. |
| **No email channel** | Contact table has an `email` column (added for Phase 2) but the agent only sends WhatsApp/SMS. | UNICEF and national-level staff who don't receive WhatsApp alerts have no automated channel. |
| **WhatsApp sandbox only** | V0 uses the Twilio WhatsApp sandbox, which requires opt-in and uses a shared sandbox number. | Not deployable at scale. Production requires either approved Twilio WhatsApp Business API or Africa's Talking SMS. |
| **Options 5/6 for outlier not auto-resolved** | "At health facility doses only" and "Outreach doses only" are recorded but not automatically applied. These require knowing which DHIS2 category option combo maps to each column. | These are logged for HQ to handle manually. Facility gets a confirmation but the data isn't corrected. |
| **DTP option 4 corrects only Penta3** | "Replace with specific values" (plural) in the guide implies correcting both DTP1 and DTP3. V0 only corrects Penta3. | If Penta1 is also wrong, the facility must manually correct it in DHIS2. |
| **No voice channel** | AHEAD guide mentions voice as a notification option. | Relevant for health workers in low-literacy or low-connectivity areas. Not planned for V1 either. |

### Infrastructure and Data Gaps

| Gap | Description | Impact |
|---|---|---|
| **Outlier baseline contamination (masking)** | V0 computes Z-scores against the historical mean and SD. If previous errors were never corrected, they pull the mean toward them and inflate the SD — making new outliers harder to detect. Example: an uncorrected BCG=200 from 2025 shifts the baseline so BCG=190 in 2026 appears plausible. This is called *masking*. | Undetected historical errors silently reduce sensitivity over time. The more contamination in the history, the higher the bar a new outlier must clear. V0's leave-one-out only removes the *current* value from its own baseline — it does not clean other historical errors. |
| **Robust statistics not implemented** | Median Absolute Deviation (method 3) uses the median instead of the mean, making it immune to historical contamination — the median cannot be shifted by extreme values. This is specifically why the AHEAD guide specifies it as one of five methods. | Without Median AD, the detection system is fragile against real-world DHIS2 data that likely contains pre-existing uncorrected errors. |
| **SQLite database** | V0 uses SQLite (single-file, no concurrency). | Not suitable for multiple simultaneous connections in production. Migration to PostgreSQL is already planned (connection string change only). |
| **Manual contact seeding** | Phone numbers are hardcoded in `agent/seed_contacts.py`. | Requires a developer to update and re-run the script every time a contact changes. Needs a UI or CSV import. |
| **No contact registry integration with DHIS2** | George's team confirmed DHIS2 does not maintain phone numbers. The agent uses its own SQLite registry. | The two systems are permanently out of sync — any staff change requires a manual update to the contact table. |
| **Synthetic data only** | V0 uses 28 months of generated data for 12 facilities. | Thresholds are not calibrated to real Ethiopia data. The absolute threshold of 100 doses, for example, may be too high for small health posts in real deployments. |
| **No admin2-level checks** | DTP thresholds are defined for admin2 in config.py but the engine only runs at facility level. | Admin2 rollup checks (e.g., zone-level DTP consistency) are not triggered. |
| **No downstream integration** | Corrections written back to DHIS2 are not propagated to the AHEAD Excel/analytics pipeline. | The cleaned dataset that feeds denominator assessment and slide decks still requires manual export and UNICEF HQ processing. |

---

## V1 Roadmap (Phase 2 Priorities)

### P0 — Must-have before any real deployment

| Item | What it involves |
|---|---|
| **Production SMS/WhatsApp** | Register for Africa's Talking (for Ethiopian numbers) or Twilio WhatsApp Business API. Update `agent/sms.py` — provider swap is the only code change. |
| **PostgreSQL migration** | Change the SQLite connection string in `agent/db.py` to a PostgreSQL URI. Schema is already compatible. |
| **Contact registry management** | Build a simple CSV import script or minimal admin UI so AHEAD team can update phone numbers without touching code. |
| **Server deployment** | Deploy agent to a cloud VM (AWS/Azure/GCP). Replace ngrok with a real domain and SSL cert. Set up as a systemd service with auto-restart. |
| **Twilio webhook security** | Add Twilio signature validation to `POST /webhook/sms`. Currently unauthenticated — anyone who knows the URL can POST fake replies. |

### P1 — Significantly improves detection quality

| Item | What it involves |
|---|---|
| **Complete 5-method outlier ensemble** | Implement MAD (method 2), Median AD (method 3), Lowess regression (method 4) in `dhis2_client.get_outliers()`. Add method count to the issue record. Send strong-flag alerts immediately; batch possible-flag alerts into a weekly digest. |
| **Cell-level missing data detection** | After the dataset registration check, query individual data values and flag specific antigen/period cells that are blank within a submitted form. |
| **Admin2 rollup checks** | Aggregate facility data to admin2 level, run DTP consistency with admin2 thresholds. Requires hierarchical aggregation step before DTP check. |
| **Multi-method confidence in SMS** | Show in the alert message how many methods flagged it: "flagged by 2 of 5 methods (possible)" vs "flagged by 4 of 5 methods (strong)." Maps to AHEAD's triage hierarchy. |
| **>1yr age band checks** | Extend outlier and DTP checks to include the `≥1yr` category option combo. |

### P2 — Quality-of-life and integration improvements

| Item | What it involves |
|---|---|
| **Email notifications** | `contacts.email` column already exists. Add an email channel to `agent/sms.py` using SendGrid or SMTP. National/regional staff get email digests. |
| **Region-name consistency check** | Batch process: count records per (admin1, admin2, year) and flag pairs with fewer than expected. Requires cross-year data access. |
| **Monthly summary to national TWG** | Implement the `_job_monthly_summary()` stub in `agent/app.py`. Generate a formatted digest of all open issues for the prior month. |
| **Audit trail export** | Export the `issues` + `conversations` tables as CSV or feed them into the AHEAD Excel pipeline. Closes the loop between the agent's decision log and HQ analytics. |
| **Threshold tuning UI** | Allow AHEAD team to adjust `OUTLIER_Z_THRESHOLD`, `DTP_THRESHOLDS`, etc. via a config endpoint or env vars without redeploying. |
| **Multi-country deployment** | `config.example.py` already documents the UID parameters to update. Write a setup wizard that queries a target DHIS2 instance and auto-populates config. |

---

## Open Questions for George's Team

These need answers before V1 can be designed with confidence.

### On the data and thresholds

1. **What is the actual reporting deadline in Ethiopia?** V0 defaults to day 10 of the following month. Is that accurate, or does it vary by level (facility vs woreda)?

2. **Are the AHEAD Table 1 thresholds (2 SD, 100 doses) right for Ethiopia at facility level?** V0's false-positive flood showed that small health posts with mean BCG ≈ 2 doses produce Z-scores > 2 naturally. Should thresholds be tiered by facility type (health center vs health post vs hospital)?

3. **Which antigens should the agent monitor?** V0 covers BCG, Penta1, Penta3, MR1. Are OPV, PCV, rotavirus, yellow fever relevant for AHEAD? The EPI package has them.

4. **What should happen when a facility has `<3 months` of history?** V0 skips detection. The AHEAD guide doesn't address this edge case. Should new facilities get a grace period?

### On the notification design

5. **Is WhatsApp the right channel for Ethiopian health facility workers?** What are they actually using in the field — WhatsApp, regular SMS, phone calls? Does this vary between health centers and health posts?

6. **Who actually holds the phone number at a facility?** Is it the facility in-charge, the data focal point, or the person who physically enters DHIS2 data? For escalation, does the woreda HMIS officer have a single number or does it vary by district?

7. **What language should alerts be sent in?** V0 sends English. Should the agent support Amharic? Are data entry workers comfortable responding in English?

8. **Should "Campaign/PIRI" be a response option?** The AHEAD guide's outlier response options don't include it, but it's the most common real-world reason for a spike. George's team may want it added back.

### On the workflow integration

9. **Does AHEAD currently produce a DQ check sheet per country, or per admin1 region?** V0 generates one issue log across all facilities. If George sends region-specific Excel files, the issue log may need to be partitioned by region.

10. **How does a correction in DHIS2 flow back into the AHEAD Excel and analytics pipeline?** V0 writes corrected values to DHIS2 but has no connection to the cleaned dataset that feeds denominator assessment and slide decks. Is that pipeline fully manual at UNICEF HQ, or does it pull from DHIS2 programmatically?

11. **Is there an existing approval workflow in DHIS2 for data corrections?** If the EPI dataset uses DHIS2 data approval, writing directly via `agent_service` may bypass it. Should the agent create a data approval note, or is direct write-back acceptable?

12. **What should happen to an issue if the facility re-enters correct data without replying to the alert?** V0 only closes an issue when the worker replies. If they just re-enter the correct value in DHIS2, the issue stays open. Should the next poll cycle auto-close it if the value is now within range?

### On production readiness

13. **Is Africa's Talking the right SMS provider for Ethiopia?** Are there MoH-preferred messaging platforms or carrier agreements that UNICEF uses for other programs?

14. **Who owns and maintains the contact registry?** George confirmed DHIS2 doesn't maintain phone numbers. Is there an existing list maintained by the AHEAD team in Excel, or does it need to be built from scratch?

15. **How clean is the historical DHIS2 data in Ethiopia?** V0's outlier detection degrades silently if uncorrected errors already exist in the historical baseline — old errors pull the mean toward them, making new outliers harder to detect (the "masking" problem). Before deploying on a real country instance, a one-time historical audit is needed: either manually clean known errors, or confirm that the robust statistics in V1 (Median AD, method 3) are sufficient to handle the level of contamination.

16. **What is the data residency requirement?** Can the agent database (issue log, phone numbers, correction history) be hosted on AWS/Azure, or does it need to be on MoH infrastructure in Ethiopia?
